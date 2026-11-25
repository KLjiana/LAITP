"""检测草案“合成图片 + 合成标注”边界验证工具（草案，未激活）。

用法：
    .venv\\Scripts\\python.exe scripts\\detection_draft_check.py
    .venv\\Scripts\\python.exe scripts\\detection_draft_check.py --output <目录> [--images 12]

本工具对应 docs/detection-contract-draft.md 第 6 节 P2“用合成图片与合成标注
验证字段设计与边界规则”。**本工具是草案验证工具，检测未实现/未激活**：它只读取
``schemas/detection/annotation.schema.json``，不修改 Schema、``backend/``、
``docs/``、界面或其它脚本，不把草案 Schema 接入加载路径，不训练模型，不读写项目
``data/``。输出目录默认为
``%TEMP%/laitp-detection-draft``；显式 ``--output`` 时写入指定目录，但拒绝写入
仓库受保护目录（``data/``、``schemas/``、``backend/``、``docs/``、``tests/``、
``scripts/``、``desktop/``、``.git/``）。

流程：

1. 生成 N 张（默认 12）128x96 合成 PNG，两个类别 ``circle`` / ``square``，
   覆盖单目标、多目标和贴边框（``x + w == width`` 或 ``y + h == height`` 的
   合法边界）；
2. 为每张图片写一个符合草案的标注 JSON（``image`` 相对路径、``width`` /
   ``height``、``boxes`` 含 ``class_id`` / ``x`` / ``y`` / ``w`` / ``h``）；
3. 用 ``annotation.schema.json`` 做结构校验，再用代码检查 Schema 无法表达、
   或不应只依赖 Schema 的规则：``x + w <= width``、``y + h <= height``、
   ``class_id`` 在类别范围内、框面积 > 0、Pillow 读取的图片实际尺寸与标注
   ``width`` / ``height`` 一致；
4. 生成一批故意无效样例（越界、负值、零尺寸、类别越界、尺寸不一致），
   逐个验证都被 Schema 或补充检查按预期拒绝；
5. 在标准输出和 ``<output>/detection-draft-summary.json`` 输出 JSON 摘要。
   退出码 0 当且仅当所有有效样例通过且所有无效样例按预期被拒绝；异常退出 1。

边界：本工具及其测试通过**只**表示合成样例符合草案字段与边界规则，
**不表示**检测标注、数据集清单、训练、导出、推理、转换或板端能力已经实现、
可用或验证通过。合成图片与标注是临时验证材料，不进入正式课堂数据、不训练、
不导出产物，也不作为任何可用检测数据或模型产物。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]

# 第三方依赖：Pillow（画图/解码）与 jsonschema（草案 Schema 结构校验）。
from PIL import Image, ImageDraw, __version__ as PILLOW_VERSION  # noqa: E402
from jsonschema import Draft202012Validator  # noqa: E402
from jsonschema.exceptions import SchemaError  # noqa: E402

TOOL_NAME = "detection_draft_check"
DEFAULT_IMAGE_COUNT = 12
MAX_IMAGE_COUNT = 120
MIN_COVERAGE_IMAGES = 4
IMAGE_WIDTH = 128
IMAGE_HEIGHT = 96
CLASSES = ("circle", "square")
CLASS_FILL = {0: (214, 72, 72), 1: (62, 104, 206)}
CLASS_OUTLINE = {0: (120, 30, 30), 1: (24, 48, 120)}
DEFAULT_OUTPUT_NAME = "laitp-detection-draft"
DEFAULT_OUTPUT = Path(tempfile.gettempdir()) / DEFAULT_OUTPUT_NAME
SUMMARY_FILE_NAME = "detection-draft-summary.json"
SCHEMA_REL_PATH = "schemas/detection/annotation.schema.json"
PROTECTED_OUTPUT_DIRS = (
    "data",
    "schemas",
    "backend",
    "docs",
    "tests",
    "scripts",
    "desktop",
    ".git",
)

# 规则标识：Schema 能表达的结构规则统一记为 "schema"，其余为代码补充检查。
RULE_SCHEMA = "schema"
RULE_ANNOTATION_READABLE = "annotation.readable"
RULE_IMAGE_READABLE = "image.readable"
RULE_IMAGE_PATH = "annotation.image == image"
RULE_WIDTH_MATCH = "image.width == annotation.width"
RULE_HEIGHT_MATCH = "image.height == annotation.height"
RULE_CLASS_RANGE = "class_id < class_count"
RULE_AREA = "box.area > 0"
RULE_X_LIMIT = "x + w <= width"
RULE_Y_LIMIT = "y + h <= height"

DRAFT_NOTES = (
    "草案验证工具，检测未实现/未激活：本摘要只用于验证草案字段与边界规则的合成样例，"
    "不代表检测标注、训练、导出、推理、转换或板端能力已经实现或验证通过。",
    "合成图片与标注是临时验证材料，不进入正式课堂数据、不训练模型、不导出产物，"
    "也不接入 backend/ 或界面的加载、校验与训练路径。",
    "检测标注仍只是 schemas/detection/ 下的草案，当前分类契约 1.0、校验器默认策略"
    "与现有生产路径均未改变。",
    "boundary_violations 只统计 JSON Schema 无法表达、由本工具代码补充检查捕获的"
    "违例条数：故意无效样例中的预期违例计入，有效样例必须为 0。",
    "草案未决问题（空标注 Q6、每图 version 字段 Q7、坐标归一化 Q5 等）不由本工具"
    "预设结论：合成标注均至少一个框，且未写入可选 version 字段。",
)


class DraftCheckError(Exception):
    """工具无法完成检查（Schema 缺失/不可用、输出目录非法等）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SyntheticBox:
    """一个合成标注框，坐标单位是原图像素。"""

    class_id: int
    x: int
    y: int
    w: int
    h: int

    def to_json(self) -> dict[str, int]:
        return {
            "class_id": self.class_id,
            "x": self.x,
            "y": self.y,
            "w": self.w,
            "h": self.h,
        }


