"""项目数据集导入：把图片复制进项目目录并重建数据清单。

当前只做批量导入（文件夹），不做摄像头采集与标注编辑。图片统一转为
RGB PNG，按内容摘要去重；导入后尝试重建数据清单，数据量不足时保留文件
并报告原因，方便课堂继续采集。
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..classification.dataset import (
    BATCH_PATTERN,
    DEFAULT_DATASET_POLICY,
    DatasetError,
    DatasetPolicy,
    IMAGE_SUFFIXES,
    TEST_DIR_NAME,
    build_dataset_manifest,
    summarize,
    validate_dataset_manifest,
)
from ..contracts import integrity
from ..contracts.errors import Code
from .project import (
    PROJECT_FILE,
    ProjectError,
    _try_rebuild,
    load_project,
    save_project,
)

SPLITS = ("train", "test")
_STEM_ALLOWED = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff._-]+")


@dataclass
class ImportResult:
    imported: int = 0
    duplicates: int = 0
    invalid: int = 0
    target_dir: str = ""
    batch: str = ""
    split: str = "train"
    manifest_path: str | None = None
    manifest_error: str | None = None
    class_counts: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "imported": self.imported,
            "duplicates": self.duplicates,
            "invalid": self.invalid,
            "target_dir": self.target_dir,
            "batch": self.batch,
            "split": self.split,
            "manifest_path": self.manifest_path,
            "manifest_error": self.manifest_error,
            "class_counts": self.class_counts,
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _image_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )


def _existing_digests(data_root: Path) -> set[str]:
    digests: set[str] = set()
    for folder in (data_root / "images", data_root / TEST_DIR_NAME):
        for path in _image_files(folder):
            try:
                digests.add(integrity.sha256_file(path))
            except OSError:
                continue
    return digests


def _safe_stem(name: str) -> str:
    stem = _STEM_ALLOWED.sub("_", name).strip("._- ") or "image"
    return stem[:80]


def _write_png(source: Path, target: Path) -> None:
    from PIL import Image

    with Image.open(source) as image:
        image.load()
        converted = image.convert("RGB")
        converted.save(target, format="PNG")


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _counts(manifest: dict[str, Any]) -> dict[str, Any]:
    summary = summarize(manifest)
    return {
        "splits": summary["splits"],
        "total": summary["total"],
        "by_class": summary["by_class"],
    }


def rebuild_dataset(
    root: str | Path,
    *,
    dataset_id: str | None = None,
    created_at: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    """扫描项目 data/ 目录并重建数据集清单，随后写回 project.json。"""
    root = Path(root)
    project = load_project(root / PROJECT_FILE)
    data_root = root / "data"
    manifest = build_dataset_manifest(
        data_root,
        classes=project.classes,
        dataset_id=dataset_id or f"ds-{uuid.uuid4().hex[:12]}",
        created_at=_parse_created_at(created_at),
    )
    manifest_path = data_root / "dataset-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    project.dataset_manifest = _relative(manifest_path, root)
    save_project(project, root / PROJECT_FILE)
    return manifest_path, manifest


def _parse_created_at(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise ProjectError(
            Code.PROJECT_SCHEMA_INVALID, f"created_at {value!r} 不是 RFC 3339 时间"
        ) from None
    if parsed.tzinfo is None:
        raise ProjectError(
            Code.PROJECT_SCHEMA_INVALID, f"created_at {value!r} 缺少时区"
        )
    return parsed


def check_dataset(
    root: str | Path,
    *,
    require_test: bool = False,
    min_train_per_class: int = 1,
    min_val_per_class: int = 1,
    min_test_per_class: int | None = None,
) -> dict[str, Any]:
    """按训练前/验收策略校验项目数据清单，返回报告与统计。"""
    root = Path(root)
    project = load_project(root / PROJECT_FILE)
    for label, value in (
        ("min_train_per_class", min_train_per_class),
        ("min_val_per_class", min_val_per_class),
    ):
        if not isinstance(value, int) or value < 0:
            raise ProjectError(
                Code.PROJECT_IMPORT_INVALID, f"{label} 必须是非负整数"
            )
    if min_test_per_class is None:
        min_test_per_class = 1 if require_test else 0
    if not isinstance(min_test_per_class, int) or min_test_per_class < 0:
        raise ProjectError(
            Code.PROJECT_IMPORT_INVALID, "min_test_per_class 必须是非负整数"
        )
    if require_test and min_test_per_class < 1:
        raise ProjectError(
            Code.PROJECT_IMPORT_INVALID,
            "要求独立测试集时 min_test_per_class 必须至少为 1",
        )

    if project.dataset_manifest is None:
        raise ProjectError(
            Code.PROJECT_DATASET_MISMATCH,
            "项目尚未生成数据清单，请先导入图片",
        )
    manifest_path = (root / project.dataset_manifest).resolve()
    if not manifest_path.is_file():
        raise ProjectError(
            Code.PROJECT_DATASET_MISMATCH,
            f"数据清单不存在：{project.dataset_manifest}",
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectError(
            Code.PROJECT_DATASET_MISMATCH, f"数据清单无法读取：{error}"
        ) from error

    policy: DatasetPolicy = replace(
        DEFAULT_DATASET_POLICY,
        require_test_split=require_test,
        min_train_per_class=min_train_per_class,
        min_val_per_class=min_val_per_class,
        min_test_per_class=min_test_per_class,
    )
    report = validate_dataset_manifest(
        manifest, dataset_root=manifest_path.parent, policy=policy
    )
    try:
        summary = summarize(manifest)
    except (KeyError, TypeError):
        summary = {}
    return {
        "ok": report.ok,
        "issues": report.to_dict()["issues"],
        "counts": summary,
        "manifest_path": str(manifest_path),
        "policy": {
            "require_test_split": policy.require_test_split,
            "min_train_per_class": policy.min_train_per_class,
            "min_val_per_class": policy.min_val_per_class,
            "min_test_per_class": policy.min_test_per_class,
        },
    }


def rename_class(root: str | Path, *, old: str, new: str) -> dict[str, Any]:
    """重命名类别并同步移动数据目录、重建清单。"""
    root = Path(root)
    project = load_project(root / PROJECT_FILE)
    if old not in project.classes:
        raise ProjectError(Code.PROJECT_CLASS_INVALID, f"类别 {old!r} 不在项目中")
    if new in project.classes:
        raise ProjectError(Code.PROJECT_CLASS_INVALID, f"类别 {new!r} 已存在")
    classes = [new if item == old else item for item in project.classes]
    checked = _checked_class_list(classes)

    data_root = root / "data"
    moves: list[tuple[Path, Path]] = []
    for split_dir in ("images", TEST_DIR_NAME):
        source = data_root / split_dir / old
        target = data_root / split_dir / new
        if source.exists():
            if target.exists():
                raise ProjectError(
                    Code.PROJECT_IMPORT_INVALID,
                    f"目标目录已存在：{target}",
                )
            moves.append((source, target))
    for source, target in moves:
        source.rename(target)

    project.classes = checked
    project.updated_at = _utc_now()
    save_project(project, root / PROJECT_FILE)
    manifest_path, manifest_error = _try_rebuild(root)
    return {
        "project": project.to_dict(),
        "manifest_path": None if manifest_path is None else str(manifest_path),
        "manifest_error": manifest_error,
    }


def rename_sample(root: str | Path, *, path: str, name: str) -> dict[str, Any]:
    """重命名单个样本文件（同目录），保留原扩展名并重建清单。"""
    root = Path(root)
    load_project(root / PROJECT_FILE)
    data_root = (root / "data").resolve()
    candidate = Path(path)
    resolved = (
        (data_root / candidate).resolve()
        if not candidate.is_absolute()
        else candidate.resolve()
    )
    try:
        relative = resolved.relative_to(data_root)
    except ValueError:
        raise ProjectError(
            Code.PROJECT_IMPORT_INVALID, f"样本路径不在项目数据目录内：{path}"
        ) from None
    if not resolved.is_file():
        raise ProjectError(
            Code.PROJECT_IMPORT_INVALID, f"样本不存在：{relative.as_posix()}"
        )
    cleaned = name.strip()
    if not cleaned or any(char in cleaned for char in ("/", "\\")) or cleaned in (".", ".."):
        raise ProjectError(
            Code.PROJECT_IMPORT_INVALID, f"新文件名非法：{name!r}"
        )
    suffix = resolved.suffix
    requested = Path(cleaned)
    if requested.suffix.lower() in IMAGE_SUFFIXES:
        suffix = requested.suffix
        stem_source = requested.stem
    else:
        stem_source = cleaned
    stem = _safe_stem(stem_source)
    target = resolved.parent / f"{stem}{suffix}"
    if target == resolved:
        raise ProjectError(Code.PROJECT_IMPORT_INVALID, "新文件名与原文件相同")
    if target.exists():
        raise ProjectError(
            Code.PROJECT_IMPORT_INVALID, f"目标文件已存在：{target.name}"
        )

    resolved.rename(target)
    target_relative = target.relative_to(data_root).as_posix()
    result: dict[str, Any] = {
        "old_path": relative.as_posix(),
        "new_path": target_relative,
        "manifest_path": None,
        "manifest_error": None,
    }
    try:
        manifest_path, _ = rebuild_dataset(root)
    except DatasetError as error:
        result["manifest_error"] = f"{error.code.value}: {error.message}"
    except ProjectError as error:
        result["manifest_error"] = error.message
    else:
        result["manifest_path"] = str(manifest_path)
    return result


def _checked_class_list(classes: list[str]) -> list[str]:
    from .project import _checked_classes

    return _checked_classes(classes)


def list_samples(root: str | Path) -> dict[str, Any]:
    """列出项目数据目录中的图片样本（按类别、批次、路径排序）。"""
    root = Path(root)
    project = load_project(root / PROJECT_FILE)
    data_root = root / "data"
    samples: list[dict[str, Any]] = []
    for split, base in (("train", data_root / "images"), ("test", data_root / TEST_DIR_NAME)):
        for class_id, name in enumerate(project.classes):
            class_dir = base / name
            if not class_dir.is_dir():
                continue
            for batch_dir in sorted(path for path in class_dir.iterdir() if path.is_dir()):
                for image in sorted(batch_dir.iterdir()):
                    if image.is_file() and image.suffix.lower() in IMAGE_SUFFIXES:
                        samples.append(
                            {
                                "path": image.relative_to(data_root).as_posix(),
                                "class_id": class_id,
                                "class_name": name,
                                "split": split,
                                "capture_batch": batch_dir.name,
                            }
                        )
    counts: dict[str, dict[str, int]] = {"train": {}, "test": {}}
    for sample in samples:
        bucket = counts[sample["split"]]
        bucket[sample["class_name"]] = bucket.get(sample["class_name"], 0) + 1
    return {
        "classes": project.classes,
        "dataset_manifest": project.dataset_manifest,
        "samples": samples,
        "total": len(samples),
        "counts": counts,
    }


def delete_sample(root: str | Path, *, path: str) -> dict[str, Any]:
    """删除项目内单个样本并尽力重建数据清单；越界路径与缺失文件被拒绝。"""
    root = Path(root)
    load_project(root / PROJECT_FILE)
    data_root = (root / "data").resolve()
    candidate = Path(path)
    resolved = (data_root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    try:
        relative = resolved.relative_to(data_root).as_posix()
    except ValueError:
        raise ProjectError(
            Code.PROJECT_IMPORT_INVALID, f"样本路径不在项目数据目录内：{path}"
        ) from None
    if not resolved.is_file():
        raise ProjectError(
            Code.PROJECT_IMPORT_INVALID, f"样本不存在：{relative}"
        )
    if resolved.suffix.lower() not in IMAGE_SUFFIXES:
        raise ProjectError(
            Code.PROJECT_IMPORT_INVALID, f"不是支持的图片：{relative}"
        )

    resolved.unlink()
    parent = resolved.parent
    while parent != data_root and parent.is_dir() and not any(parent.iterdir()):
        parent.rmdir()
        parent = parent.parent

    result: dict[str, Any] = {
        "deleted": relative,
        "manifest_path": None,
        "manifest_error": None,
        "summary": None,
    }
    try:
        manifest_path, manifest = rebuild_dataset(root)
    except DatasetError as error:
        result["manifest_error"] = f"{error.code.value}: {error.message}"
    except ProjectError as error:
        result["manifest_error"] = error.message
    else:
        result["manifest_path"] = str(manifest_path)
        result["summary"] = summarize(manifest)
    return result


def import_images(
    root: str | Path,
    *,
    class_name: str,
    source_dir: str | Path,
    split: str = "train",
    batch: str | None = None,
) -> ImportResult:
    """把来源目录中的图片导入项目指定类别（默认训练集）。"""
    root = Path(root)
    project = load_project(root / PROJECT_FILE)
    if class_name not in project.classes:
        raise ProjectError(
            Code.PROJECT_CLASS_INVALID,
            f"类别 {class_name!r} 不在项目类别表中：{project.classes}",
        )
    if split not in SPLITS:
        raise ProjectError(
            Code.PROJECT_IMPORT_INVALID, f"split {split!r} 必须是 train 或 test"
        )
    source = Path(source_dir)
    if not source.is_dir():
        raise ProjectError(
            Code.PROJECT_IMPORT_INVALID, f"图片来源目录不存在：{source}"
        )
    batch_name = batch or f"batch-{datetime.now():%Y%m%d-%H%M%S}"
    if not BATCH_PATTERN.match(batch_name):
        raise ProjectError(
            Code.PROJECT_IMPORT_INVALID,
            f"批次名 {batch_name!r} 只能包含字母、数字、点、下划线与连字符",
        )

    data_root = root / "data"
    base = data_root / (TEST_DIR_NAME if split == "test" else "images") / class_name
    if batch is None:
        candidate = batch_name
        index = 2
        while (base / candidate).exists():
            candidate = f"{batch_name}-{index}"
            index += 1
        batch_name = candidate
    target_dir = base / batch_name
    target_dir.mkdir(parents=True, exist_ok=True)

    result = ImportResult(batch=batch_name, split=split, target_dir=str(target_dir))
    digests = _existing_digests(data_root)
    sources = sorted(
        path
        for path in source.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )
    if not sources:
        raise ProjectError(
            Code.PROJECT_IMPORT_INVALID, f"来源目录中没有支持的图片：{source}"
        )

    for path in sources:
        try:
            digest = integrity.sha256_file(path)
        except OSError:
            result.invalid += 1
            continue
        if digest in digests:
            result.duplicates += 1
            continue

        stem = _safe_stem(path.stem)
        target = target_dir / f"{stem}.png"
        index = 2
        while target.exists():
            target = target_dir / f"{stem}-{index}.png"
            index += 1
        try:
            _write_png(path, target)
        except Exception:  # Pillow 的异常类型因解码器而异
            result.invalid += 1
            target.unlink(missing_ok=True)
            continue
        digests.add(digest)
        result.imported += 1

    manifest_path: Path | None = None
    try:
        manifest_path, manifest = rebuild_dataset(root)
    except DatasetError as error:
        result.manifest_error = f"{error.code.value}: {error.message}"
    except ProjectError as error:
        result.manifest_error = error.message
    if manifest_path is not None:
        result.manifest_path = str(manifest_path)
        result.class_counts = _counts(manifest)
    return result


@dataclass
class ImportTreeItem:
    class_name: str
    batch: str
    imported: int
    duplicates: int
    invalid: int
    manifest_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "class_name": self.class_name,
            "batch": self.batch,
            "imported": self.imported,
            "duplicates": self.duplicates,
            "invalid": self.invalid,
            "manifest_error": self.manifest_error,
        }


@dataclass
class ImportTreeResult:
    classes: int = 0
    batches: int = 0
    imported: int = 0
    duplicates: int = 0
    invalid: int = 0
    items: list[ImportTreeItem] = field(default_factory=list)
    manifest_path: str | None = None
    class_counts: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "classes": self.classes,
            "batches": self.batches,
            "imported": self.imported,
            "duplicates": self.duplicates,
            "invalid": self.invalid,
            "items": [item.to_dict() for item in self.items],
            "manifest_path": self.manifest_path,
            "class_counts": self.class_counts,
        }


def import_tree(
    root: str | Path,
    *,
    source_dir: str | Path,
    split: str = "train",
    batch: str | None = None,
) -> ImportTreeResult:
    """按 ``来源目录/<类别>/<批次目录>/*.png`` 递归批量导入。

    - 来源目录下的子目录名必须是项目类别；
    - 每个类别目录下的子目录名作为采集批次；没有子目录时整目录作为一个批次
      （使用 ``batch`` 参数或自动生成批次名）；
    - ``batch`` 非空时覆盖子目录名，所有图片导入同一批次；
    - 任一批次导入失败会抛出 ``ProjectError``（此前已导入的文件保留）。
    """
    root = Path(root)
    project = load_project(root / PROJECT_FILE)
    source = Path(source_dir)
    if not source.is_dir():
        raise ProjectError(
            Code.PROJECT_IMPORT_INVALID, f"来源目录不存在：{source}"
        )
    if split not in SPLITS:
        raise ProjectError(
            Code.PROJECT_IMPORT_INVALID, f"split {split!r} 必须是 train 或 test"
        )

    class_dirs = sorted(path for path in source.iterdir() if path.is_dir())
    if not class_dirs:
        raise ProjectError(
            Code.PROJECT_IMPORT_INVALID,
            "来源目录下没有类别子目录（应为 来源/类别/批次/*.png）",
        )

    result = ImportTreeResult(classes=len(class_dirs))
    for class_dir in class_dirs:
        if class_dir.name not in project.classes:
            raise ProjectError(
                Code.PROJECT_CLASS_INVALID,
                f"来源目录类别 {class_dir.name!r} 不在项目类别表中：{project.classes}",
            )
        batch_dirs = sorted(path for path in class_dir.iterdir() if path.is_dir())
        if batch is not None:
            targets = [(batch, batch_dir) for batch_dir in batch_dirs] or [
                (batch, class_dir)
            ]
        elif batch_dirs:
            targets = [(batch_dir.name, batch_dir) for batch_dir in batch_dirs]
        else:
            targets = [(None, class_dir)]

        for batch_name, directory in targets:
            imported = import_images(
                root,
                class_name=class_dir.name,
                source_dir=directory,
                split=split,
                batch=batch_name,
            )
            result.batches += 1
            result.imported += imported.imported
            result.duplicates += imported.duplicates
            result.invalid += imported.invalid
            result.manifest_path = imported.manifest_path or result.manifest_path
            result.class_counts = imported.class_counts or result.class_counts
            result.items.append(
                ImportTreeItem(
                    class_name=class_dir.name,
                    batch=imported.batch,
                    imported=imported.imported,
                    duplicates=imported.duplicates,
                    invalid=imported.invalid,
                    manifest_error=imported.manifest_error,
                )
            )
    return result
