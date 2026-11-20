"""数据集体检报告：供老师课前检查项目数据质量，输出 Markdown 与可选 CSV。

用法：
    python scripts/dataset_report.py --project <project.json> [--output report.md] [--csv samples.csv]

只读现有 ``project.json`` 与 ``data/`` 目录，不重建数据清单、不修改项目：

- 训练/验证/测试样本数来自项目数据清单；清单缺失时仍扫描目录并提示；
- 每类每批次样本数直接扫描 ``data/images/<类别>/<批次>/`` 与
  ``data/test-images/<类别>/<批次>/``（与 ``backend.classification.dataset`` 约定一致）；
- 用文件 SHA-256 做内容重复检查，用 Pillow 打开解码检查无效图片；
- 输出 Markdown 报告，可选输出逐样本 CSV；标准输出为 UTF-8 JSON 摘要。

退出码：报告生成成功为 0（数据风险只写入报告，不改变退出码）；
项目文件缺失/无法读取或项目图片目录不存在为 1（输出错误 JSON）。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, UnidentifiedImageError

from backend.classification.dataset import IMAGE_SUFFIXES, TEST_DIR_NAME
from backend.console import emit_json
from backend.contracts import integrity, paths
from backend.project.project import (
    PROJECT_FILE,
    Project,
    ProjectError,
    load_project,
)

DATA_DIR_NAME = "data"
TRAIN_IMAGE_DIR = "images"  # 训练/验证样本来源，训练/验证划分由数据清单按批次决定
SPLITS = ("train", "val", "test")
SPLIT_LABELS = {"train": "训练", "val": "验证", "test": "测试", "unassigned": "未划分"}
MIN_CLASS_SAMPLES = 30
SIZE_TOP = 5
UNBATCHED = "（未分批次）"
SEVERE = "严重"
NOTE = "提示"


class ReportError(Exception):
    """报告无法生成（项目图片目录缺失、输出写入失败等）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Sample:
    """扫描到的一个图片样本。``path`` 相对项目根目录，使用 / 分隔。"""

    path: str
    class_name: str
    batch: str
    source: str
    split: str
    sha256: str = ""
    width: int | None = None
    height: int | None = None
    error: str | None = None
    duplicate: bool = False

    @property
    def valid(self) -> bool:
        return self.error is None


@dataclass
class ManifestInfo:
    """项目数据清单的只读快照；缺失或不可用时 ``present`` 为 False。"""

    declared: str | None = None
    present: bool = False
    error: str | None = None
    dataset_root: Path | None = None
    classes: list[str] = field(default_factory=list)
    split_counts: dict[str, int] = field(
        default_factory=lambda: {split: 0 for split in SPLITS}
    )
    class_splits: dict[str, dict[str, int]] = field(default_factory=dict)
    # 规范化绝对路径 -> (文件路径, 清单样本)；用于把目录扫描结果对回清单划分。
    index: dict[str, tuple[Path, dict[str, Any]]] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.split_counts.values())


@dataclass
class ScanResult:
    """``data/`` 目录扫描结果。"""

    samples: list[Sample] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    class_totals: dict[str, int] = field(default_factory=dict)
    image_batches: dict[str, set[str]] = field(default_factory=dict)
    unbatched: int = 0
    unknown_class_dirs: list[str] = field(default_factory=list)


@dataclass
class ReportData:
    project: Project
    root: Path
    project_file: Path
    manifest: ManifestInfo
    scan: ScanResult
    duplicates: list[tuple[str, list[Sample]]]
    warnings: list[tuple[str, str]]
    generated_at: str


@dataclass
class ReportResult:
    project_file: Path
    report_path: Path
    csv_path: Path | None
    classes: int
    samples: int
    duplicates: int
    invalid: int
    warnings: int


