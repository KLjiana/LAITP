"""分类数据清单：构建、按采集批次划分与校验（T03）。

数据布局（相对数据集根目录）::

    images/<类别>/<采集批次>/<图片>        # 训练与验证
    test-images/<类别>/<采集批次>/<图片>   # 独立测试集，冻结后不参与调参
    dataset-manifest.json                  # 本模块生成的数据清单

类别表由调用方显式给出顺序，不依赖目录遍历顺序；训练/验证按采集批次
稳定划分，同一批次只能落在一个划分中，避免相邻连拍泄漏到验证集。
真实图片尚未提供时，测试使用构造样例验证格式与规则，不能据此声称
真实分类效果或课堂可行性已通过。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from PIL import Image, UnidentifiedImageError

from ..console import emit_json
from ..contracts import integrity, paths, schemas
from ..contracts.errors import Code, Issue, Report, Stage
from ..contracts.runtime_spec import VersionSyntaxError, parse_version

DATASET_SCHEMA_NAME = "dataset-manifest.schema.json"
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".bmp", ".webp"})
TRAIN, VAL, TEST = "train", "val", "test"
SPLITS = (TRAIN, VAL, TEST)
TEST_DIR_NAME = "test-images"
BATCH_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class DatasetError(Exception):
    """无法构建数据清单。``code`` 是稳定错误码。"""

    def __init__(self, code: Code, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class DatasetDecodeError(Exception):
    """图片无法解码。"""


@dataclass(frozen=True)
class DatasetSample:
    path: str
    sha256: str
    class_id: int
    capture_batch: str
    split: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "class_id": self.class_id,
            "capture_batch": self.capture_batch,
            "split": self.split,
        }


@dataclass(frozen=True)
class DatasetPolicy:
    """校验策略。默认值用于开发数据；正式验收按计划第 4 节加严。"""

    dataset_major: int = 1
    dataset_minor: int = 0
    require_test_split: bool = False
    min_train_per_class: int = 1
    min_val_per_class: int = 1
    min_test_per_class: int = 0
    decode_images: bool = True


DEFAULT_DATASET_POLICY = DatasetPolicy()


# --------------------------------------------------------------------------- #
# 构建
# --------------------------------------------------------------------------- #


def _checked_classes(classes: Sequence[str]) -> list[str]:
    if len(classes) < 2:
        raise DatasetError(Code.DATASET_CLASS_INVALID, "至少需要 2 个类别")
    result: list[str] = []
    seen: set[str] = set()
    for name in classes:
        if not isinstance(name, str) or not name.strip():
            raise DatasetError(Code.DATASET_CLASS_INVALID, f"类别名 {name!r} 不能为空")
        reason = paths.check_rel_path(name)
        if reason is not None:
            raise DatasetError(
                Code.DATASET_CLASS_INVALID,
                f"类别名 {name!r} 不能用作目录名：{reason}",
            )
        if name in seen:
            raise DatasetError(Code.DATASET_CLASS_INVALID, f"类别 {name!r} 重复")
        seen.add(name)
        result.append(name)
    return result


def _batch_files(class_dir: Path) -> dict[str, list[Path]]:
    """读取 ``<类别>/<采集批次>/<图片>``。缺少批次目录时拒绝，避免无法按批次划分。"""
    if not class_dir.is_dir():
        raise DatasetError(Code.DATASET_EMPTY_CLASS, f"缺少类别目录 {class_dir}")
    batches: dict[str, list[Path]] = {}
    for batch_dir in sorted(path for path in class_dir.iterdir() if path.is_dir()):
        if not BATCH_PATTERN.match(batch_dir.name):
            raise DatasetError(
                Code.DATASET_BATCH_INVALID,
                f"采集批次名 {batch_dir.name!r} 只能包含字母、数字、点、下划线和连字符",
            )
        images = sorted(
            path
            for path in batch_dir.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
        )
        if not images:
            raise DatasetError(
                Code.DATASET_BATCH_INVALID, f"采集批次 {batch_dir} 中没有图片文件"
            )
        batches[batch_dir.name] = images
    if not batches:
        raise DatasetError(
            Code.DATASET_BATCH_INVALID,
            f"类别目录 {class_dir} 下没有采集批次子目录；请按 <类别>/<采集批次>/<图片> 组织数据",
        )
    return batches


def _choose_val_batches(
    batches: Sequence[str], class_id: int, val_ratio: float, seed: str
) -> set[str]:
    """按稳定哈希选取验证批次，保证每类至少 1 个训练批次和 1 个验证批次。"""
    if len(batches) < 2:
        raise DatasetError(
            Code.DATASET_BATCH_INVALID,
            f"类别 {class_id} 只有 {len(batches)} 个采集批次，至少需要 2 个才能划分训练/验证",
        )
    ranked = sorted(
        batches,
        key=lambda batch: hashlib.sha256(
            f"{seed}:{class_id}:{batch}".encode("utf-8")
        ).hexdigest(),
    )
    count = max(1, round(len(ranked) * val_ratio))
    count = min(count, len(ranked) - 1)
    return set(ranked[:count])


def _timestamp(value: datetime | None) -> str:
    moment = value if value is not None else datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise DatasetError(Code.DATASET_CLASS_INVALID, "created_at 必须带时区")
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _sample(path: Path, root: Path, class_id: int, batch: str, split: str) -> DatasetSample:
    return DatasetSample(
        path=path.relative_to(root).as_posix(),
        sha256=integrity.sha256_file(path),
        class_id=class_id,
        capture_batch=batch,
        split=split,
    )


def build_dataset_manifest(
    dataset_root: str | Path,
    *,
    classes: Sequence[str],
    dataset_id: str,
    dataset_version: str = "1.0",
    val_ratio: float = 0.2,
    seed: str = "laitp-split-v1",
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """扫描数据集目录并生成数据清单。

    训练/验证取自 ``images/``，测试取自 ``test-images/``（存在时）。输出稳定：
    相同目录内容、类别顺序和种子产生相同划分。
    """
    root = Path(dataset_root)
    names = _checked_classes(classes)
    if not 0 < val_ratio < 1:
        raise DatasetError(Code.DATASET_BATCH_INVALID, "val_ratio 必须在 (0, 1) 之间")

    samples: list[DatasetSample] = []
    for class_id, name in enumerate(names):
        batches = _batch_files(root / "images" / name)
        val_batches = _choose_val_batches(sorted(batches), class_id, val_ratio, seed)
        for batch, images in batches.items():
            split = VAL if batch in val_batches else TRAIN
            for image in images:
                samples.append(_sample(image, root, class_id, batch, split))

    test_root = root / TEST_DIR_NAME
    if test_root.is_dir():
        for class_id, name in enumerate(names):
            batches = _batch_files(test_root / name)
            for batch, images in batches.items():
                for image in images:
                    samples.append(_sample(image, root, class_id, batch, TEST))

    samples.sort(key=lambda item: (item.class_id, item.capture_batch, item.path))
    return {
        "dataset_version": dataset_version,
        "dataset_id": dataset_id,
        "task": "image_classification",
        "created_at": _timestamp(created_at),
        "classes": names,
        "samples": [sample.to_dict() for sample in samples],
    }


def summarize(manifest: dict[str, Any]) -> dict[str, Any]:
    """按划分与类别统计样本数，供命令行与训练记录使用。"""
    classes: list[str] = manifest["classes"]
    counts = {split: [0] * len(classes) for split in SPLITS}
    for sample in manifest["samples"]:
        class_id = sample["class_id"]
        split = sample["split"]
        if 0 <= class_id < len(classes) and split in counts:
            counts[split][class_id] += 1
    by_class = [
        {
            "class_id": class_id,
            "name": name,
            "train": counts[TRAIN][class_id],
            "val": counts[VAL][class_id],
            "test": counts[TEST][class_id],
        }
        for class_id, name in enumerate(classes)
    ]
    return {
        "total": len(manifest["samples"]),
        "splits": {split: sum(counts[split]) for split in SPLITS},
        "by_class": by_class,
    }


# --------------------------------------------------------------------------- #
# 校验
# --------------------------------------------------------------------------- #


def decode_image(path: Path) -> None:
    """完整解码图片，确认不是损坏或伪装文件。"""
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise DatasetDecodeError(f"无法解码图片：{error}") from error


def _check_version(report: Report, version_text: str, policy: DatasetPolicy) -> bool:
    try:
        major, minor, _ = parse_version(version_text)
    except VersionSyntaxError:
        report.add(
            Code.DATASET_SCHEMA_INVALID,
            Stage.SCHEMA,
            "dataset_version",
            f"数据清单版本 {version_text!r} 不符合 major.minor 格式",
        )
        return False
    if major != policy.dataset_major:
        report.add(
            Code.DATASET_VERSION_UNSUPPORTED_MAJOR,
            Stage.SCHEMA,
            "dataset_version",
            f"数据清单主版本 {major} 不受支持（当前仅支持 {policy.dataset_major}.x）",
        )
        return False
    if minor > policy.dataset_minor:
        report.add(
            Code.DATASET_VERSION_UNSUPPORTED_MINOR,
            Stage.SCHEMA,
            "dataset_version",
            f"数据清单次版本 {version_text} 高于当前支持的 "
            f"{policy.dataset_major}.{policy.dataset_minor}",
        )
        return False
    return True


def validate_dataset_manifest(
    manifest: Any,
    *,
    dataset_root: str | Path,
    policy: DatasetPolicy = DEFAULT_DATASET_POLICY,
    decoder: Callable[[Path], None] | None = None,
) -> Report:
    """校验数据清单的结构、完整性、类别覆盖与批次划分。"""
    report = Report()
    structure = schemas.schema_issues(
        DATASET_SCHEMA_NAME,
        manifest,
        code=Code.DATASET_SCHEMA_INVALID,
        stage=Stage.SCHEMA,
    )
    if structure:
        report.extend(structure)
        return report

    if not _check_version(report, manifest["dataset_version"], policy):
        return report

    root = Path(dataset_root)
    classes: list[str] = manifest["classes"]
    samples: list[dict[str, Any]] = manifest["samples"]
    decode = decoder if decoder is not None else (decode_image if policy.decode_images else None)

    seen_paths: dict[str, int] = {}
    seen_digests: dict[str, int] = {}
    # 批次身份是（类别, 批次）：不同类别的同名批次是不同采集批次。
    batch_splits: dict[tuple[int, str], tuple[str, int]] = {}
    counts = {split: [0] * len(classes) for split in SPLITS}

    for index, sample in enumerate(samples):
        location = f"samples[{index}]"
        rel = sample["path"]
        reason = paths.check_rel_path(rel)
        if reason is not None:
            report.add(
                Code.DATASET_SAMPLE_PATH_INVALID,
                Stage.PATHS,
                f"{location}.path",
                f"{rel!r}：{reason}",
            )
            continue
        if rel in seen_paths:
            report.add(
                Code.DATASET_SAMPLE_DUPLICATE,
                Stage.PATHS,
                f"{location}.path",
                f"样本路径 {rel!r} 与 samples[{seen_paths[rel]}] 重复",
            )
        else:
            seen_paths[rel] = index

        class_id = sample["class_id"]
        if not 0 <= class_id < len(classes):
            report.add(
                Code.DATASET_CLASS_ID_INVALID,
                Stage.LABELS,
                f"{location}.class_id",
                f"类别 ID {class_id} 超出类别表范围 0..{len(classes) - 1}",
            )
            continue

        split = sample["split"]
        counts[split][class_id] += 1

        batch = sample["capture_batch"]
        batch_key = (class_id, batch)
        previous = batch_splits.get(batch_key)
        if previous is None:
            batch_splits[batch_key] = (split, index)
        elif previous[0] != split:
            report.add(
                Code.DATASET_BATCH_MIXED_SPLITS,
                Stage.SEMANTICS,
                f"{location}.split",
                f"类别 {classes[class_id]!r} 的采集批次 {batch!r} 同时出现在 "
                f"{previous[0]}（samples[{previous[1]}]）和 {split}，"
                "会把相邻连拍泄漏到验证集",
            )

        digest = sample["sha256"]
        if digest in seen_digests:
            report.add(
                Code.DATASET_CONTENT_DUPLICATE,
                Stage.SEMANTICS,
                f"{location}.sha256",
                f"与 samples[{seen_digests[digest]}] 内容相同（摘要 {digest}），"
                "同一图片不得重复计入数据集或跨越划分",
            )
        else:
            seen_digests[digest] = index

        target = paths.resolve_in_package(root, rel)
        if target is None:
            report.add(
                Code.DATASET_SAMPLE_PATH_INVALID,
                Stage.PATHS,
                f"{location}.path",
                f"样本 {rel!r} 解析后位于数据集目录之外（疑似符号链接）",
            )
            continue
        if not target.is_file():
            report.add(
                Code.DATASET_FILE_MISSING,
                Stage.INTEGRITY,
                f"{location}.path",
                f"样本文件 {rel!r} 不存在",
            )
            continue
        try:
            actual = integrity.sha256_file(target)
        except OSError as error:
            report.add(
                Code.DATASET_FILE_UNREADABLE,
                Stage.INTEGRITY,
                f"{location}.path",
                f"无法读取 {rel!r}：{error.strerror or error}",
            )
            continue
        if actual != digest:
            report.add(
                Code.DATASET_DIGEST_MISMATCH,
                Stage.INTEGRITY,
                f"{location}.sha256",
                f"文件 {rel!r} 实际摘要为 {actual}，与清单不一致",
            )
            continue
        if decode is not None:
            try:
                decode(target)
            except (DatasetDecodeError, OSError) as error:
                report.add(
                    Code.DATASET_IMAGE_UNDECODABLE,
                    Stage.INTEGRITY,
                    f"{location}.path",
                    f"样本 {rel!r} 无法解码：{error}",
                )

    _check_coverage(report, classes, counts, policy)
    return report


def _check_coverage(
    report: Report,
    classes: Sequence[str],
    counts: dict[str, list[int]],
    policy: DatasetPolicy,
) -> None:
    requirements = {TRAIN: policy.min_train_per_class, VAL: policy.min_val_per_class}
    for split, minimum in requirements.items():
        if minimum <= 0:
            # 明确不要求该划分（例如评估时只提供冻结的测试清单）。
            continue
        for class_id, name in enumerate(classes):
            present = counts[split][class_id]
            if present == 0:
                report.add(
                    Code.DATASET_CLASS_MISSING_IN_SPLIT,
                    Stage.SEMANTICS,
                    f"classes[{class_id}]",
                    f"类别 {name!r} 在 {split} 划分中没有样本",
                )
            elif present < minimum:
                report.add(
                    Code.DATASET_CLASS_TOO_FEW_SAMPLES,
                    Stage.SEMANTICS,
                    f"classes[{class_id}]",
                    f"类别 {name!r} 在 {split} 划分只有 {present} 张，至少需要 {minimum} 张",
                )

    test_total = sum(counts[TEST])
    if policy.require_test_split and test_total == 0:
        report.add(
            Code.DATASET_TEST_SPLIT_MISSING,
            Stage.SEMANTICS,
            "samples",
            "正式验收需要独立测试集（test-images/），当前清单没有 test 样本",
        )
        return
    if test_total == 0:
        return
    for class_id, name in enumerate(classes):
        present = counts[TEST][class_id]
        if present == 0:
            report.add(
                Code.DATASET_CLASS_MISSING_IN_SPLIT,
                Stage.SEMANTICS,
                f"classes[{class_id}]",
                f"类别 {name!r} 在 test 划分中没有样本",
            )
        elif present < policy.min_test_per_class:
            report.add(
                Code.DATASET_CLASS_TOO_FEW_SAMPLES,
                Stage.SEMANTICS,
                f"classes[{class_id}]",
                f"类别 {name!r} 在 test 划分只有 {present} 张，至少需要 {policy.min_test_per_class} 张",
            )


# --------------------------------------------------------------------------- #
# 命令行
# --------------------------------------------------------------------------- #


def _load_manifest(path: Path) -> tuple[Any, Report | None]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as error:
        return None, Report(
            [
                Issue(
                    Code.DATASET_JSON_INVALID,
                    Stage.SCHEMA,
                    str(path),
                    f"无法读取数据清单：{error.strerror or error}",
                )
            ]
        )
    try:
        return json.loads(text), None
    except json.JSONDecodeError as error:
        return None, Report(
            [
                Issue(
                    Code.DATASET_JSON_INVALID,
                    Stage.SCHEMA,
                    str(path),
                    f"JSON 解析失败：第 {error.lineno} 行第 {error.colno} 列：{error.msg}",
                )
            ]
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m backend.classification.dataset",
        description="LAITP 分类数据清单构建与校验（T03）",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="扫描数据目录并生成清单")
    build.add_argument("--root", required=True, help="数据集根目录")
    build.add_argument("--classes", nargs="+", required=True, help="有序类别名，顺序即类别 ID")
    build.add_argument("--dataset-id", required=True)
    build.add_argument("--output", required=True, help="清单输出路径")
    build.add_argument("--val-ratio", type=float, default=0.2)
    build.add_argument("--seed", default="laitp-split-v1")

    validate = subparsers.add_parser("validate", help="校验数据清单")
    validate.add_argument("manifest", help="dataset-manifest.json 路径")
    validate.add_argument("--root", required=True, help="数据集根目录")
    validate.add_argument("--require-test", action="store_true")
    validate.add_argument("--min-train", type=int, default=1)
    validate.add_argument("--min-val", type=int, default=1)
    validate.add_argument("--min-test", type=int, default=0)
    validate.add_argument("--no-decode", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "build":
        try:
            manifest = build_dataset_manifest(
                args.root,
                classes=args.classes,
                dataset_id=args.dataset_id,
                val_ratio=args.val_ratio,
                seed=args.seed,
            )
        except DatasetError as error:
            report = Report(
                [Issue(error.code, Stage.SEMANTICS, "$", error.message)]
            )
            emit_json({"ok": False, **report.to_dict()})
            return 1
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        emit_json(
            {
                "ok": True,
                "manifest_path": str(output),
                "dataset_id": manifest["dataset_id"],
                "counts": summarize(manifest),
            }
        )
        return 0

    data, failure = _load_manifest(Path(args.manifest))
    if failure is not None:
        emit_json({"ok": False, **failure.to_dict()})
        return 1
    policy = DatasetPolicy(
        require_test_split=args.require_test,
        min_train_per_class=args.min_train,
        min_val_per_class=args.min_val,
        min_test_per_class=args.min_test,
        decode_images=not args.no_decode,
    )
    report = validate_dataset_manifest(data, dataset_root=args.root, policy=policy)
    counts = summarize(data) if isinstance(data, dict) and "samples" in data else None
    emit_json({"ok": report.ok, "counts": counts, **report.to_dict()})
    return 0 if report.ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
