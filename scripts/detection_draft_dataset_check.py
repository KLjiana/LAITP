"""检测数据集清单 2.0 草案跨字段校验器（草案工具，未激活，不接入生产）。

用法：
    .venv\\Scripts\\python.exe scripts\\detection_draft_dataset_check.py ^
        --manifest <dataset-manifest-2.0-draft.json>
    .venv\\Scripts\\python.exe scripts\\detection_draft_dataset_check.py ^
        --manifest <dataset-manifest-2.0-draft.json> --output <report.json>

本工具对应 docs/detection-contract-draft.md 第 6 节 P2“按数据集清单做跨字段
校验”。**草案工具、未激活、不接入生产**：它只读取
``schemas/detection/dataset-manifest-2.0-draft.schema.json`` 与
``schemas/detection/annotation.schema.json``，不修改 Schema、``backend/``、
``docs/``、界面或其它脚本，不把草案接入任何加载路径，不训练模型，也不写项目
``data/``。所有 ``image`` / ``annotation`` 路径都相对 ``--manifest`` 文件所在
目录解析。

流程：

1. 用清单 2.0 草案 Schema 校验结构；结构错误立即输出错误 JSON 并退出 1；
2. 再逐样本做 Schema 无法表达的跨字段校验（每条规则按样本记 passed/failed）：
   ``image`` 文件存在且可解码；实际宽高与清单 ``width`` / ``height`` 一致；
   文件 SHA-256 与清单 ``sha256`` 一致；``annotation`` 文件存在、JSON 可解析、
   通过 ``annotation.schema.json``；标注框数与清单 ``box_count`` 一致；标注
   ``image`` 与清单 ``image`` 一致；标注 ``width`` / ``height`` 与图片实际
   解码尺寸一致；每个框满足 ``0 <= x``、``0 <= y``、``x + w <= width``、
   ``y + h <= height`` 且 ``class_id < len(classes)``；``capture_batch``
   出现时必须是非空字符串（格式由 Schema 约束，本工具防御性复核）；
3. 同一 ``capture_batch`` 出现在多个划分时只记 warning，不阻断（草案规则
   要求“同一批次不跨划分”，但最终语义由 Q7/P2 决定，本工具不预设结论）；
4. 在标准输出输出 JSON 报告；``--output`` 时同时原子写入该报告文件（UTF-8、
   不带 BOM）。

退出码：0 当且仅当 ``issues`` 为空；存在跨字段 issue、清单无法读取或结构 /
Schema 校验失败时退出 1，并输出带 ``error`` 与 ``issues`` 的错误 JSON。

边界：本工具及测试通过**只**表示给定清单通过了这批草案跨字段规则，
**不表示**检测标注、数据集清单、训练、导出、推理、转换或板端能力已经实现、
可用或验证通过。空标注合法性（Q6）、每图 version 字段（Q7）、坐标是否归一化
（Q5）、``capture_batch`` 去留（Q7）等未决问题不由本工具预设结论；
``box_count = 0`` 结构上允许，出现在多个划分的采集批次只警告。

实现说明：图片解码与 JSON Schema 违例枚举复用 ``scripts/detection_draft_check.py``
的 ``read_image_size`` / ``schema_issues`` 只读函数，未修改该脚本；本脚本的
其余逻辑（清单结构、路径解析、SHA-256、标注绑定、框边界与批次检查）独立实现。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from PIL import __version__ as PILLOW_VERSION  # noqa: E402
from jsonschema import Draft202012Validator  # noqa: E402
from jsonschema.exceptions import SchemaError  # noqa: E402

# 复用现有草案工具的只读辅助函数；不修改 detection_draft_check.py。
from detection_draft_check import read_image_size, schema_issues  # noqa: E402

TOOL_NAME = "detection_draft_dataset_check"
MANIFEST_SCHEMA_REL = "schemas/detection/dataset-manifest-2.0-draft.schema.json"
ANNOTATION_SCHEMA_REL = "schemas/detection/annotation.schema.json"
SPLITS = ("train", "val", "test")
MAX_CAPTURE_BATCH_LENGTH = 128

# 规则标识：输出报告 checks 的键，按样本统计 passed / failed。
RULE_MANIFEST_READABLE = "manifest.readable"
RULE_MANIFEST_SCHEMA = "manifest.schema"
RULE_IMAGE_EXISTS = "image.exists"
RULE_IMAGE_READABLE = "image.readable"
RULE_IMAGE_WIDTH = "image.width"
RULE_IMAGE_HEIGHT = "image.height"
RULE_IMAGE_SHA256 = "image.sha256"
RULE_ANNOTATION_EXISTS = "annotation.exists"
RULE_ANNOTATION_READABLE = "annotation.readable"
RULE_ANNOTATION_SCHEMA = "annotation.schema"
RULE_ANNOTATION_IMAGE = "annotation.image"
RULE_ANNOTATION_WIDTH = "annotation.width"
RULE_ANNOTATION_HEIGHT = "annotation.height"
RULE_BOX_COUNT = "box_count"
RULE_BOX_CLASS_ID = "box.class_id"
RULE_BOX_BOUNDS = "box.bounds"
RULE_CAPTURE_BATCH = "capture_batch"

RULES = (
    RULE_MANIFEST_READABLE,
    RULE_MANIFEST_SCHEMA,
    RULE_IMAGE_EXISTS,
    RULE_IMAGE_READABLE,
    RULE_IMAGE_WIDTH,
    RULE_IMAGE_HEIGHT,
    RULE_IMAGE_SHA256,
    RULE_ANNOTATION_EXISTS,
    RULE_ANNOTATION_READABLE,
    RULE_ANNOTATION_SCHEMA,
    RULE_ANNOTATION_IMAGE,
    RULE_ANNOTATION_WIDTH,
    RULE_ANNOTATION_HEIGHT,
    RULE_BOX_COUNT,
    RULE_BOX_CLASS_ID,
    RULE_BOX_BOUNDS,
    RULE_CAPTURE_BATCH,
)

# issue / warning 代码：供测试与报告消费方稳定匹配。
CODE_MANIFEST_MISSING = "MANIFEST_MISSING"
CODE_MANIFEST_UNREADABLE = "MANIFEST_UNREADABLE"
CODE_MANIFEST_INVALID = "MANIFEST_INVALID"
CODE_MANIFEST_SCHEMA_INVALID = "MANIFEST_SCHEMA_INVALID"
CODE_IMAGE_PATH_INVALID = "IMAGE_PATH_INVALID"
CODE_IMAGE_MISSING = "IMAGE_MISSING"
CODE_IMAGE_UNREADABLE = "IMAGE_UNREADABLE"
CODE_IMAGE_WIDTH_MISMATCH = "IMAGE_WIDTH_MISMATCH"
CODE_IMAGE_HEIGHT_MISMATCH = "IMAGE_HEIGHT_MISMATCH"
CODE_IMAGE_SHA256_MISMATCH = "IMAGE_SHA256_MISMATCH"
CODE_IMAGE_SHA256_UNREADABLE = "IMAGE_SHA256_UNREADABLE"
CODE_ANNOTATION_PATH_INVALID = "ANNOTATION_PATH_INVALID"
CODE_ANNOTATION_MISSING = "ANNOTATION_MISSING"
CODE_ANNOTATION_UNREADABLE = "ANNOTATION_UNREADABLE"
CODE_ANNOTATION_SCHEMA_INVALID = "ANNOTATION_SCHEMA_INVALID"
CODE_ANNOTATION_IMAGE_MISMATCH = "ANNOTATION_IMAGE_MISMATCH"
CODE_ANNOTATION_WIDTH_MISMATCH = "ANNOTATION_WIDTH_MISMATCH"
CODE_ANNOTATION_HEIGHT_MISMATCH = "ANNOTATION_HEIGHT_MISMATCH"
CODE_BOX_COUNT_MISMATCH = "BOX_COUNT_MISMATCH"
CODE_CLASS_ID_OUT_OF_RANGE = "CLASS_ID_OUT_OF_RANGE"
CODE_BOX_OUT_OF_BOUNDS = "BOX_OUT_OF_BOUNDS"
CODE_CAPTURE_BATCH_INVALID = "CAPTURE_BATCH_INVALID"
CODE_CAPTURE_BATCH_CROSS_SPLIT = "CAPTURE_BATCH_CROSS_SPLIT"
CODE_DATASET_EMPTY = "DATASET_EMPTY"

DRAFT_NOTES = (
    "草案工具、未激活、不接入生产：本报告只用于核对检测数据集清单 2.0 草案的"
    "跨字段规则，不代表检测标注、数据集清单、训练、导出、推理、转换或板端能力"
    "已经实现或验证通过。",
    "本工具只读清单、图片与标注文件，不修改数据，不接入 backend/、界面或任何"
    "生产加载、训练、校验路径；现有分类契约 1.0 与校验器默认策略均未改变。",
    "检测标注、数据集清单 2.0 与检测结果格式仍是 schemas/detection/ 下的草案；"
    "本工具通过不表示检测数据集能力已经可用。",
    "未决问题不由本工具预设结论：空标注（Q6）、每图 version 字段与 capture_batch"
    " 去留（Q7）、坐标是否归一化（Q5）等仍待 P2 评审；box_count = 0 结构上允许，"
    "同一 capture_batch 出现在多个划分只警告、不阻断。",
    "checks 中每条规则的 passed/failed 按样本计数；依赖文件缺失、不可解析或字段"
    "类型非法而未评估的规则保持 0/0，避免用级联错误掩盖首个根因。",
    "输出 JSON 为不带 BOM 的 UTF-8；退出码 0 当且仅当 issues 为空，warning 不"
    "影响退出码。",
)


class DatasetCheckError(Exception):
    """工具无法完成检查（清单缺失、Schema 不可用、报告不可写等）。"""

    def __init__(
        self,
        code: str,
        message: str,
        stage: str = "input",
        location: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.stage = stage
        self.location = location


@dataclass(frozen=True)
class SampleRef:
    """清单中的一个样本及其位置，``label`` 用于 issues/warnings 定位。"""

    split: str
    index: int
    sample: Mapping[str, Any]

    @property
    def label(self) -> str:
        return f"{self.split}[{self.index}]"

    @property
    def location(self) -> str:
        return f"$.splits.{self.split}.samples[{self.index}]"


# --------------------------------------------------------------------------- #
# 基础 I/O
# --------------------------------------------------------------------------- #


def _now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _emit_json(payload: Any) -> None:
    """以 UTF-8 写标准输出（Windows 控制台代码页可能是 GBK）。"""
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write(text.encode("utf-8"))
        buffer.flush()
    else:  # pragma: no cover - 只有标准输出被替换成文本流时使用
        sys.stdout.write(text)


def _write_json_atomic(path: Path, payload: Any) -> None:
    """先写临时文件再整体替换，避免留下半写 JSON（UTF-8，不带 BOM）。"""
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    temp_path = path.with_name(path.name + ".tmp")
    try:
        temp_path.write_text(text, encoding="utf-8")
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_resolve(path: Path) -> Path:
    """尽量解析为绝对路径；极端路径解析失败时退回 absolute()。"""
    try:
        return Path(path).expanduser().resolve()
    except OSError:  # pragma: no cover - 极端路径解析失败
        return Path(path).expanduser().absolute()


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _empty_checks() -> dict[str, dict[str, int]]:
    return {rule: {"passed": 0, "failed": 0} for rule in RULES}


def _base_report(manifest_text: str) -> dict[str, Any]:
    """报告骨架：成功与错误路径都返回相同字段，便于消费方统一处理。"""
    return {
        "ok": False,
        "tool": TOOL_NAME,
        "draft": True,
        "activated": False,
        "notes": list(DRAFT_NOTES),
        "manifest": manifest_text,
        "manifest_sha256": None,
        "schemas": {
            "manifest": MANIFEST_SCHEMA_REL,
            "annotation": ANNOTATION_SCHEMA_REL,
        },
        "samples": 0,
        "splits": {split: 0 for split in SPLITS},
        "checks": _empty_checks(),
        "issues": [],
        "warnings": [],
        "generated_at": _now_text(),
        "python_version": sys.version.split()[0],
        "pillow_version": PILLOW_VERSION,
    }


# --------------------------------------------------------------------------- #
# Schema / 清单加载与路径解析
# --------------------------------------------------------------------------- #


def load_schema(rel_path: str, code_prefix: str) -> Draft202012Validator:
    """读取草案 Schema 并确认是合法的 draft 2020-12 Schema。"""
    path = ROOT / rel_path
    if not path.is_file():
        raise DatasetCheckError(
            f"{code_prefix}_MISSING",
            f"草案 Schema 不存在：{rel_path}",
            stage="schema",
            location=rel_path,
        )
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DatasetCheckError(
            f"{code_prefix}_UNREADABLE",
            f"草案 Schema 无法读取或不是合法 JSON：{rel_path}（{error}）",
            stage="schema",
            location=rel_path,
        ) from error
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise DatasetCheckError(
            f"{code_prefix}_INVALID",
            f"草案 Schema 不是合法的 draft 2020-12 Schema：{rel_path}"
            f"（{error.message}）",
            stage="schema",
            location=rel_path,
        ) from error
    return Draft202012Validator(schema)


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    """读取清单 JSON；容忍 BOM，返回顶层对象。"""
    if not manifest_path.is_file():
        raise DatasetCheckError(
            CODE_MANIFEST_MISSING,
            f"清单文件不存在或不是普通文件：{manifest_path}",
            stage="input",
            location=str(manifest_path),
        )
    try:
        raw = manifest_path.read_bytes()
    except OSError as error:
        raise DatasetCheckError(
            CODE_MANIFEST_UNREADABLE,
            f"清单文件无法读取：{error}",
            stage="input",
            location=str(manifest_path),
        ) from error
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DatasetCheckError(
            CODE_MANIFEST_UNREADABLE,
            f"清单不是可解析的 UTF-8 JSON：{error}",
            stage="input",
            location=str(manifest_path),
        ) from error
    if not isinstance(data, dict):
        raise DatasetCheckError(
            CODE_MANIFEST_INVALID,
            "清单顶层必须是 JSON 对象",
            stage="schema",
            location=str(manifest_path),
        )
    return data


def resolve_member_path(
    manifest_dir: Path, relative: Any
) -> tuple[Path | None, str | None]:
    """把清单中的相对路径解析到 ``manifest`` 所在目录，并拒绝越界路径。"""
    if not isinstance(relative, str) or not relative:
        return None, "路径必须是非空字符串"
    candidate = Path(relative)
    if candidate.is_absolute() or candidate.drive or relative.startswith("/"):
        return None, f"路径必须是相对 --manifest 所在目录的相对路径：{relative!r}"
    if "\\" in relative:
        return None, f"路径不得包含反斜杠：{relative!r}"
    try:
        resolved = (manifest_dir / relative).resolve()
    except OSError as error:
        return None, f"路径无法解析：{error}"
    if not resolved.is_relative_to(manifest_dir):
        return None, f"路径解析后超出 --manifest 所在目录：{relative!r}"
    return resolved, None


def iter_samples(manifest: Mapping[str, Any]) -> Iterable[SampleRef]:
    for split in SPLITS:
        for index, sample in enumerate(manifest["splits"][split]["samples"]):
            yield SampleRef(split=split, index=index, sample=sample)


# --------------------------------------------------------------------------- #
# 逐样本跨字段检查
# --------------------------------------------------------------------------- #


class DatasetChecker:
    """对已通过结构校验的清单逐样本执行跨字段规则。"""

    def __init__(
        self,
        manifest: Mapping[str, Any],
        manifest_dir: Path,
        annotation_validator: Draft202012Validator,
    ) -> None:
        self.manifest = manifest
        self.manifest_dir = manifest_dir
        self.annotation_validator = annotation_validator
        self.class_count = len(manifest["classes"])
        self.checks = _empty_checks()
        self.issues: list[dict[str, Any]] = []
        self.warnings: list[dict[str, Any]] = []
        self.sample_count = 0
        self.split_counts = {split: 0 for split in SPLITS}
        self._batches: dict[str, list[tuple[str, str]]] = defaultdict(list)

    # -- 记录辅助 ---------------------------------------------------------- #

    def _record(self, rule: str, ok: bool) -> None:
        self.checks[rule]["passed" if ok else "failed"] += 1

    def _issue(
        self,
        code: str,
        stage: str,
        ref: SampleRef | None,
        location: str,
        message: str,
    ) -> None:
        self.issues.append(
            {
                "code": code,
                "stage": stage,
                "sample": ref.label if ref is not None else None,
                "location": location,
                "message": message,
            }
        )

    # -- 主流程 ------------------------------------------------------------ #

    def run(self) -> None:
        for ref in iter_samples(self.manifest):
            self.sample_count += 1
            self.split_counts[ref.split] += 1
            self._check_sample(ref)
        self._check_capture_batch_splits()
        if self.sample_count == 0:
            self.warnings.append(
                {
                    "code": CODE_DATASET_EMPTY,
                    "message": (
                        "清单没有任何样本；草案 Schema 允许空划分，但每个划分的"
                        "最小样本数/类别覆盖仍待 P2 决定，本工具不阻断。"
                    ),
                    "samples": [],
                }
            )

    def _check_sample(self, ref: SampleRef) -> None:
        sample = ref.sample
        base = ref.location
        actual_size: tuple[int, int] | None = None

        image_path, image_error = resolve_member_path(
            self.manifest_dir, sample.get("image")
        )
        if image_error is not None:
            self._record(RULE_IMAGE_EXISTS, False)
            self._issue(
                CODE_IMAGE_PATH_INVALID, "image", ref, f"{base}.image", image_error
            )
        elif not image_path.is_file():
            self._record(RULE_IMAGE_EXISTS, False)
            self._issue(
                CODE_IMAGE_MISSING,
                "image",
                ref,
                f"{base}.image",
                f"图片文件不存在或不是普通文件：{sample['image']}",
            )
        else:
            self._record(RULE_IMAGE_EXISTS, True)
            width, height, read_error = read_image_size(image_path)
            if read_error is not None:
                self._record(RULE_IMAGE_READABLE, False)
                self._issue(
                    CODE_IMAGE_UNREADABLE, "image", ref, f"{base}.image", read_error
                )
            else:
                self._record(RULE_IMAGE_READABLE, True)
                actual_size = (width, height)
                self._check_image_size(ref, sample, width, height)
            self._check_image_sha256(ref, sample, image_path)

        annotation = self._load_annotation(ref, base)
        if annotation is not None:
            self._check_annotation_fields(ref, annotation, sample, actual_size)
        self._check_capture_batch(ref, sample)

    # -- 图片 -------------------------------------------------------------- #

    def _check_image_size(
        self, ref: SampleRef, sample: Mapping[str, Any], width: int, height: int
    ) -> None:
        base = ref.location
        if width != sample["width"]:
            self._record(RULE_IMAGE_WIDTH, False)
            self._issue(
                CODE_IMAGE_WIDTH_MISMATCH,
                "image",
                ref,
                f"{base}.width",
                f"清单 width={sample['width']} 与图片实际解码宽度 {width} 不一致",
            )
        else:
            self._record(RULE_IMAGE_WIDTH, True)
        if height != sample["height"]:
            self._record(RULE_IMAGE_HEIGHT, False)
            self._issue(
                CODE_IMAGE_HEIGHT_MISMATCH,
                "image",
                ref,
                f"{base}.height",
                f"清单 height={sample['height']} 与图片实际解码高度 {height} 不一致",
            )
        else:
            self._record(RULE_IMAGE_HEIGHT, True)

    def _check_image_sha256(
        self, ref: SampleRef, sample: Mapping[str, Any], image_path: Path
    ) -> None:
        try:
            actual = _sha256_file(image_path)
        except OSError as error:
            self._record(RULE_IMAGE_SHA256, False)
            self._issue(
                CODE_IMAGE_SHA256_UNREADABLE,
                "image",
                ref,
                f"{ref.location}.sha256",
                f"无法计算图片 SHA-256：{error}",
            )
            return
        expected = sample["sha256"]
        if actual != expected:
            self._record(RULE_IMAGE_SHA256, False)
            self._issue(
                CODE_IMAGE_SHA256_MISMATCH,
                "image",
                ref,
                f"{ref.location}.sha256",
                f"图片实际 SHA-256={actual} 与清单 sha256={expected} 不一致",
            )
        else:
            self._record(RULE_IMAGE_SHA256, True)

    # -- 标注读取与结构 ---------------------------------------------------- #

    def _load_annotation(self, ref: SampleRef, base: str) -> dict[str, Any] | None:
        sample = ref.sample
        annotation_path, path_error = resolve_member_path(
            self.manifest_dir, sample.get("annotation")
        )
        if path_error is not None:
            self._record(RULE_ANNOTATION_EXISTS, False)
            self._issue(
                CODE_ANNOTATION_PATH_INVALID,
                "annotation",
                ref,
                f"{base}.annotation",
                path_error,
            )
            return None
        if not annotation_path.is_file():
            self._record(RULE_ANNOTATION_EXISTS, False)
            self._issue(
                CODE_ANNOTATION_MISSING,
                "annotation",
                ref,
                f"{base}.annotation",
                f"标注文件不存在或不是普通文件：{sample['annotation']}",
            )
            return None
        self._record(RULE_ANNOTATION_EXISTS, True)

        try:
            raw = annotation_path.read_bytes()
        except OSError as error:
            self._record(RULE_ANNOTATION_READABLE, False)
            self._issue(
                CODE_ANNOTATION_UNREADABLE,
                "annotation",
                ref,
                f"{base}.annotation",
                f"标注文件无法读取：{error}",
            )
            return None
        try:
            annotation = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            self._record(RULE_ANNOTATION_READABLE, False)
            self._issue(
                CODE_ANNOTATION_UNREADABLE,
                "annotation",
                ref,
                f"{base}.annotation",
                f"标注不是可解析的 UTF-8 JSON：{error}",
            )
            return None
        self._record(RULE_ANNOTATION_READABLE, True)

        if not isinstance(annotation, dict):
            self._record(RULE_ANNOTATION_SCHEMA, False)
            self._issue(
                CODE_ANNOTATION_SCHEMA_INVALID,
                "annotation",
                ref,
                f"{base}.annotation",
                "标注顶层必须是 JSON 对象",
            )
            return None

        errors = schema_issues(self.annotation_validator, annotation)
        if errors:
            self._record(RULE_ANNOTATION_SCHEMA, False)
            for error in errors:
                pointer = error["path"]
                suffix = pointer[1:] if pointer.startswith("$") else pointer
                self._issue(
                    CODE_ANNOTATION_SCHEMA_INVALID,
                    "annotation",
                    ref,
                    f"annotation{suffix}",
                    f"{pointer}: {error['message']}",
                )
        else:
            self._record(RULE_ANNOTATION_SCHEMA, True)
        return annotation

    # -- 标注跨字段 -------------------------------------------------------- #

    def _check_annotation_fields(
        self,
        ref: SampleRef,
        annotation: Mapping[str, Any],
        sample: Mapping[str, Any],
        actual_size: tuple[int, int] | None,
    ) -> None:
        base = ref.location
        self._check_annotation_image(ref, annotation, sample, base)
        reference = self._annotation_reference_size(sample, actual_size)
        self._check_annotation_size(ref, annotation, reference, base)
        boxes = annotation.get("boxes")
        if isinstance(boxes, list):
            self._check_box_count(ref, sample, boxes, base)
            bounds = self._bounds_size(annotation, sample, actual_size)
            self._check_boxes(ref, boxes, bounds, base)

    def _check_annotation_image(
        self,
        ref: SampleRef,
        annotation: Mapping[str, Any],
        sample: Mapping[str, Any],
        base: str,
    ) -> None:
        annotation_image = annotation.get("image")
        if not isinstance(annotation_image, str):
            return  # 缺字段/类型错误已由 annotation.schema 报告，不重复计数
        if annotation_image != sample["image"]:
            self._record(RULE_ANNOTATION_IMAGE, False)
            self._issue(
                CODE_ANNOTATION_IMAGE_MISMATCH,
                "annotation",
                ref,
                f"{base}.annotation.image",
                f"标注 image={annotation_image!r} 与清单 image={sample['image']!r}"
                " 不一致",
            )
        else:
            self._record(RULE_ANNOTATION_IMAGE, True)

    def _annotation_reference_size(
        self,
        sample: Mapping[str, Any],
        actual_size: tuple[int, int] | None,
    ) -> tuple[int, int, str]:
        """标注尺寸的对照基准：优先图片实际解码尺寸，退回清单声明尺寸。"""
        if actual_size is not None:
            return actual_size[0], actual_size[1], "图片实际解码"
        return sample["width"], sample["height"], "清单声明"

    def _check_annotation_size(
        self,
        ref: SampleRef,
        annotation: Mapping[str, Any],
        reference: tuple[int, int, str],
        base: str,
    ) -> None:
        expected_width, expected_height, source = reference
        annotation_width = annotation.get("width")
        annotation_height = annotation.get("height")
        if _is_int(annotation_width):
            if annotation_width != expected_width:
                self._record(RULE_ANNOTATION_WIDTH, False)
                self._issue(
                    CODE_ANNOTATION_WIDTH_MISMATCH,
                    "annotation",
                    ref,
                    f"{base}.annotation.width",
                    f"标注 width={annotation_width} 与{source}宽度"
                    f" {expected_width} 不一致",
                )
            else:
                self._record(RULE_ANNOTATION_WIDTH, True)
        if _is_int(annotation_height):
            if annotation_height != expected_height:
                self._record(RULE_ANNOTATION_HEIGHT, False)
                self._issue(
                    CODE_ANNOTATION_HEIGHT_MISMATCH,
                    "annotation",
                    ref,
                    f"{base}.annotation.height",
                    f"标注 height={annotation_height} 与{source}高度"
                    f" {expected_height} 不一致",
                )
            else:
                self._record(RULE_ANNOTATION_HEIGHT, True)

    def _bounds_size(
        self,
        annotation: Mapping[str, Any],
        sample: Mapping[str, Any],
        actual_size: tuple[int, int] | None,
    ) -> tuple[int, int]:
        """框边界检查使用的宽高：实际解码尺寸 > 标注声明 > 清单声明。"""
        if actual_size is not None:
            return actual_size
        annotation_width = annotation.get("width")
        annotation_height = annotation.get("height")
        if _is_int(annotation_width) and _is_int(annotation_height):
            return annotation_width, annotation_height
        return sample["width"], sample["height"]

    def _check_box_count(
        self,
        ref: SampleRef,
        sample: Mapping[str, Any],
        boxes: Sequence[Any],
        base: str,
    ) -> None:
        expected = sample.get("box_count")
        if not _is_int(expected):
            return  # annotation.schema 只约束标注；清单 box_count 由清单 Schema 约束
        actual = len(boxes)
        if actual != expected:
            self._record(RULE_BOX_COUNT, False)
            self._issue(
                CODE_BOX_COUNT_MISMATCH,
                "sample",
                ref,
                f"{base}.box_count",
                f"清单 box_count={expected} 与标注 boxes 数量 {actual} 不一致",
            )
        else:
            self._record(RULE_BOX_COUNT, True)

    def _check_boxes(
        self,
        ref: SampleRef,
        boxes: Sequence[Any],
        bounds: tuple[int, int],
        base: str,
    ) -> None:
        if not boxes:
            # 空 boxes 对“所有框都在界内/类别有效”是空真；box_count 另行核对。
            self._record(RULE_BOX_CLASS_ID, True)
            self._record(RULE_BOX_BOUNDS, True)
            return

        bound_width, bound_height = bounds
        class_evaluated = False
        bounds_evaluated = False
        class_failed = False
        bounds_failed = False
        for index, box in enumerate(boxes):
            if not isinstance(box, dict):
                continue
            location = f"{base}.annotation.boxes[{index}]"
            class_id = box.get("class_id")
            if _is_int(class_id):
                class_evaluated = True
                if not 0 <= class_id < self.class_count:
                    class_failed = True
                    self._issue(
                        CODE_CLASS_ID_OUT_OF_RANGE,
                        "annotation",
                        ref,
                        f"{location}.class_id",
                        f"class_id={class_id} 不在类别表"
                        f" 0～{self.class_count - 1} 范围内",
                    )
            x, y, w, h = (box.get(key) for key in ("x", "y", "w", "h"))
            if all(_is_int(value) for value in (x, y, w, h)):
                bounds_evaluated = True
                if x < 0 or y < 0 or x + w > bound_width or y + h > bound_height:
                    bounds_failed = True
                    self._issue(
                        CODE_BOX_OUT_OF_BOUNDS,
                        "annotation",
                        ref,
                        location,
                        f"框越界：x={x}, y={y}, w={w}, h={h}，"
                        f"边界 0 <= x/y、x + w <= {bound_width}、"
                        f"y + h <= {bound_height}",
                    )
        # 同一规则按样本只记一次 passed/failed，而不是按框重复计数。
        if class_evaluated:
            self._record(RULE_BOX_CLASS_ID, not class_failed)
        if bounds_evaluated:
            self._record(RULE_BOX_BOUNDS, not bounds_failed)

    # -- 采集批次 ---------------------------------------------------------- #

    def _check_capture_batch(self, ref: SampleRef, sample: Mapping[str, Any]) -> None:
        batch = sample.get("capture_batch")
        if batch is None:
            return  # 可选字段；未提供时无法做批次追溯，本规则不计数
        if (
            not isinstance(batch, str)
            or not batch
            or len(batch) > MAX_CAPTURE_BATCH_LENGTH
        ):
            self._record(RULE_CAPTURE_BATCH, False)
            self._issue(
                CODE_CAPTURE_BATCH_INVALID,
                "sample",
                ref,
                f"{ref.location}.capture_batch",
                "capture_batch 必须是非空字符串且长度不超过"
                f" {MAX_CAPTURE_BATCH_LENGTH}（该格式通常已由清单 Schema 拒绝）",
            )
            return
        self._record(RULE_CAPTURE_BATCH, True)
        self._batches[batch].append((ref.split, ref.label))

    def _check_capture_batch_splits(self) -> None:
        for batch in sorted(self._batches):
            usages = self._batches[batch]
            splits = sorted({split for split, _ in usages})
            if len(splits) <= 1:
                continue
            self.warnings.append(
                {
                    "code": CODE_CAPTURE_BATCH_CROSS_SPLIT,
                    "message": (
                        f"同一 capture_batch={batch!r} 出现在多个划分"
                        f"（{', '.join(splits)}）；草案要求同一批次不跨划分，"
                        "但最终规则待 Q7/P2 决定，本草案工具只警告、不阻断。"
                    ),
                    "samples": [label for _, label in usages],
                }
            )


# --------------------------------------------------------------------------- #
# 报告组装与主流程
# --------------------------------------------------------------------------- #


def run_check(manifest_path: Path) -> dict[str, Any]:
    """执行结构 + 跨字段校验并返回 JSON 报告（不写文件、不打印）。"""
    manifest_path = Path(manifest_path).expanduser()
    resolved = _safe_resolve(manifest_path)
    report = _base_report(str(resolved))

    manifest = load_manifest(resolved)
    try:
        report["manifest_sha256"] = _sha256_file(resolved)
    except OSError:  # pragma: no cover - 刚成功读取后极少失败
        report["manifest_sha256"] = None

    manifest_validator = load_schema(MANIFEST_SCHEMA_REL, "MANIFEST_SCHEMA")
    annotation_validator = load_schema(ANNOTATION_SCHEMA_REL, "ANNOTATION_SCHEMA")

    report["checks"][RULE_MANIFEST_READABLE]["passed"] = 1
    schema_errors = schema_issues(manifest_validator, manifest)
    if schema_errors:
        report["checks"][RULE_MANIFEST_SCHEMA]["failed"] = 1
        for error in schema_errors:
            report["issues"].append(
                {
                    "code": CODE_MANIFEST_SCHEMA_INVALID,
                    "stage": "schema",
                    "sample": None,
                    "location": error["path"],
                    "message": error["message"],
                }
            )
        report["error"] = {
            "code": CODE_MANIFEST_SCHEMA_INVALID,
            "stage": "schema",
            "message": f"清单未通过草案 Schema 结构校验：{len(schema_errors)} 处错误",
        }
        return report
    report["checks"][RULE_MANIFEST_SCHEMA]["passed"] = 1

    checker = DatasetChecker(manifest, resolved.parent, annotation_validator)
    checker.checks[RULE_MANIFEST_READABLE]["passed"] = 1
    checker.checks[RULE_MANIFEST_SCHEMA]["passed"] = 1
    checker.run()
    report["checks"] = checker.checks
    report["issues"] = checker.issues
    report["warnings"] = checker.warnings
    report["samples"] = checker.sample_count
    report["splits"] = checker.split_counts
    report["ok"] = not checker.issues
    return report


def _error_report(manifest_path: Path, error: DatasetCheckError) -> dict[str, Any]:
    """工具无法完成检查时的错误 JSON（字段与正常报告一致）。"""
    resolved = _safe_resolve(manifest_path)
    report = _base_report(str(resolved))
    if error.code in (CODE_MANIFEST_MISSING, CODE_MANIFEST_UNREADABLE):
        report["checks"][RULE_MANIFEST_READABLE]["failed"] = 1
    elif error.code == CODE_MANIFEST_INVALID:
        report["checks"][RULE_MANIFEST_READABLE]["passed"] = 1
        report["checks"][RULE_MANIFEST_SCHEMA]["failed"] = 1
    report["issues"] = [
        {
            "code": error.code,
            "stage": error.stage,
            "sample": None,
            "location": error.location or str(resolved),
            "message": error.message,
        }
    ]
    report["error"] = {
        "code": error.code,
        "stage": error.stage,
        "message": error.message,
    }
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python scripts/detection_draft_dataset_check.py",
        description=(
            "检测数据集清单 2.0 草案跨字段校验器（草案工具，未激活，不接入生产）："
            "先按草案 Schema 校验清单结构，再逐样本核对图片/标注存在性、摘要、"
            "尺寸、框数、类别上界、框边界与采集批次。"
        ),
    )
    parser.add_argument(
        "--manifest",
        required=True,
        metavar="PATH",
        help="检测数据集清单 2.0 草案 JSON；image/annotation 路径相对该文件所在目录",
    )
    parser.add_argument(
        "--output",
        default=None,
        metavar="PATH",
        help="可选：同时把 JSON 报告原子写入该文件（UTF-8，不带 BOM）",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    parser = _build_parser()
    args = parser.parse_args(argv)
    manifest_path = Path(args.manifest)

    try:
        report = run_check(manifest_path)
    except DatasetCheckError as error:
        _emit_json(_error_report(manifest_path, error))
        return 1
    except Exception as error:  # 不把异常堆栈当正常输出；稳定 JSON + 退出码 1
        wrapped = DatasetCheckError(
            "DATASET_CHECK_FAILED",
            f"校验过程异常（{type(error).__name__}）：{error}",
            stage="tool",
        )
        _emit_json(_error_report(manifest_path, wrapped))
        return 1

    if args.output:
        try:
            _write_json_atomic(Path(args.output), report)
        except OSError as error:
            wrapped = DatasetCheckError(
                "OUTPUT_WRITE_FAILED",
                f"无法写入报告文件 {args.output}：{error}",
                stage="output",
                location=str(args.output),
            )
            _emit_json(_error_report(manifest_path, wrapped))
            return 1

    _emit_json(report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
