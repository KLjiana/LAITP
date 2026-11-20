"""完整产物包校验测试（T02）。

每个用例在临时目录生成摘要自洽的产物包，再按场景破坏一个条件，
断言返回稳定错误码与定位。生成的最小 ONNX 模型仅用于张量签名比对。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Callable

import pytest

from backend.contracts import validate_model_package
from backend.contracts.errors import Code
from backend.contracts.onnx_signature import IntrospectionError, ModelSignature
from backend.contracts.tensors import TensorSignature
from tests.support.packages import (
    build_package,
    reopen_manifest,
    runtime_profile,
    save_manifest,
    write_json,
)

PROFILE = runtime_profile()


@pytest.fixture()
def package(tmp_path: Path) -> Path:
    return build_package(tmp_path / "pkg")


def validate(package: Path, profile=runtime_profile(), **kwargs: Any):
    return validate_model_package(package, runtime_profile=profile, **kwargs)


def mutate(
    package: Path,
    change: Callable[[dict[str, Any]], None],
    *,
    refresh: bool = True,
) -> None:
    manifest = reopen_manifest(package)
    change(manifest)
    save_manifest(package, manifest, refresh=refresh)


def assert_code(package: Path, code: Code, profile=runtime_profile()):
    report = validate(package, profile)
    assert report.has(code), f"期望 {code.value}，实际 {[i.code.value for i in report.issues]}"
    return report


# --------------------------------------------------------------------------- #
# 成功路径
# --------------------------------------------------------------------------- #


def test_valid_package_passes(package: Path) -> None:
    report = validate(package)
    assert report.ok, report.issues
    assert report.issues == ()


def test_package_with_chinese_and_space_paths(package: Path, tmp_path: Path) -> None:
    target = tmp_path / "学生 项目" / "模型 包 v1"
    shutil.copytree(package, target)
    report = validate(target)
    assert report.ok, report.issues


# --------------------------------------------------------------------------- #
# 结构、版本与任务
# --------------------------------------------------------------------------- #


def test_missing_required_field_is_rejected(package: Path) -> None:
    mutate(package, lambda manifest: manifest.pop("runtime"))
    report = assert_code(package, Code.SCHEMA_INVALID)
    assert any(issue.location == "runtime" for issue in report.issues)


def test_unknown_preprocessing_op_is_rejected(package: Path) -> None:
    def change(manifest: dict[str, Any]) -> None:
        manifest["preprocessing"]["steps"][0] = {"op": "blur"}

    mutate(package, change)
    report = assert_code(package, Code.SCHEMA_INVALID)
    assert any(issue.location == "preprocessing.steps[0]" for issue in report.issues)


def test_unsupported_contract_major_version(package: Path) -> None:
    mutate(package, lambda manifest: manifest.update(contract_version="2.0"))
    report = assert_code(package, Code.VERSION_UNSUPPORTED_MAJOR)
    assert report.issues[0].location == "contract_version"


def test_unsupported_contract_minor_version(package: Path) -> None:
    mutate(package, lambda manifest: manifest.update(contract_version="1.1"))
    assert_code(package, Code.VERSION_UNSUPPORTED_MINOR)


def test_unimplemented_task_is_rejected(package: Path) -> None:
    mutate(package, lambda manifest: manifest.update(task="object_detection"))
    assert_code(package, Code.TASK_UNSUPPORTED)


def test_non_host_executor_is_rejected(package: Path) -> None:
    def change(manifest: dict[str, Any]) -> None:
        manifest["preprocessing"]["executor"] = "model"

    mutate(package, change)
    report = assert_code(package, Code.EXECUTOR_UNSUPPORTED)
    assert report.issues[0].location == "preprocessing.executor"


# --------------------------------------------------------------------------- #
# 路径与完整性
# --------------------------------------------------------------------------- #


def test_absolute_path_is_rejected(package: Path) -> None:
    def change(manifest: dict[str, Any]) -> None:
        manifest["files"][0]["path"] = "C:/data/model.onnx"
        manifest["model"]["path"] = "C:/data/model.onnx"

    mutate(package, change)
    assert_code(package, Code.SCHEMA_INVALID)


def test_traversal_path_is_rejected(package: Path) -> None:
    def change(manifest: dict[str, Any]) -> None:
        manifest["files"][0]["path"] = "../model.onnx"
        manifest["model"]["path"] = "../model.onnx"

    mutate(package, change)
    report = assert_code(package, Code.PATH_INVALID)
    assert any(issue.location == "files[0].path" for issue in report.issues)


def test_windows_reserved_name_is_rejected(package: Path) -> None:
    def change(manifest: dict[str, Any]) -> None:
        manifest["files"][0]["path"] = "CON.onnx"
        manifest["model"]["path"] = "CON.onnx"

    mutate(package, change)
    assert_code(package, Code.PATH_INVALID)


def test_referenced_file_not_declared_is_rejected(package: Path) -> None:
    mutate(package, lambda manifest: manifest["model"].update(path="model-v2.onnx"))
    report = assert_code(package, Code.PATH_REFERENCE_MISSING)
    assert any(issue.location == "model.path" for issue in report.issues)


def test_role_mismatch_is_rejected(package: Path) -> None:
    def change(manifest: dict[str, Any]) -> None:
        next(e for e in manifest["files"] if e["role"] == "labels")["role"] = "model"

    mutate(package, change)
    report = assert_code(package, Code.FILE_ROLE_MISMATCH)
    assert any(issue.location == "labels.path" for issue in report.issues)


def test_unreferenced_file_is_rejected(package: Path) -> None:
    (package / "README.md").write_text("说明", encoding="utf-8")

    def change(manifest: dict[str, Any]) -> None:
        manifest["files"].append(
            {"path": "README.md", "role": "thresholds", "sha256": "0" * 64}
        )

    mutate(package, change)
    assert_code(package, Code.FILE_UNREFERENCED)


def test_missing_file_is_rejected(package: Path) -> None:
    (package / "validation" / "sample.png").unlink()
    report = assert_code(package, Code.FILE_MISSING)
    assert any(issue.location == "files[2].path" for issue in report.issues)


def test_corrupted_weight_is_rejected(package: Path) -> None:
    with (package / "model.onnx").open("ab") as handle:
        handle.write(b"\x00")
    assert_code(package, Code.FILE_DIGEST_MISMATCH)


def test_labels_reordered_with_old_digest_is_rejected(package: Path) -> None:
    manifest = reopen_manifest(package)
    write_json(package / "labels.json", ["书本", "水杯", "笔袋"])
    save_manifest(package, manifest, refresh=False)
    report = assert_code(package, Code.FILE_DIGEST_MISMATCH)
    assert any(issue.location == "files[1].sha256" for issue in report.issues)


# --------------------------------------------------------------------------- #
# 标签
# --------------------------------------------------------------------------- #


def test_label_count_mismatch_is_rejected(package: Path) -> None:
    write_json(package / "labels.json", ["水杯", "书本"])
    mutate(package, lambda manifest: None)
    assert_code(package, Code.LABELS_COUNT_MISMATCH)


def test_duplicate_label_is_rejected(package: Path) -> None:
    write_json(package / "labels.json", ["水杯", "水杯", "笔袋"])
    mutate(package, lambda manifest: None)
    assert_code(package, Code.LABELS_DUPLICATE)


def test_label_count_must_match_output_class_dim(package: Path) -> None:
    write_json(package / "labels.json", ["水杯", "书本", "笔袋", "尺子"])

    def change(manifest: dict[str, Any]) -> None:
        manifest["labels"]["count"] = 4

    mutate(package, change)
    assert_code(package, Code.LABELS_CLASS_DIM_MISMATCH)


def test_invalid_labels_file_is_rejected(package: Path) -> None:
    (package / "labels.json").write_text('{"class": "水杯"}', encoding="utf-8")
    mutate(package, lambda manifest: None)
    assert_code(package, Code.LABELS_INVALID)


# --------------------------------------------------------------------------- #
# 张量
# --------------------------------------------------------------------------- #


def test_declared_shape_must_match_model(package: Path) -> None:
    def change(manifest: dict[str, Any]) -> None:
        manifest["inputs"][0]["shape"] = [1, 3, 256, 256]
        manifest["preprocessing"]["steps"][0].update(width=256, height=256)

    mutate(package, change)
    report = assert_code(package, Code.TENSOR_SIGNATURE_MISMATCH)
    assert any(issue.location == "inputs[0].shape" for issue in report.issues)


def test_channel_count_mismatch_is_rejected(package: Path) -> None:
    def change(manifest: dict[str, Any]) -> None:
        manifest["inputs"][0]["shape"] = [1, 4, 224, 224]

    mutate(package, change)
    assert_code(package, Code.TENSOR_CHANNEL_INVALID)


def test_batch_dimension_must_be_one(package: Path) -> None:
    def change(manifest: dict[str, Any]) -> None:
        manifest["inputs"][0]["shape"] = [2, 3, 224, 224]

    mutate(package, change)
    assert_code(package, Code.TENSOR_BATCH_INVALID)


def test_opset_must_match_model(package: Path) -> None:
    mutate(package, lambda manifest: manifest["model"].update(opset=13))
    assert_code(package, Code.MODEL_OPSET_MISMATCH)


def test_quantized_tensor_requires_metadata(package: Path) -> None:
    def change(manifest: dict[str, Any]) -> None:
        manifest["inputs"][0]["dtype"] = "int8"

    mutate(package, change)
    assert_code(package, Code.TENSOR_QUANTIZATION_INVALID)


def test_missing_introspection_dependency_is_reported(
    package: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "backend.contracts.manifest.default_introspector", lambda: None
    )
    assert_code(package, Code.TENSOR_INSPECTION_UNAVAILABLE)


class _FixedIntrospector:
    name = "fixed"

    def __init__(self, signature: ModelSignature) -> None:
        self._signature = signature

    def inspect(self, model_path: Path) -> ModelSignature:
        return self._signature


class _FailingIntrospector:
    name = "failing"

    def inspect(self, model_path: Path) -> ModelSignature:
        raise IntrospectionError("模拟读取失败")


def _signature(outputs: tuple[TensorSignature, ...]) -> ModelSignature:
    return ModelSignature(
        inputs=(TensorSignature("images", (1, 3, 224, 224), "float32"),),
        outputs=outputs,
        opset=17,
        ir_version=None,
        tool="fixed",
    )


def test_actual_output_tensor_mismatch_is_rejected(package: Path) -> None:
    reader = _FixedIntrospector(_signature((TensorSignature("logits", (1, 4), "float32"),)))
    report = validate(package, introspector=reader)
    assert report.has(Code.TENSOR_SIGNATURE_MISMATCH)
    assert any(issue.location == "outputs[0].shape" for issue in report.issues)


def test_introspection_failure_is_not_ignored(package: Path) -> None:
    report = validate(package, introspector=_FailingIntrospector())
    assert report.has(Code.TENSOR_INSPECTION_UNAVAILABLE)


# --------------------------------------------------------------------------- #
# 处理语义
# --------------------------------------------------------------------------- #


def test_resize_must_match_input_shape(package: Path) -> None:
    def change(manifest: dict[str, Any]) -> None:
        manifest["preprocessing"]["steps"][0]["height"] = 128

    mutate(package, change)
    assert_code(package, Code.PREPROCESSING_INVALID)


def test_normalize_channel_order_must_match_color_space(package: Path) -> None:
    def change(manifest: dict[str, Any]) -> None:
        manifest["preprocessing"]["steps"][1]["channel_order"] = "BGR"

    mutate(package, change)
    assert_code(package, Code.PREPROCESSING_INVALID)


def test_preprocessing_must_reach_declared_layout(package: Path) -> None:
    def change(manifest: dict[str, Any]) -> None:
        manifest["preprocessing"]["steps"] = manifest["preprocessing"]["steps"][:3]

    mutate(package, change)
    report = assert_code(package, Code.PREPROCESSING_INVALID)
    assert any(
        "布局" in issue.message for issue in report.issues
    )


def test_probabilities_without_softmax_are_valid(package: Path) -> None:
    def change(manifest: dict[str, Any]) -> None:
        manifest["outputs"][0]["meaning"] = "class_probabilities"
        manifest["postprocessing"]["steps"] = []

    mutate(package, change)
    report = validate(package)
    assert report.ok, report.issues


def test_logits_require_softmax(package: Path) -> None:
    mutate(package, lambda manifest: manifest["postprocessing"].update(steps=[]))
    assert_code(package, Code.POSTPROCESSING_INVALID)


def test_probabilities_must_not_run_softmax_twice(package: Path) -> None:
    def change(manifest: dict[str, Any]) -> None:
        manifest["outputs"][0]["meaning"] = "class_probabilities"

    mutate(package, change)
    report = assert_code(package, Code.POSTPROCESSING_INVALID)
    assert any(issue.location == "postprocessing.steps[0]" for issue in report.issues)


def test_softmax_axis_must_match_class_axis(package: Path) -> None:
    def change(manifest: dict[str, Any]) -> None:
        manifest["postprocessing"]["steps"][0]["axis"] = 0

    mutate(package, change)
    assert_code(package, Code.POSTPROCESSING_INVALID)


def test_class_axis_out_of_range_is_rejected(package: Path) -> None:
    def change(manifest: dict[str, Any]) -> None:
        manifest["outputs"][0]["class_axis"] = 3

    mutate(package, change)
    assert_code(package, Code.TENSOR_SHAPE_INVALID)


# --------------------------------------------------------------------------- #
# 运行时
# --------------------------------------------------------------------------- #


def test_missing_runtime_profile_is_rejected(package: Path) -> None:
    report = validate(package, profile=None)
    assert report.has(Code.RUNTIME_PROFILE_MISSING)


def test_runtime_version_must_satisfy_range(package: Path) -> None:
    report = validate(package, profile=runtime_profile(version="1.17.5"))
    assert report.has(Code.RUNTIME_VERSION_INCOMPATIBLE)


def test_runtime_platform_must_match(package: Path) -> None:
    report = validate(package, profile=runtime_profile(platform="linux-x64"))
    assert report.has(Code.RUNTIME_UNSUPPORTED)


def test_required_capability_must_be_available(package: Path) -> None:
    report = validate(package, profile=runtime_profile(capabilities=()))
    assert report.has(Code.RUNTIME_CAPABILITY_MISSING)


def test_board_platform_is_not_supported(package: Path) -> None:
    def change(manifest: dict[str, Any]) -> None:
        manifest["runtime"].update(
            platform="k230",
            board={"model": "K230-CanMV", "firmware_range": ">=1.0.0,<2.0.0"},
        )

    mutate(package, change)
    assert_code(package, Code.BOARD_UNSUPPORTED)


# --------------------------------------------------------------------------- #
# 来源与转换
# --------------------------------------------------------------------------- #


def _add_conversion(manifest: dict[str, Any], mode: str = "none") -> None:
    manifest["provenance"]["source"] = {
        "artifact_id": "art-20261116-0001",
        "manifest_sha256": "a" * 64,
    }
    manifest["conversion"] = {
        "converter": {"name": "laitp-export", "version": "0.1.0"},
        "quantization": {"mode": mode},
    }


def test_conversion_artifact_with_source_is_valid(package: Path) -> None:
    mutate(package, _add_conversion)
    report = validate(package)
    assert report.ok, report.issues


def test_conversion_requires_source_artifact(package: Path) -> None:
    def change(manifest: dict[str, Any]) -> None:
        manifest["conversion"] = {
            "converter": {"name": "laitp-export", "version": "0.1.0"},
            "quantization": {"mode": "none"},
        }

    mutate(package, change)
    report = assert_code(package, Code.SCHEMA_INVALID)
    assert any(issue.location.startswith("provenance") for issue in report.issues)


def test_source_artifact_id_must_differ(package: Path) -> None:
    def change(manifest: dict[str, Any]) -> None:
        _add_conversion(manifest)
        manifest["provenance"]["source"]["artifact_id"] = manifest["artifact_id"]

    mutate(package, change)
    assert_code(package, Code.PROVENANCE_INVALID)


def test_conversion_claiming_no_quantization_with_int8_tensor(package: Path) -> None:
    def change(manifest: dict[str, Any]) -> None:
        _add_conversion(manifest)
        manifest["inputs"][0]["dtype"] = "int8"
        manifest["inputs"][0]["quantization"] = {
            "scheme": "per_tensor",
            "scale": 0.02,
            "zero_point": 0,
        }

    mutate(package, change)
    assert_code(package, Code.CONVERSION_INVALID)


def test_timestamp_format_is_enforced_by_schema(package: Path) -> None:
    def change(manifest: dict[str, Any]) -> None:
        manifest["provenance"]["created_at"] = "2026-11-17 09:30:00"

    mutate(package, change)
    report = assert_code(package, Code.SCHEMA_INVALID)
    assert any(issue.location == "provenance.created_at" for issue in report.issues)


def test_impossible_timestamp_is_rejected_semantically(package: Path) -> None:
    def change(manifest: dict[str, Any]) -> None:
        manifest["provenance"]["created_at"] = "2026-13-45T25:61:61+08:00"

    mutate(package, change)
    report = assert_code(package, Code.PROVENANCE_INVALID)
    assert report.issues[0].location == "provenance.created_at"