def _now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _abs_key(path: Path) -> str:
    """用于跨清单/扫描比对的路径键（Windows 下大小写不敏感）。"""
    try:
        resolved = path.resolve()
    except OSError:  # pragma: no cover - 仅极端路径解析失败
        resolved = path.absolute()
    return os.path.normcase(str(resolved))


def _cell(value: object) -> str:
    """转义 Markdown 表格单元格。"""
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def _split_label(split: str) -> str:
    return SPLIT_LABELS.get(split, split)


def _ordered_splits(items: Iterable[Sample]) -> list[str]:
    used = {sample.split for sample in items}
    order = (*SPLITS, "unassigned")
    return [split for split in order if split in used]


def _inspect_image(path: Path) -> tuple[int | None, int | None, str | None]:
    """用 Pillow 打开并完整解码图片，成功返回宽高。

    失败时返回的提示不包含绝对路径，报告里用项目相对路径定位文件，
    复制项目后报告仍可读。
    """
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
            return image.width, image.height, None
    except UnidentifiedImageError:
        return None, None, "无法解码：无法识别图片格式（文件可能损坏或不是图片）"
    except (OSError, ValueError) as error:  # 截断/损坏等解码错误
        return None, None, f"无法解码：{error}"
    except Exception as error:  # pragma: no cover - Pillow 其它异常类型
        return None, None, f"无法解码（{type(error).__name__}）"


def _iter_image_files(directory: Path) -> list[Path]:
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )


def _load_project_root(project: str | Path) -> tuple[Path, Path, Project]:
    """解析 ``--project``（project.json 或项目目录）并加载项目。"""
    candidate = Path(project)
    project_file = candidate / PROJECT_FILE if candidate.is_dir() else candidate
    loaded = load_project(project_file)
    resolved = project_file.resolve()
    return resolved.parent, resolved, loaded


def _load_manifest(root: Path, project: Project) -> ManifestInfo:
    info = ManifestInfo(declared=project.dataset_manifest)
    if project.dataset_manifest is None:
        return info
    target = paths.resolve_in_package(root, project.dataset_manifest)
    if target is None:
        info.error = f"数据清单路径越出项目目录：{project.dataset_manifest}"
        return info
    if not target.is_file():
        info.error = f"数据清单不存在：{project.dataset_manifest}"
        return info
    try:
        data = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        info.error = f"数据清单无法读取：{error}"
        return info
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("samples"), list)
        or not isinstance(data.get("classes"), list)
    ):
        info.error = "数据清单结构不完整（缺少 classes 或 samples）"
        return info

    info.present = True
    info.dataset_root = target.parent
    info.classes = [str(item) for item in data["classes"]]
    info.class_splits = {
        name: {split: 0 for split in SPLITS} for name in project.classes
    }
    for item in data["samples"]:
        if not isinstance(item, dict):
            continue
        split = item.get("split")
        if split not in SPLITS:
            continue
        info.split_counts[split] += 1
        class_id = item.get("class_id")
        if isinstance(class_id, int) and 0 <= class_id < len(info.classes):
            name = info.classes[class_id]
            if name in info.class_splits:
                info.class_splits[name][split] += 1
        relative = item.get("path")
        if isinstance(relative, str) and relative:
            sample_path = target.parent / relative
            info.index[_abs_key(sample_path)] = (sample_path, item)
    return info


def _make_sample(
    root: Path,
    source: str,
    class_name: str,
    batch: str,
    path: Path,
    manifest: ManifestInfo,
) -> Sample:
    try:
        relative_path = path.relative_to(root).as_posix()
    except ValueError:  # pragma: no cover - 扫描结果总在项目目录内
        relative_path = f"{DATA_DIR_NAME}/{source}/{class_name}/{batch}/{path.name}"
    sample = Sample(
        path=relative_path,
        class_name=class_name,
        batch=batch,
        source=source,
        split="unassigned",
    )
    try:
        sample.sha256 = integrity.sha256_file(path)
    except OSError as error:
        sample.error = f"无法读取文件：{error.strerror or error}"
    if sample.error is None:
        width, height, decode_error = _inspect_image(path)
        sample.width = width
        sample.height = height
        sample.error = decode_error

    matched = manifest.index.get(_abs_key(path)) if manifest.present else None
    if matched is not None:
        split = str(matched[1].get("split") or "unassigned")
        sample.split = split if split in SPLIT_LABELS else "unassigned"
    elif source == TEST_DIR_NAME:
        # 即使清单缺失，test-images/ 目录本身仍表示测试集。
        sample.split = "test"
    return sample


