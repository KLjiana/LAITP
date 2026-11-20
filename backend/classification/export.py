"""ONNX 导出与模型产物包发布（T05）。

输入是 T04 的训练运行目录（``training-artifact.json`` + ``model.pt``），输出是
契约 1.0 的模型产物包（manifest、model.onnx、labels、固定样本、参考结果、阈值）
以及绑定产物与清单摘要的转换验证记录。

导出后用 ``onnx.checker``、ONNX Runtime 实际推理和 T02 产物包校验器共同确认；
任何一步失败都不发布。固定样本的参考结果来自部署端（ONNX Runtime），转换记录
同时保存训练端与部署端的原始输出差异。
"""

from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import onnx
import onnxruntime as ort
import torch

from ..contracts import integrity
from ..contracts.errors import Code, Issue, Report, Stage
from ..contracts.manifest import validate_model_package
from ..contracts.runtime_spec import RuntimeProfile
from .model import DEFAULT_WEIGHTS_ID, TrainingError, WeightReference, load_weight_reference
from .preprocess import PreprocessSpec, load_image
from .training import TRAINING_RECORD_FORMAT, load_training_artifact

EXPORT_RECORD_FORMAT = "laitp-export-record-1.0"
THRESHOLDS_VERSION = "1.0"
DEFAULT_OPSET = 17
RUNTIME_VERSION_RANGE = ">=1.20.0,<2.0.0"
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