@dataclass(frozen=True)
class GeneratedSample:
    """一张合成图片及其标注文件记录。"""

    index: int
    image_rel: str
    annotation_rel: str
    annotation: dict[str, Any]

    @property
    def edge_touch(self) -> bool:
        """标注中是否有框贴住右边界或下边界（合法边界，用于验证 ``<=``）。"""
        return any(
            box["x"] + box["w"] == IMAGE_WIDTH
            or box["y"] + box["h"] == IMAGE_HEIGHT
            for box in self.annotation["boxes"]
        )


@dataclass(frozen=True)
class InvalidCase:
    """一个故意无效的标注样例及其预期拒绝渠道。"""

    name: str
    kind: str
    expect_channel: str  # "schema" 或 "semantic"
    expected_rules: tuple[str, ...]
    annotation: dict[str, Any]

    @property
    def annotation_rel(self) -> str:
        return f"invalid/annotations/{self.name}.json"


# --------------------------------------------------------------------------- #
# 基础 I/O
# --------------------------------------------------------------------------- #


def _now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _emit_json(payload: Any) -> None:
    """以 UTF-8 JSON 写标准输出（Windows 控制台代码页可能是 GBK）。"""
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write(text.encode("utf-8"))
        buffer.flush()
    else:  # pragma: no cover - 只有标准输出被替换成文本流时使用
        sys.stdout.write(text)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: Any) -> None:
    """先写临时文件再整体替换，避免留下半写 JSON（草案约定）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    temp_path = path.with_name(path.name + ".tmp")
    try:
        temp_path.write_text(text, encoding="utf-8")
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _json_pointer(parts: Iterable[Any]) -> str:
    """把 jsonschema 的绝对路径转成便于阅读的 ``$.boxes[0].w`` 形式。"""
    text = "$"
    for part in parts:
        if isinstance(part, int):
            text += f"[{part}]"
        else:
            text += f".{part}"
    return text


# --------------------------------------------------------------------------- #
# 输出目录与 Schema
# --------------------------------------------------------------------------- #


def resolve_output(raw: str | Path | None) -> Path:
    """解析输出目录；默认系统临时目录，并拒绝写入仓库受保护目录。"""
    if raw is None:
        output = DEFAULT_OUTPUT
    else:
        output = Path(raw).expanduser()
    try:
        resolved = output.resolve()
    except OSError:  # pragma: no cover - 极端路径解析失败
        resolved = output.absolute()

    if resolved == ROOT:
        raise DraftCheckError(
            "OUTPUT_PATH_FORBIDDEN",
            f"输出目录不能是仓库根目录，请使用临时目录或 artifacts/ 子目录：{resolved}",
        )
    for name in PROTECTED_OUTPUT_DIRS:
        protected = (ROOT / name).resolve()
        if resolved == protected or protected in resolved.parents:
            raise DraftCheckError(
                "OUTPUT_PATH_FORBIDDEN",
                f"输出目录不能位于仓库受保护目录 {name}/ 下：{resolved}",
            )
    if resolved.exists() and not resolved.is_dir():
        raise DraftCheckError(
            "OUTPUT_PATH_INVALID",
            f"输出路径已存在且不是目录：{resolved}",
        )
    return resolved


def load_schema_validator(schema_path: Path) -> Draft202012Validator:
    """只读取草案标注 Schema，并确认它是可用的 draft 2020-12 Schema。"""
    if not schema_path.is_file():
        raise DraftCheckError(
            "DETECTION_SCHEMA_MISSING",
            f"草案标注 Schema 不存在：{SCHEMA_REL_PATH}",
        )
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DraftCheckError(
            "DETECTION_SCHEMA_UNREADABLE",
            f"草案标注 Schema 无法读取或不是合法 JSON：{error}",
        ) from error
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise DraftCheckError(
            "DETECTION_SCHEMA_INVALID",
            f"草案标注 Schema 不是合法的 draft 2020-12 Schema：{error.message}",
        ) from error
    return Draft202012Validator(schema)


# --------------------------------------------------------------------------- #
# Schema 与补充规则检查
# --------------------------------------------------------------------------- #


def schema_issues(
    validator: Draft202012Validator, annotation: Any
) -> list[dict[str, Any]]:
    """返回 Schema 结构违例；规则统一记为 ``schema``。"""
    errors = sorted(
        validator.iter_errors(annotation),
        key=lambda error: tuple(
            (isinstance(part, str), str(part)) for part in error.absolute_path
        ),
    )
    return [
        {
            "rule": RULE_SCHEMA,
            "path": _json_pointer(error.absolute_path),
            "message": error.message,
        }
        for error in errors
    ]


def read_image_size(path: Path) -> tuple[int, int, str | None]:
    """用 Pillow 打开并完整解码图片，返回实际宽高；失败时返回错误说明。"""
    try:
        with Image.open(path) as image:
            image.load()
            return image.width, image.height, None
    except Exception as error:  # Pillow 的异常类型较多，统一转成可读说明
        return 0, 0, f"无法读取或解码图片：{type(error).__name__}: {error}"


def semantic_violations(
    annotation: Mapping[str, Any],
    image_path: Path | None,
    class_count: int,
) -> list[dict[str, Any]]:
    """检查 JSON Schema 无法表达的跨字段/尺寸规则，返回违例明细。

    调用方应优先通过 ``schema_issues``；本函数对结构做防御性判断，
    只报告字段存在且为整数后的语义问题，避免异常输出。
    """
    violations: list[dict[str, Any]] = []
    width = annotation.get("width")
    height = annotation.get("height")

    if image_path is None:
        violations.append(
            {
                "rule": RULE_IMAGE_READABLE,
                "message": "没有提供图片路径，无法核对图片实际尺寸",
            }
        )
    else:
        actual_width, actual_height, error = read_image_size(image_path)
        if error is not None:
            violations.append({"rule": RULE_IMAGE_READABLE, "message": error})
        else:
            if isinstance(width, int) and not isinstance(width, bool):
                if width != actual_width:
                    violations.append(
                        {
                            "rule": RULE_WIDTH_MATCH,
                            "message": "标注 width 与图片实际解码宽度不一致",
                            "expected": width,
                            "actual": actual_width,
                        }
                    )
            if isinstance(height, int) and not isinstance(height, bool):
                if height != actual_height:
                    violations.append(
                        {
                            "rule": RULE_HEIGHT_MATCH,
                            "message": "标注 height 与图片实际解码高度不一致",
                            "expected": height,
                            "actual": actual_height,
                        }
                    )

    boxes = annotation.get("boxes")
    if not isinstance(boxes, list):
        boxes = []
    for index, box in enumerate(boxes):
        if not isinstance(box, dict):
            continue
        values = [box.get(key) for key in ("class_id", "x", "y", "w", "h")]
        if any(
            not isinstance(value, int) or isinstance(value, bool) for value in values
        ):
            continue
        class_id, x, y, w, h = values
        if not 0 <= class_id < class_count:
            violations.append(
                {
                    "rule": RULE_CLASS_RANGE,
                    "box_index": index,
                    "message": f"class_id={class_id} 不在类别表 0～{class_count - 1} 范围内",
                    "expected": f"0 <= class_id < {class_count}",
                    "actual": class_id,
                }
            )
        if w * h <= 0:
            violations.append(
                {
                    "rule": RULE_AREA,
                    "box_index": index,
                    "message": f"框面积必须大于 0，实际 w={w}, h={h}",
                    "expected": "w * h > 0",
                    "actual": {"w": w, "h": h},
                }
            )
        if isinstance(width, int) and not isinstance(width, bool):
            if x + w > width:
                violations.append(
                    {
                        "rule": RULE_X_LIMIT,
                        "box_index": index,
                        "message": f"框右边界越界：x + w = {x + w} > width = {width}",
                        "expected": f"x + w <= {width}",
                        "actual": x + w,
                    }
                )
        if isinstance(height, int) and not isinstance(height, bool):
            if y + h > height:
                violations.append(
                    {
                        "rule": RULE_Y_LIMIT,
                        "box_index": index,
                        "message": f"框下边界越界：y + h = {y + h} > height = {height}",
                        "expected": f"y + h <= {height}",
                        "actual": y + h,
                    }
                )
    return violations


# --------------------------------------------------------------------------- #
# 合成图片与标注
# --------------------------------------------------------------------------- #


def _layout_boxes(index: int) -> tuple[SyntheticBox, ...]:
    """确定第 ``index`` 张图的框布局：单目标、多目标与贴边框循环覆盖。"""
    pattern = index % 4
    if pattern == 0:
        return (
            SyntheticBox(0, 8 + (index % 5) * 4, 10 + (index % 3) * 6, 30, 24),
        )
    if pattern == 1:
        return (
            SyntheticBox(1, 18 + (index % 4) * 5, 12 + (index % 3) * 8, 26, 22),
        )
    if pattern == 2:
        return (
            SyntheticBox(0, 6, 8, 22, 18),
            SyntheticBox(1, 70, 52, 28, 24),
        )
    # 贴边框：一个框贴左上角，一个框贴右下边界（右/下边界不含，x+w、y+h 可等于宽高）。
    return (
        SyntheticBox(0, 0, 0, 24, 20),
        SyntheticBox(1, IMAGE_WIDTH - 26, IMAGE_HEIGHT - 22, 26, 22),
    )


def _render_image(index: int, boxes: Sequence[SyntheticBox]) -> Image.Image:
    """按框画简单图形；颜色只用于肉眼区分，不参与标注语义。"""
    background = (244 - (index % 3) * 3, 246 - (index % 2) * 3, 238)
    image = Image.new("RGB", (IMAGE_WIDTH, IMAGE_HEIGHT), background)
    draw = ImageDraw.Draw(image)
    for box in boxes:
        bounds = (box.x, box.y, box.x + box.w - 1, box.y + box.h - 1)
        fill = CLASS_FILL[box.class_id]
        outline = CLASS_OUTLINE[box.class_id]
        if CLASSES[box.class_id] == "circle":
            draw.ellipse(bounds, fill=fill, outline=outline)
        else:
            draw.rectangle(bounds, fill=fill, outline=outline)
    return image


def generate_valid_dataset(output_dir: Path, count: int) -> list[GeneratedSample]:
    """生成 ``count`` 张合成 PNG 与对应草案标注 JSON。"""
    samples: list[GeneratedSample] = []
    for index in range(count):
        stem = f"case-{index:03d}"
        image_rel = f"images/{stem}.png"
        annotation_rel = f"annotations/{stem}.json"
        boxes = _layout_boxes(index)
        image_path = output_dir / image_rel
        image_path.parent.mkdir(parents=True, exist_ok=True)
        _render_image(index, boxes).save(image_path, format="PNG")

        annotation = {
            "image": image_rel,
            "width": IMAGE_WIDTH,
            "height": IMAGE_HEIGHT,
            "boxes": [box.to_json() for box in boxes],
        }
        _write_json_atomic(output_dir / annotation_rel, annotation)
        samples.append(
            GeneratedSample(
                index=index,
                image_rel=image_rel,
                annotation_rel=annotation_rel,
                annotation=annotation,
            )
        )
    return samples


def check_valid_dataset(
    output_dir: Path,
    validator: Draft202012Validator,
    samples: Sequence[GeneratedSample],
) -> tuple[int, list[dict[str, Any]]]:
    """校验所有有效样例；返回通过数与违例明细（正常应为空）。"""
    passed = 0
    violations: list[dict[str, Any]] = []
    for sample in samples:
        annotation_path = output_dir / sample.annotation_rel
        try:
            annotation = json.loads(annotation_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            violations.append(
                {
                    "annotation": sample.annotation_rel,
                    "rule": RULE_ANNOTATION_READABLE,
                    "message": f"标注文件无法读取或不是合法 JSON：{error}",
                }
            )
            continue

        issues = schema_issues(validator, annotation)
        for issue in issues:
            violations.append({"annotation": sample.annotation_rel, **issue})
        if issues:
            continue

        if annotation.get("image") != sample.image_rel:
            violations.append(
                {
                    "annotation": sample.annotation_rel,
                    "rule": RULE_IMAGE_PATH,
                    "message": "标注 image 字段与图片实际相对路径不一致",
                    "expected": sample.image_rel,
                    "actual": annotation.get("image"),
                }
            )
            continue

        semantic = semantic_violations(
            annotation, output_dir / sample.image_rel, len(CLASSES)
        )
        for violation in semantic:
            violations.append({"annotation": sample.annotation_rel, **violation})
        if not semantic:
            passed += 1
    return passed, violations


# --------------------------------------------------------------------------- #
# 故意无效样例
# --------------------------------------------------------------------------- #


def build_invalid_cases(image_rel: str) -> list[InvalidCase]:
    """构造故意无效的标注样例，覆盖越界、负值、零尺寸、类别与尺寸错误。"""

    def box(**overrides: int) -> dict[str, int]:
        data = {"class_id": 0, "x": 10, "y": 10, "w": 20, "h": 20}
        data.update(overrides)
        return data

    def annotation(**overrides: Any) -> dict[str, Any]:
        data: dict[str, Any] = {
            "image": image_rel,
            "width": IMAGE_WIDTH,
            "height": IMAGE_HEIGHT,
            "boxes": [box()],
        }
        data.update(overrides)
        return data

    return [
        # 结构合法、但跨字段/尺寸规则必须由代码补充检查拒绝的样例。
        InvalidCase(
            "x-overflow",
            "boundary",
            "semantic",
            (RULE_X_LIMIT,),
            annotation(boxes=[box(x=IMAGE_WIDTH - 5)]),
        ),
        InvalidCase(
            "y-overflow",
            "boundary",
            "semantic",
            (RULE_Y_LIMIT,),
            annotation(boxes=[box(y=IMAGE_HEIGHT - 5, h=10)]),
        ),
        InvalidCase(
            "class-id-out-of-range",
            "class_range",
            "semantic",
            (RULE_CLASS_RANGE,),
            annotation(boxes=[box(class_id=len(CLASSES))]),
        ),
        InvalidCase(
            "width-mismatch",
            "size_mismatch",
            "semantic",
            (RULE_WIDTH_MATCH,),
            annotation(width=IMAGE_WIDTH // 2),
        ),
        InvalidCase(
            "height-mismatch",
            "size_mismatch",
            "semantic",
            (RULE_HEIGHT_MATCH,),
            annotation(height=IMAGE_HEIGHT // 2),
        ),
        # 应被 Schema 单字段约束直接拒绝的样例。
        InvalidCase("negative-x", "negative", "schema", (), annotation(boxes=[box(x=-1)])),
        InvalidCase(
            "negative-width", "negative", "schema", (), annotation(boxes=[box(w=-4)])
        ),
        InvalidCase(
            "zero-width", "zero_area", "schema", (), annotation(boxes=[box(w=0)])
        ),
        InvalidCase(
            "zero-height", "zero_area", "schema", (), annotation(boxes=[box(h=0)])
        ),
        InvalidCase(
            "negative-class-id",
            "negative",
            "schema",
            (),
            annotation(boxes=[box(class_id=-1)]),
        ),
    ]


def write_invalid_cases(output_dir: Path, cases: Sequence[InvalidCase]) -> None:
    for case in cases:
        _write_json_atomic(output_dir / case.annotation_rel, case.annotation)


def evaluate_invalid_cases(
    output_dir: Path,
    validator: Draft202012Validator,
    cases: Sequence[InvalidCase],
) -> tuple[list[dict[str, Any]], int, list[str]]:
    """逐个验证故意无效样例被拒绝；返回明细、补充检查违例数、告警。"""
    reports: list[dict[str, Any]] = []
    semantic_count = 0
    warnings: list[str] = []
    for case in cases:
        annotation: Any = None
        try:
            annotation = json.loads(
                (output_dir / case.annotation_rel).read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as error:
            warnings.append(f"无效样例 {case.name} 无法读取：{error}")

        issues: list[dict[str, Any]] = []
        semantic: list[dict[str, Any]] = []
        if annotation is None:
            channel: str | None = None
        else:
            issues = schema_issues(validator, annotation)
            if issues:
                channel = "schema"
            else:
                semantic = semantic_violations(
                    annotation, output_dir / case.annotation["image"], len(CLASSES)
                )
                channel = "semantic" if semantic else None
                semantic_count += len(semantic)

        rejected = channel is not None
        if channel is None:
            expected_ok = False
        elif case.expect_channel == "schema":
            expected_ok = channel == "schema"
        else:
            rules = {item["rule"] for item in semantic}
            expected_ok = channel == "semantic" and all(
                rule in rules for rule in case.expected_rules
            )

        if rejected and not expected_ok:
            warnings.append(
                f"无效样例 {case.name} 被拒绝，但拒绝渠道/规则与预期不符"
                f"（预期 {case.expect_channel}，实际 {channel}）"
            )
        elif not rejected:
            warnings.append(f"无效样例 {case.name} 未被拒绝")

        reports.append(
            {
                "name": case.name,
                "kind": case.kind,
                "annotation": case.annotation_rel,
                "expected_channel": case.expect_channel,
                "expected_rules": list(case.expected_rules),
                "rejected": rejected,
                "rejected_by": channel,
                "violations": issues + semantic,
                "ok": bool(rejected and expected_ok),
            }
        )
    return reports, semantic_count, warnings


# --------------------------------------------------------------------------- #
# 输出目录整洁性
# --------------------------------------------------------------------------- #


def _stale_files(output_dir: Path, expected: set[Path]) -> list[str]:
    """列出输出目录中不属于本次生成的文件（工具不删除用户已有文件）。"""
    stale: list[str] = []
    for relative_dir in ("images", "annotations", "invalid/annotations"):
        directory = output_dir / relative_dir
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if path.is_file() and path not in expected:
                stale.append(path.relative_to(output_dir).as_posix())
    return stale


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #


def run_check(output_dir: Path, image_count: int) -> dict[str, Any]:
    """执行完整检查并返回 JSON 摘要（同时写入输出目录）。"""
    if image_count < 1:
        raise DraftCheckError("IMAGE_COUNT_INVALID", "--images 必须大于等于 1")
    if image_count > MAX_IMAGE_COUNT:
        raise DraftCheckError(
            "IMAGE_COUNT_INVALID",
            f"--images 上限为 {MAX_IMAGE_COUNT}（本工具用于小规模边界验证）",
        )
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise DraftCheckError(
            "OUTPUT_DIR_UNWRITABLE",
            f"无法创建输出目录 {output_dir}：{error.strerror or error}",
        ) from error

    schema_path = ROOT / SCHEMA_REL_PATH
    validator = load_schema_validator(schema_path)

    warnings: list[str] = []
    if image_count < MIN_COVERAGE_IMAGES:
        warnings.append(
            f"合成图片只有 {image_count} 张，可能未覆盖多目标与贴边框场景"
            f"（建议至少 {MIN_COVERAGE_IMAGES} 张）。"
        )

    samples = generate_valid_dataset(output_dir, image_count)
    valid_passed, valid_violations = check_valid_dataset(
        output_dir, validator, samples
    )
    if valid_passed != len(samples):
        warnings.append(
            f"有效样例未全部通过：{len(samples) - valid_passed} 个失败，"
            f"{len(valid_violations)} 条违例明细。"
        )

    invalid_cases = build_invalid_cases(samples[0].image_rel)
    write_invalid_cases(output_dir, invalid_cases)
    case_reports, invalid_semantic_count, case_warnings = evaluate_invalid_cases(
        output_dir, validator, invalid_cases
    )
    warnings.extend(case_warnings)

    rejected_total = sum(1 for report in case_reports if report["rejected"])
    edge_annotations = sum(1 for sample in samples if sample.edge_touch)
    if edge_annotations == 0:
        warnings.append("没有生成贴边框样例，x+w<=width 与 y+h<=height 的包含边界未被覆盖。")

    expected_files: set[Path] = set()
    for sample in samples:
        expected_files.add(output_dir / sample.image_rel)
        expected_files.add(output_dir / sample.annotation_rel)
    for case in invalid_cases:
        expected_files.add(output_dir / case.annotation_rel)
    stale = _stale_files(output_dir, expected_files)
    if stale:
        warnings.append(
            "输出目录中存在非本次生成的文件（工具不清理用户目录）："
            + "、".join(stale[:5])
            + (" 等" if len(stale) > 5 else "")
        )

    ok = (
        len(samples) == image_count
        and valid_passed == len(samples)
        and not valid_violations
        and rejected_total == len(case_reports)
        and all(report["ok"] for report in case_reports)
    )
    boundary_violations = len(valid_violations) + invalid_semantic_count

    summary: dict[str, Any] = {
        "ok": ok,
        "tool": TOOL_NAME,
        "draft": True,
        "activated": False,
        "notes": list(DRAFT_NOTES),
        "output": str(output_dir),
        "summary_file": str(output_dir / SUMMARY_FILE_NAME),
        "schema_path": SCHEMA_REL_PATH,
        "schema_sha256": _sha256_file(schema_path),
        "classes": list(CLASSES),
        "image_size": [IMAGE_WIDTH, IMAGE_HEIGHT],
        "images": len(samples),
        "valid_annotations": valid_passed,
        "invalid_annotations": len(invalid_cases),
        "boundary_violations": boundary_violations,
        "valid_set_violations": valid_violations,
        "rejected_cases": case_reports,
        "edge_case_annotations": edge_annotations,
        "warnings": warnings,
        "generated_at": _now_text(),
        "python_version": sys.version.split()[0],
        "pillow_version": PILLOW_VERSION,
    }
    _write_json_atomic(output_dir / SUMMARY_FILE_NAME, summary)
    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python scripts/detection_draft_check.py",
        description=(
            "检测草案合成图片/标注边界验证工具（草案，未激活）：生成合成 PNG 与"
            "草案标注，校验 annotation.schema.json 及 Schema 无法表达的边界规则，"
            "并验证故意无效样例被拒绝。"
        ),
    )
    parser.add_argument(
        "--output",
        default=None,
        help=f"输出目录；默认 %%TEMP%%/{DEFAULT_OUTPUT_NAME}（不得位于仓库受保护目录下）",
    )
    parser.add_argument(
        "--images",
        type=int,
        default=DEFAULT_IMAGE_COUNT,
        metavar="N",
        help=f"合成图片数量（默认 {DEFAULT_IMAGE_COUNT}）",
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
    error_notes = list(DRAFT_NOTES)
    try:
        output_dir = resolve_output(args.output)
        summary = run_check(output_dir, args.images)
    except DraftCheckError as error:
        _emit_json(
            {
                "ok": False,
                "tool": TOOL_NAME,
                "draft": True,
                "activated": False,
                "notes": error_notes,
                "code": error.code,
                "error": error.message,
            }
        )
        return 1
    except Exception as error:  # 不把异常堆栈当正常输出；保持稳定 JSON + 退出码 1
        _emit_json(
            {
                "ok": False,
                "tool": TOOL_NAME,
                "draft": True,
                "activated": False,
                "notes": error_notes,
                "code": "DETECTION_DRAFT_CHECK_FAILED",
                "error": f"检查过程异常（{type(error).__name__}）：{error}",
            }
        )
        return 1

    _emit_json(summary)
    return 0 if summary["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