def _scan(
    root: Path,
    data_root: Path,
    project: Project,
    manifest: ManifestInfo,
) -> ScanResult:
    result = ScanResult(
        class_totals={name: 0 for name in project.classes},
        image_batches={name: set() for name in project.classes},
    )
    result.sources = [
        name
        for name in (TRAIN_IMAGE_DIR, TEST_DIR_NAME)
        if (data_root / name).is_dir()
    ]
    known = set(project.classes)
    for source in result.sources:
        base = data_root / source
        for entry in sorted(base.iterdir()):
            if entry.is_dir() and entry.name not in known:
                result.unknown_class_dirs.append(f"data/{source}/{entry.name}")
        for class_name in project.classes:
            class_dir = base / class_name
            if not class_dir.is_dir():
                continue
            for batch_dir in sorted(
                path for path in class_dir.iterdir() if path.is_dir()
            ):
                files = _iter_image_files(batch_dir)
                if not files:
                    continue
                if source == TRAIN_IMAGE_DIR:
                    result.image_batches[class_name].add(batch_dir.name)
                for path in files:
                    result.samples.append(
                        _make_sample(
                            root, source, class_name, batch_dir.name, path, manifest
                        )
                    )
                    result.class_totals[class_name] += 1
            # 直接放在类别目录下的图片没有批次子目录，数据清单无法按批次划分。
            for path in _iter_image_files(class_dir):
                result.samples.append(
                    _make_sample(root, source, class_name, UNBATCHED, path, manifest)
                )
                result.class_totals[class_name] += 1
                result.unbatched += 1
    return result


def _collect_duplicates(
    samples: Sequence[Sample],
) -> list[tuple[str, list[Sample]]]:
    by_digest: dict[str, list[Sample]] = {}
    for sample in samples:
        if sample.sha256:
            by_digest.setdefault(sample.sha256, []).append(sample)
    groups = [
        (digest, items) for digest, items in by_digest.items() if len(items) > 1
    ]
    groups.sort(key=lambda item: (-len(item[1]), item[0]))
    for _, items in groups:
        for sample in items:
            sample.duplicate = True
    return groups