class ExportError(Exception):
    """导出失败。``code`` 是稳定错误码，``issues`` 可携带校验器问题。"""

    def __init__(
        self, code: Code, message: str, issues: Sequence[Issue] = ()
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.issues = tuple(issues)


@dataclass(frozen=True)
class ExportConfig:
    run_dir: Path
    output_root: Path
    artifact_id: str
    project_id: str
    platform: str = "windows-x64"
    opset: int = DEFAULT_OPSET
    weights_config: Path | None = None
    weights_id: str = DEFAULT_WEIGHTS_ID
    data_root: Path | None = None
    samples_per_class: int = 1
    logit_abs_tolerance: float = 1e-3
    logit_rel_tolerance: float = 1e-3
    created_at: datetime | None = None


@dataclass(frozen=True)
class ExportResult:
    artifact_id: str
    package_dir: Path
    manifest_path: Path
    conversion_record_path: Path
    checks: dict[str, Any]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _timestamp(value: datetime | None) -> str:
    moment = value if value is not None else datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ExportError(Code.EXPORT_CONFIG_INVALID, "created_at 必须带时区")
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _validate_config(config: ExportConfig) -> None:
    for name, value in (
        ("artifact_id", config.artifact_id),
        ("project_id", config.project_id),
    ):
        if not IDENTIFIER.match(str(value)):
            raise ExportError(
                Code.EXPORT_CONFIG_INVALID,
                f"{name} {value!r} 只能包含字母、数字、点、下划线和连字符",
            )
    if not 7 <= config.opset <= 21:
        raise ExportError(
            Code.EXPORT_CONFIG_INVALID, f"opset {config.opset} 不在 7..21 范围内"
        )
    if config.platform not in ("windows-x64", "linux-x64"):
        raise ExportError(
            Code.EXPORT_CONFIG_INVALID, f"暂不支持目标平台 {config.platform!r}"
        )
    if config.samples_per_class < 1:
        raise ExportError(Code.EXPORT_CONFIG_INVALID, "samples_per_class 必须 ≥ 1")
    if config.logit_abs_tolerance <= 0 or config.logit_rel_tolerance <= 0:
        raise ExportError(Code.EXPORT_CONFIG_INVALID, "数值容差必须为正数")
    final_dir = Path(config.output_root) / config.artifact_id
    if final_dir.exists():
        raise ExportError(
            Code.EXPORT_CONFIG_INVALID,
            f"导出目录已存在：{final_dir}；发布不可原地修改，请使用新的 artifact_id",
        )


def _read_training_record(run_dir: Path) -> tuple[dict[str, Any], bytes]:
    record_path = Path(run_dir) / "training-artifact.json"
    try:
        raw = record_path.read_bytes()
    except OSError as error:
        raise ExportError(
            Code.EXPORT_SOURCE_INVALID,
            f"无法读取训练记录 {record_path}：{error.strerror or error}",
        ) from error
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExportError(
            Code.EXPORT_SOURCE_INVALID,
            f"训练记录不是有效 JSON：{error}",
        ) from error
    if record.get("format") != TRAINING_RECORD_FORMAT:
        raise ExportError(
            Code.EXPORT_SOURCE_INVALID,
            f"训练记录格式不是 {TRAINING_RECORD_FORMAT}",
        )

    files = record.get("files", {})
    if "model.pt" not in files:
        raise ExportError(Code.EXPORT_SOURCE_INVALID, "训练记录未列出 model.pt")
    for name, info in files.items():
        target = Path(run_dir) / name
        if not target.is_file():
            raise ExportError(
                Code.EXPORT_SOURCE_INVALID, f"训练记录中的文件 {name} 不存在"
            )
        actual = integrity.sha256_file(target)
        if actual != info.get("sha256"):
            raise ExportError(
                Code.EXPORT_SOURCE_INVALID,
                f"训练文件 {name} 摘要 {actual} 与记录不一致",
            )
    return record, raw


def _resolve_weights(
    config: ExportConfig, record: dict[str, Any]
) -> WeightReference | None:
    if config.weights_config is None:
        return None
    weight = load_weight_reference(config.weights_config, weights_id=config.weights_id)
    recorded = record.get("model", {}).get("weights_sha256")
    if recorded and recorded != weight.sha256:
        raise ExportError(
            Code.EXPORT_SOURCE_INVALID,
            f"权重摘要 {weight.sha256} 与训练记录 {recorded} 不一致",
        )
    return weight


def _select_samples(
    config: ExportConfig, run_dir: Path, classes: Sequence[str]
) -> tuple[list[dict[str, Any]], Path]:
    manifest_path = Path(run_dir) / "dataset-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ExportError(
            Code.EXPORT_SOURCE_INVALID, f"无法读取训练数据清单副本：{error}"
        ) from error
    if list(manifest.get("classes", [])) != list(classes):
        raise ExportError(
            Code.EXPORT_SOURCE_INVALID, "数据清单类别表与训练记录不一致"
        )

    data_root = Path(config.data_root) if config.data_root is not None else None
    if data_root is None:
        config_path = Path(run_dir) / "config.json"
        try:
            run_config = json.loads(config_path.read_text(encoding="utf-8"))
            data_root = Path(run_config["dataset_root"])
        except (OSError, json.JSONDecodeError, KeyError) as error:
            raise ExportError(
                Code.EXPORT_CONFIG_INVALID,
                "无法从训练配置确定数据根目录，请显式提供 data_root",
            ) from error

    val = sorted(
        (sample for sample in manifest["samples"] if sample["split"] == "val"),
        key=lambda sample: sample["path"],
    )
    chosen: list[dict[str, Any]] = []
    for class_id, label in enumerate(classes):
        candidates = [sample for sample in val if sample["class_id"] == class_id]
        if len(candidates) < config.samples_per_class:
            raise ExportError(
                Code.EXPORT_SAMPLE_MISSING,
                f"类别 {label!r} 只有 {len(candidates)} 张验证图片，"
                f"固定样本需要 {config.samples_per_class} 张",
            )
        chosen.extend(candidates[: config.samples_per_class])
    return chosen, data_root


def _export_onnx(
    model: torch.nn.Module,
    config: ExportConfig,
    preprocess: PreprocessSpec,
    onnx_path: Path,
) -> int:
    dummy = torch.zeros(1, 3, preprocess.height, preprocess.width)
    try:
        with torch.no_grad():
            torch.onnx.export(
                model,
                dummy,
                str(onnx_path),
                input_names=["images"],
                output_names=["logits"],
                opset_version=config.opset,
                do_constant_folding=True,
                dynamo=False,
            )
    except Exception as error:  # torch 导出异常类型不固定
        raise ExportError(
            Code.EXPORT_ONNX_FAILED, f"torch.onnx.export 失败：{error}"
        ) from error

    try:
        onnx.checker.check_model(str(onnx_path))
    except Exception as error:
        raise ExportError(
            Code.EXPORT_ONNX_FAILED, f"ONNX 模型未通过官方检查：{error}"
        ) from error

    proto = onnx.load(str(onnx_path))
    opset = next(
        (
            int(entry.version)
            for entry in proto.opset_import
            if entry.domain in ("", "ai.onnx")
        ),
        None,
    )
    if opset != config.opset:
        raise ExportError(
            Code.EXPORT_VERIFICATION_FAILED,
            f"导出 opset {opset} 与配置 {config.opset} 不一致",
        )
    return opset