def _collect_warnings(
    *,
    root: Path,
    project: Project,
    manifest: ManifestInfo,
    scan: ScanResult,
    duplicates: Sequence[tuple[str, list[Sample]]],
) -> list[tuple[str, str]]:
    """返回 (级别, 提示) 列表；严重项排在提示项之前，同级保持固定顺序。"""
    warnings: list[tuple[str, str]] = []
    samples = scan.samples
    invalid = [sample for sample in samples if not sample.valid]

    if not samples:
        warnings.append((SEVERE, "没有扫描到任何图片样本，项目无法训练。"))
    if not manifest.present:
        if manifest.error is not None:
            warnings.append(
                (
                    SEVERE,
                    f"数据清单不可用：{manifest.error}；报告按 data/ 目录直接扫描，"
                    "训练/验证划分未知。",
                )
            )
        else:
            warnings.append(
                (
                    NOTE,
                    "项目尚未生成数据清单，训练/验证划分未知；"
                    "请导入图片后重建数据清单（rebuild-dataset）。",
                )
            )
    if not (root / DATA_DIR_NAME / TRAIN_IMAGE_DIR).is_dir():
        warnings.append(
            (SEVERE, f"缺少训练/验证图片目录 data/{TRAIN_IMAGE_DIR}。")
        )
    if invalid:
        warnings.append(
            (
                SEVERE,
                f"{len(invalid)} 张图片无法读取或解码，训练前应删除或替换（见第 4 节）。",
            )
        )
    if duplicates:
        involved = sum(len(items) for _, items in duplicates)
        cross = any(
            len(
                {
                    sample.split
                    for sample in items
                    if sample.split != "unassigned"
                }
            )
            > 1
            for _, items in duplicates
        )
        message = (
            f"发现 {len(duplicates)} 组内容重复的图片（涉及 {involved} 张），"
            "重复样本会造成训练/验证/测试泄漏。"
        )
        if cross:
            message += "其中存在跨划分重复，评估结果会被高估。"
        warnings.append((SEVERE, message))
    if scan.unbatched:
        warnings.append(
            (
                NOTE,
                f"{scan.unbatched} 张图片直接放在类别目录下，缺少采集批次子目录；"
                "数据清单要求 <类别>/<批次>/<图片> 结构。",
            )
        )
    if scan.unknown_class_dirs:
        shown = "、".join(scan.unknown_class_dirs[:5])
        suffix = " 等" if len(scan.unknown_class_dirs) > 5 else ""
        warnings.append(
            (
                NOTE,
                f"数据目录中存在不属于项目的类别目录：{shown}{suffix}，未计入报告。",
            )
        )

    for class_name in project.classes:
        total = scan.class_totals.get(class_name, 0)
        if total == 0:
            warnings.append((SEVERE, f"类别「{class_name}」没有任何图片样本。"))
        elif total < MIN_CLASS_SAMPLES:
            warnings.append(
                (
                    NOTE,
                    f"类别「{class_name}」只有 {total} 张样本，"
                    f"少于建议的 {MIN_CLASS_SAMPLES} 张。",
                )
            )
        batches = scan.image_batches.get(class_name, set())
        if total > 0 and len(batches) < 2:
            warnings.append(
                (
                    SEVERE,
                    f"类别「{class_name}」在 images/ 下只有 {len(batches)} 个采集批次，"
                    "无法按批次划分训练/验证（至少需要 2 个）。",
                )
            )

    if manifest.present:
        counts = manifest.split_counts
        if counts["train"] == 0:
            warnings.append((SEVERE, "训练样本数为 0，无法训练。"))
        if counts["val"] == 0:
            warnings.append((NOTE, "验证样本数为 0，无法验证训练过程。"))
        if counts["test"] == 0:
            warnings.append((SEVERE, "测试样本数为 0，无法评估模型泛化能力。"))
        if manifest.classes != project.classes:
            warnings.append(
                (
                    SEVERE,
                    "数据清单类别表与项目类别表不一致，类别 ID 可能整体错位；"
                    "请重建数据清单。",
                )
            )
        missing_files = sum(
            1 for file_path, _ in manifest.index.values() if not file_path.is_file()
        )
        if missing_files:
            warnings.append(
                (
                    SEVERE,
                    f"数据清单中有 {missing_files} 个样本文件在磁盘上不存在"
                    "（清单可能过期）。",
                )
            )
        tracked = set(manifest.index)
        untracked = sum(
            1 for sample in samples if _abs_key(root / sample.path) not in tracked
        )
        if untracked:
            warnings.append(
                (
                    NOTE,
                    f"磁盘上有 {untracked} 张图片未记录在数据清单中"
                    "（清单可能过期，训练前请重建）。",
                )
            )
        if manifest.classes == project.classes:
            for class_name in project.classes:
                class_counts = manifest.class_splits.get(class_name, {})
                for split in SPLITS:
                    if counts[split] > 0 and class_counts.get(split, 0) == 0:
                        warnings.append(
                            (
                                SEVERE,
                                f"类别「{class_name}」在{_split_label(split)}划分中没有样本。",
                            )
                        )
    else:
        test_count = sum(
            1 for sample in samples if sample.source == TEST_DIR_NAME
        )
        if test_count == 0:
            warnings.append(
                (
                    NOTE,
                    f"未发现独立测试集图片（data/{TEST_DIR_NAME}/），"
                    "无法评估泛化能力。",
                )
            )

    severe = [item for item in warnings if item[0] == SEVERE]
    notes = [item for item in warnings if item[0] != SEVERE]
    return severe + notes


def _current_model(project: Project) -> str:
    current = project.current_model()
    if current is not None:
        return f"`{current.artifact_id}`（{current.kind}，`{current.path}`）"
    if project.models:
        return f"未设置（项目已有 {len(project.models)} 个模型记录）"
    return "未设置"


def _manifest_line(manifest: ManifestInfo) -> str:
    if manifest.present:
        return f"`{manifest.declared}`（已生成，{manifest.total} 个样本）"
    if manifest.declared is None:
        return "未生成（project.json 中没有 dataset_manifest）"
    return f"`{manifest.declared}`（不可用：{manifest.error}）"


def _sources_line(scan: ScanResult) -> str:
    if not scan.sources:
        return "无"
    return "、".join(f"`data/{source}`" for source in scan.sources)


def _render_markdown(data: ReportData) -> str:
    project = data.project
    manifest = data.manifest
    scan = data.scan
    lines: list[str] = []

    def add(text: str = "") -> None:
        lines.append(text)

    add("# 数据集体检报告")
    add()
    add(f"生成时间：{data.generated_at}")
    add()
    add("## 1. 基本信息")
    add()
    add("| 项目 | 内容 |")
    add("| --- | --- |")
    add(f"| 项目名 | {_cell(project.name)} |")
    add(f"| 项目 ID | {_cell(project.project_id)} |")
    add(f"| 项目路径 | `{data.root}` |")
    add(f"| 项目文件 | `{data.project_file}` |")
    add(f"| 任务类型 | {_cell(project.task)} |")
    add(f"| 类别（{len(project.classes)} 个） | {_cell('、'.join(project.classes))} |")
    add(f"| 当前模型 | {_current_model(project)} |")
    add(f"| 数据清单 | {_manifest_line(manifest)} |")
    add(f"| 扫描目录 | {_sources_line(scan)} |")
    add()

    add("## 2. 训练/验证/测试样本数")
    add()
    add("| 划分 | 样本数 |")
    add("| --- | ---: |")
    if manifest.present:
        for split in SPLITS:
            add(f"| {_split_label(split)}（{split}） | {manifest.split_counts[split]} |")
        add(f"| 合计 | {manifest.total} |")
        add()
        add(f"> 统计来自数据清单 `{manifest.declared}`。")
    else:
        for split in SPLITS:
            add(f"| {_split_label(split)}（{split}） | 未生成 |")
        add()
        add("数据清单未生成或不可用；按 `data/` 目录直接扫描的图片数：")
        add()
        add("| 目录 | 图片数 |")
        add("| --- | ---: |")
        labels = {
            TRAIN_IMAGE_DIR: "训练/验证来源",
            TEST_DIR_NAME: "独立测试集",
        }
        for source in (TRAIN_IMAGE_DIR, TEST_DIR_NAME):
            count = sum(1 for sample in scan.samples if sample.source == source)
            add(f"| `data/{source}`（{labels[source]}） | {count} |")
        add(f"| 合计 | {len(scan.samples)} |")
    add()

    add("## 3. 每类每批次样本数")
    add()
    add("| 类别 | 批次 | 来源目录 | 清单划分 | 样本数 |")
    add("| --- | --- | --- | --- | ---: |")
    grouped: dict[tuple[str, str, str], list[Sample]] = {}
    for sample in scan.samples:
        grouped.setdefault(
            (sample.class_name, sample.source, sample.batch), []
        ).append(sample)
    source_order = {
        name: index for index, name in enumerate((TRAIN_IMAGE_DIR, TEST_DIR_NAME))
    }
    for class_name in project.classes:
        keys = sorted(
            (key for key in grouped if key[0] == class_name),
            key=lambda key: (source_order.get(key[1], 99), key[2]),
        )
        if not keys:
            add(f"| {_cell(class_name)} | （没有批次） | — | — | 0 |")
            continue
        for key in keys:
            items = grouped[key]
            split_label = "、".join(_split_label(split) for split in _ordered_splits(items))
            add(
                f"| {_cell(class_name)} | {_cell(key[2])} | `data/{key[1]}` "
                f"| {split_label} | {len(items)} |"
            )
    if scan.samples:
        add(f"| 合计 | {len(grouped)} 个批次 | — | — | {len(scan.samples)} |")
    add()
    if scan.unbatched:
        add(
            f"> 有 {scan.unbatched} 张图片没有批次子目录，"
            f"已按「{UNBATCHED}」统计。"
        )
        add()

    add("## 4. 重复与无效图片检查")
    add()
    add(
        f"已检查 {len(scan.samples)} 张图片：文件 SHA-256 精确比对 + Pillow 打开解码。"
    )
    add()
    add("### 重复图片")
    add()
    if data.duplicates:
        for index, (digest, items) in enumerate(data.duplicates, start=1):
            add(
                f"重复组 {index}：{len(items)} 张，"
                f"sha256 前 12 位 `{digest[:12]}`"
            )
            add()
            for item in items:
                add(
                    f"- `{item.path}`"
                    f"（{_cell(item.class_name)} / {_cell(item.batch)} / "
                    f"{_split_label(item.split)}）"
                )
            add()
    else:
        add("未发现内容重复的图片。")
        add()
    add("### 无法读取或解码的图片")
    add()
    invalid = [sample for sample in scan.samples if not sample.valid]
    if invalid:
        add("| 文件 | 错误 |")
        add("| --- | --- |")
        for sample in invalid:
            add(f"| `{sample.path}` | {_cell(sample.error or '')} |")
    else:
        add("未发现无法读取或解码的图片。")
    add()

    add(f"## 5. 图片尺寸分布（前 {SIZE_TOP}）")
    add()
    valid = [
        sample
        for sample in scan.samples
        if sample.valid and sample.width is not None and sample.height is not None
    ]
    sizes = Counter((sample.width, sample.height) for sample in valid)
    if sizes:
        add("| 宽×高 | 数量 | 占比 |")
        add("| --- | ---: | ---: |")
        for (width, height), count in sizes.most_common(SIZE_TOP):
            add(f"| {width}×{height} | {count} | {count / len(valid) * 100:.1f}% |")
        if len(sizes) > SIZE_TOP:
            add()
            add(
                f"> 共 {len(sizes)} 种尺寸，仅列出数量最多的 {SIZE_TOP} 种。"
            )
    else:
        add("没有可读取尺寸的有效图片。")
    add()

    add("## 6. 风险提示")
    add()
    if data.warnings:
        for severity, message in data.warnings:
            add(f"- 【{severity}】{message}")
    else:
        add("未发现明显风险。")
    add()
    add("---")
    add()
    add(
        "本报告只读取项目文件与 `data/` 目录，不重建数据清单、不修改项目；"
        "严格训练前验收请使用 `python -m backend.project check-dataset`。"
    )
    add()
    return "\n".join(lines)