def _open_session(onnx_path: Path) -> tuple[ort.InferenceSession, list[int], list[int]]:
    try:
        session = ort.InferenceSession(
            str(onnx_path), providers=["CPUExecutionProvider"]
        )
    except Exception as error:
        raise ExportError(
            Code.EXPORT_VERIFICATION_FAILED, f"ONNX Runtime 无法加载模型：{error}"
        ) from error
    inputs = session.get_inputs()
    outputs = session.get_outputs()
    if len(inputs) != 1 or inputs[0].name != "images":
        raise ExportError(
            Code.EXPORT_VERIFICATION_FAILED,
            f"模型输入应为单一 images，实际 {[item.name for item in inputs]}",
        )
    if len(outputs) != 1 or outputs[0].name != "logits":
        raise ExportError(
            Code.EXPORT_VERIFICATION_FAILED,
            f"模型输出应为单一 logits，实际 {[item.name for item in outputs]}",
        )
    return session, list(inputs[0].shape), list(outputs[0].shape)


def _softmax(values: np.ndarray) -> np.ndarray:
    shifted = values - np.max(values)
    exponential = np.exp(shifted)
    return exponential / exponential.sum()


def _verify_fixed_samples(
    config: ExportConfig,
    model: torch.nn.Module,
    session: ort.InferenceSession,
    preprocess: PreprocessSpec,
    classes: Sequence[str],
    samples: Sequence[dict[str, Any]],
    data_root: Path,
    package_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    validation_dir = package_dir / "validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    max_abs_diff = 0.0
    max_rel_diff = 0.0
    max_torch_magnitude = 1e-6
    agreements = 0

    for index, sample in enumerate(samples):
        source = data_root / sample["path"]
        if not source.is_file():
            raise ExportError(
                Code.EXPORT_SAMPLE_MISSING,
                f"固定样本文件不存在：{sample['path']}",
            )
        class_id = int(sample["class_id"])
        suffix = source.suffix.lower()
        if suffix not in IMAGE_SUFFIXES:
            suffix = ".png"
        sample_rel = f"validation/class-{class_id}{suffix}"
        if config.samples_per_class > 1:
            sample_rel = f"validation/class-{class_id}-{index}{suffix}"
        expected_rel = (
            f"validation/expected-class-{class_id}.json"
            if config.samples_per_class == 1
            else f"validation/expected-class-{class_id}-{index}.json"
        )
        shutil.copyfile(source, package_dir / sample_rel)

        tensor = preprocess.transform()(load_image(source)).unsqueeze(0)
        with torch.no_grad():
            torch_logits = model(tensor).numpy()[0]
        ort_logits = session.run(["logits"], {"images": tensor.numpy()})[0][0]

        difference = np.abs(torch_logits - ort_logits)
        max_abs_diff = max(max_abs_diff, float(difference.max()))
        max_torch_magnitude = max(max_torch_magnitude, float(np.abs(torch_logits).max()))
        max_rel_diff = max(max_rel_diff, float(difference.max()))

        probabilities = _softmax(ort_logits)
        prediction = int(np.argmax(probabilities))
        if int(np.argmax(torch_logits)) == int(np.argmax(ort_logits)):
            agreements += 1

        expected = {
            "record_version": "1.0",
            "artifact_id": config.artifact_id,
            "sample": {
                "path": sample_rel,
                "class_id": class_id,
                "label": classes[class_id],
                "source_path": sample["path"],
            },
            "input": {
                "shape": list(tensor.shape),
                "dtype": "float32",
                "tensor_sha256": integrity.sha256_bytes(tensor.numpy().tobytes()),
                "preprocess": preprocess.to_dict(),
            },
            "raw_output": ort_logits.tolist(),
            "probabilities": probabilities.tolist(),
            "prediction": {
                "class_id": prediction,
                "label": classes[prediction],
                "probability": float(probabilities[prediction]),
            },
            "runtime": {"name": "onnxruntime", "version": ort.__version__},
        }
        (package_dir / expected_rel).write_text(
            json.dumps(expected, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        records.append(
            {
                "sample": sample_rel,
                "reference_output": expected_rel,
                "class_id": class_id,
                "max_abs_diff": float(difference.max()),
            }
        )

    if max_torch_magnitude > 0:
        max_rel_diff = max_rel_diff / max_torch_magnitude
    agreement = agreements / len(samples)
    checks = {
        "count": len(samples),
        "max_abs_diff": max_abs_diff,
        "max_rel_diff": max_rel_diff,
        "prediction_agreement": agreement,
        "abs_tolerance": config.logit_abs_tolerance,
        "rel_tolerance": config.logit_rel_tolerance,
    }
    if (
        max_abs_diff > config.logit_abs_tolerance
        or max_rel_diff > config.logit_rel_tolerance
        or agreement < 1.0
    ):
        raise ExportError(
            Code.EXPORT_VERIFICATION_FAILED,
            f"训练端与部署端输出差异超出阈值：{json.dumps(checks, ensure_ascii=False)}",
        )
    return records, checks


def _file_entry(package_dir: Path, relative: str, role: str) -> dict[str, Any]:
    target = package_dir / relative
    return {
        "path": relative,
        "role": role,
        "sha256": integrity.sha256_file(target),
        "size_bytes": target.stat().st_size,
    }


def _build_manifest(
    config: ExportConfig,
    record: dict[str, Any],
    record_digest: str,
    preprocess: PreprocessSpec,
    classes: Sequence[str],
    package_dir: Path,
    samples: Sequence[dict[str, Any]],
    onnx_rel: str,
    created_at: str,
    thresholds_rel: str,
) -> dict[str, Any]:
    files = [
        _file_entry(package_dir, onnx_rel, "model"),
        _file_entry(package_dir, "labels.json", "labels"),
        _file_entry(package_dir, thresholds_rel, "thresholds"),
    ]
    validation_samples = []
    for index, sample in enumerate(samples):
        sample_file = sample["sample"]
        files.append(_file_entry(package_dir, sample_file, "validation_sample"))
        files.append(
            _file_entry(package_dir, sample["reference_output"], "reference_output")
        )
        validation_samples.append(
            {
                "name": f"class-{sample['class_id']}",
                "path": sample_file,
                "reference_output": sample["reference_output"],
            }
        )

    return {
        "contract_version": "1.0",
        "artifact_id": config.artifact_id,
        "task": "image_classification",
        "provenance": {
            "project_id": config.project_id,
            "run_id": record["run_id"],
            "dataset_manifest_sha256": record["dataset"]["dataset_manifest_sha256"],
            "created_at": created_at,
            "source": {
                "artifact_id": record["artifact_id"],
                "manifest_sha256": record_digest,
            },
        },
        "files": files,
        "model": {
            "path": onnx_rel,
            "format": "onnx",
            "opset": config.opset,
            "external_data": [],
        },
        "inputs": [
            {
                "name": "images",
                "shape": [1, 3, preprocess.height, preprocess.width],
                "dtype": "float32",
                "layout": "NCHW",
                "color_space": preprocess.color_space,
            }
        ],
        "outputs": [
            {
                "name": "logits",
                "shape": [1, len(classes)],
                "dtype": "float32",
                "meaning": "class_logits",
                "class_axis": 1,
            }
        ],
        "preprocessing": preprocess.manifest_fields(),
        "postprocessing": {
            "executor": "host",
            "steps": [{"op": "softmax", "axis": 1}],
        },
        "labels": {"path": "labels.json", "count": len(classes)},
        "runtime": {
            "runtime": "onnxruntime",
            "version_range": RUNTIME_VERSION_RANGE,
            "platform": config.platform,
            "device": "cpu",
            "required_capabilities": ["onnxruntime-cpu"],
        },
        "conversion": {
            "converter": {
                "name": "torch.onnx.export",
                "version": torch.__version__,
            },
            "quantization": {"mode": "none"},
        },
        "validation": {
            "samples": validation_samples,
            "thresholds": {"path": thresholds_rel},
        },
    }


def export_model(config: ExportConfig) -> ExportResult:
    """导出 ONNX 产物包并写入转换验证记录。"""
    _validate_config(config)
    run_dir = Path(config.run_dir)
    record, record_bytes = _read_training_record(run_dir)
    record_digest = integrity.sha256_bytes(record_bytes)
    weight = _resolve_weights(config, record)

    try:
        loaded = load_training_artifact(
            run_dir / "model.pt",
            weights_path=weight.path if weight is not None else None,
        )
    except TrainingError as error:
        raise ExportError(error.code, error.message) from error

    preprocess = PreprocessSpec.from_dict(record["preprocess"])
    if preprocess != loaded.preprocess:
        raise ExportError(
            Code.EXPORT_SOURCE_INVALID,
            "训练记录中的预处理参数与 model.pt 不一致",
        )
    classes = list(loaded.classes)
    if list(record["dataset"]["classes"]) != classes:
        raise ExportError(Code.EXPORT_SOURCE_INVALID, "训练记录类别表不一致")

    samples, data_root = _select_samples(config, run_dir, classes)
    created_at = _timestamp(config.created_at)

    output_root = Path(config.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    final_dir = output_root / config.artifact_id
    temporary = output_root / f".tmp-{config.artifact_id}-{uuid.uuid4().hex[:8]}"
    package_dir = temporary / "model-package"
    (package_dir / "validation").mkdir(parents=True)
    try:
        onnx_rel = "model.onnx"
        opset = _export_onnx(loaded.model, config, preprocess, package_dir / onnx_rel)
        session, input_shape, output_shape = _open_session(package_dir / onnx_rel)
        expected_input = [1, 3, preprocess.height, preprocess.width]
        expected_output = [1, len(classes)]
        if input_shape != expected_input or output_shape != expected_output:
            raise ExportError(
                Code.EXPORT_VERIFICATION_FAILED,
                f"模型实际张量形状输入 {input_shape} / 输出 {output_shape} "
                f"与预期 {expected_input} / {expected_output} 不一致",
            )

        (package_dir / "labels.json").write_text(
            json.dumps(classes, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        thresholds_rel = "validation/thresholds.json"
        thresholds = {
            "thresholds_version": THRESHOLDS_VERSION,
            "logit_abs_tolerance": config.logit_abs_tolerance,
            "logit_rel_tolerance": config.logit_rel_tolerance,
            "prediction_agreement": 1.0,
            "note": "探索性默认值；正式验收前需按任务、精度与设备冻结，不得事后放宽",
        }
        (package_dir / thresholds_rel).write_text(
            json.dumps(thresholds, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        sample_records, sample_checks = _verify_fixed_samples(
            config,
            loaded.model,
            session,
            preprocess,
            classes,
            samples,
            data_root,
            package_dir,
        )

        manifest = _build_manifest(
            config,
            record,
            record_digest,
            preprocess,
            classes,
            package_dir,
            sample_records,
            onnx_rel,
            created_at,
            thresholds_rel,
        )
        manifest_path = package_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        profile = RuntimeProfile(
            runtime="onnxruntime",
            version=ort.__version__,
            platform=config.platform,
            capabilities=frozenset({"onnxruntime-cpu"}),
        )
        report = validate_model_package(package_dir, runtime_profile=profile)
        if not report.ok:
            raise ExportError(
                Code.EXPORT_PACKAGE_REJECTED,
                "产物包未通过契约校验",
                report.issues,
            )

        manifest_digest = integrity.sha256_file(manifest_path)
        conversion_record = {
            "record_version": EXPORT_RECORD_FORMAT,
            "artifact_id": config.artifact_id,
            "created_at": created_at,
            "status": "passed",
            "manifest": {
                "path": "model-package/manifest.json",
                "sha256": manifest_digest,
            },
            "source": {
                "artifact_id": record["artifact_id"],
                "manifest_sha256": record_digest,
                "run_id": record["run_id"],
                "model_pt_sha256": record["files"]["model.pt"]["sha256"],
                "weights_id": record["model"].get("weights_id"),
                "weights_sha256": record["model"].get("weights_sha256"),
            },
            "converter": {
                "name": "torch.onnx.export",
                "torch": torch.__version__,
                "opset": opset,
            },
            "runtime": {
                "name": "onnxruntime",
                "version": ort.__version__,
                "platform": config.platform,
            },
            "checks": {
                "onnx_checker": "passed",
                "opset": {"declared": config.opset, "actual": opset, "passed": True},
                "input_shape": input_shape,
                "output_shape": output_shape,
                "fixed_samples": sample_checks,
                "package_validation": {"ok": True, "issues": []},
            },
            "thresholds": {
                "path": f"model-package/{thresholds_rel}",
                "sha256": integrity.sha256_file(package_dir / thresholds_rel),
            },
        }
        (temporary / "conversion-record.json").write_text(
            json.dumps(conversion_record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.rename(final_dir)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    return ExportResult(
        artifact_id=config.artifact_id,
        package_dir=final_dir / "model-package",
        manifest_path=final_dir / "model-package" / "manifest.json",
        conversion_record_path=final_dir / "conversion-record.json",
        checks=conversion_record["checks"],
    )