def _write_text(path: Path, text: str, label: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as error:
        raise ReportError(
            "REPORT_WRITE_FAILED",
            f"无法写入 {label} {path}：{error.strerror or error}",
        ) from error


def _write_csv(samples: Sequence[Sample], path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "相对路径",
                    "类别",
                    "批次",
                    "划分",
                    "宽度",
                    "高度",
                    "sha256前12位",
                    "是否重复",
                ]
            )
            for sample in samples:
                writer.writerow(
                    [
                        sample.path,
                        sample.class_name,
                        sample.batch,
                        _split_label(sample.split),
                        sample.width if sample.width is not None else "",
                        sample.height if sample.height is not None else "",
                        sample.sha256[:12],
                        "是" if sample.duplicate else "否",
                    ]
                )
    except OSError as error:
        raise ReportError(
            "REPORT_WRITE_FAILED",
            f"无法写入 CSV {path}：{error.strerror or error}",
        ) from error


def generate_report(
    project: str | Path,
    *,
    output: str | Path | None = None,
    csv_path: str | Path | None = None,
) -> ReportResult:
    """生成报告并返回输出路径与统计。数据风险不抛异常，只写入报告。"""
    root, project_file, loaded = _load_project_root(project)
    manifest = _load_manifest(root, loaded)

    data_root = root / DATA_DIR_NAME
    if not data_root.is_dir():
        raise ReportError(
            "REPORT_IMAGE_DIR_MISSING",
            f"项目图片目录不存在：{data_root}",
        )
    image_dirs = [
        name
        for name in (TRAIN_IMAGE_DIR, TEST_DIR_NAME)
        if (data_root / name).is_dir()
    ]
    if not image_dirs:
        raise ReportError(
            "REPORT_IMAGE_DIR_MISSING",
            f"项目图片目录不存在：{data_root / TRAIN_IMAGE_DIR} 或 "
            f"{data_root / TEST_DIR_NAME}",
        )

    scan = _scan(root, data_root, loaded, manifest)
    duplicates = _collect_duplicates(scan.samples)
    warnings = _collect_warnings(
        root=root,
        project=loaded,
        manifest=manifest,
        scan=scan,
        duplicates=duplicates,
    )
    data = ReportData(
        project=loaded,
        root=root,
        project_file=project_file,
        manifest=manifest,
        scan=scan,
        duplicates=duplicates,
        warnings=warnings,
        generated_at=_now_text(),
    )

    report_path = (
        Path(output) if output is not None else root / "dataset-report.md"
    ).resolve()
    _write_text(report_path, _render_markdown(data), "Markdown 报告")

    resolved_csv: Path | None = None
    if csv_path is not None:
        resolved_csv = Path(csv_path).resolve()
        _write_csv(scan.samples, resolved_csv)

    return ReportResult(
        project_file=project_file,
        report_path=report_path,
        csv_path=resolved_csv,
        classes=len(loaded.classes),
        samples=len(scan.samples),
        duplicates=len(duplicates),
        invalid=sum(1 for sample in scan.samples if not sample.valid),
        warnings=len(warnings),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python scripts/dataset_report.py",
        description=(
            "LAITP 数据集体检报告：为老师课前检查项目数据质量，"
            "输出 Markdown 报告与可选逐样本 CSV。"
        ),
    )
    parser.add_argument(
        "--project", required=True, help="project.json 或项目目录"
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Markdown 报告输出路径；默认 <项目目录>/dataset-report.md",
    )
    parser.add_argument(
        "--csv", dest="csv_path", default=None, help="可选：逐样本 CSV 输出路径"
    )
    return parser


def _emit_error(project: str | Path, code: str, message: str) -> None:
    emit_json(
        {"ok": False, "project": str(project), "code": code, "error": message}
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        result = generate_report(
            args.project, output=args.output, csv_path=args.csv_path
        )
    except ProjectError as error:
        _emit_error(args.project, error.code.value, error.message)
        return 1
    except ReportError as error:
        _emit_error(args.project, error.code, error.message)
        return 1

    emit_json(
        {
            "ok": True,
            "project": str(result.project_file),
            "report": str(result.report_path),
            "csv": None if result.csv_path is None else str(result.csv_path),
            "classes": result.classes,
            "samples": result.samples,
            "duplicates": result.duplicates,
            "invalid": result.invalid,
            "warnings": result.warnings,
        }
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
