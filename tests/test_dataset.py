"""数据清单构建与校验测试（T03）。"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from backend.classification.dataset import (
    DATASET_SCHEMA_NAME,
    DatasetDecodeError,
    DatasetError,
    DatasetPolicy,
    build_dataset_manifest,
    summarize,
    validate_dataset_manifest,
)
from backend.contracts import schemas
from backend.contracts.errors import Code
from tests.support.images import build_dataset_tree

CLASSES = ("水杯", "书本", "笔袋")
FIXED_TIME = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)
DATASET_ID = "ds-20261117-0001"


@pytest.fixture()
def dataset(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    root = build_dataset_tree(tmp_path / "data", classes=CLASSES)
    manifest = build_dataset_manifest(
        root, classes=CLASSES, dataset_id=DATASET_ID, created_at=FIXED_TIME
    )
    return root, manifest


def validate(
    root: Path,
    manifest: dict[str, Any],
    policy: DatasetPolicy = DatasetPolicy(),
    decoder=None,
):
    return validate_dataset_manifest(
        manifest, dataset_root=root, policy=policy, decoder=decoder
    )


def assert_code(root: Path, manifest: dict[str, Any], code: Code, policy=DatasetPolicy()):
    report = validate(root, manifest, policy)
    assert report.has(code), [i.code.value for i in report.issues]
    return report


# --------------------------------------------------------------------------- #
# 构建
# --------------------------------------------------------------------------- #


def test_static_manifest_fixture_matches_schema() -> None:
    from tests.support.fixtures import load_json

    manifest = load_json("datasets/valid-classification.json")
    assert schemas.schema_issues(DATASET_SCHEMA_NAME, manifest) == []


def test_manifest_matches_schema(dataset: tuple[Path, dict[str, Any]]) -> None:
    _, manifest = dataset
    assert schemas.schema_issues(DATASET_SCHEMA_NAME, manifest) == []


def test_build_is_deterministic(tmp_path: Path) -> None:
    root = build_dataset_tree(tmp_path / "data", classes=CLASSES)
    first = build_dataset_manifest(
        root, classes=CLASSES, dataset_id=DATASET_ID, created_at=FIXED_TIME
    )
    second = build_dataset_manifest(
        root, classes=CLASSES, dataset_id=DATASET_ID, created_at=FIXED_TIME
    )
    assert first == second


def test_each_batch_belongs_to_one_split(dataset: tuple[Path, dict[str, Any]]) -> None:
    _, manifest = dataset
    splits: dict[str, str] = {}
    for sample in manifest["samples"]:
        batch = sample["capture_batch"]
        if batch in splits:
            assert splits[batch] == sample["split"], batch
        else:
            splits[batch] = sample["split"]
    for class_id in range(len(CLASSES)):
        class_splits = {
            sample["split"]
            for sample in manifest["samples"]
            if sample["class_id"] == class_id
        }
        assert {"train", "val"} <= class_splits


def test_class_order_defines_class_ids(dataset: tuple[Path, dict[str, Any]]) -> None:
    _, manifest = dataset
    assert manifest["classes"] == list(CLASSES)
    for sample in manifest["samples"]:
        expected = CLASSES.index(sample["path"].split("/")[1])
        assert sample["class_id"] == expected


def test_summary_counts_match_samples(dataset: tuple[Path, dict[str, Any]]) -> None:
    _, manifest = dataset
    summary = summarize(manifest)
    assert summary["total"] == len(manifest["samples"])
    splits = summary["splits"]
    assert splits["train"] + splits["val"] + splits["test"] == summary["total"]
    assert all(row["train"] >= 1 and row["val"] >= 1 for row in summary["by_class"])


def test_requires_at_least_two_classes(tmp_path: Path) -> None:
    root = build_dataset_tree(tmp_path / "data", classes=("甲", "乙"))
    with pytest.raises(DatasetError) as error:
        build_dataset_manifest(root, classes=("甲",), dataset_id=DATASET_ID)
    assert error.value.code is Code.DATASET_CLASS_INVALID


def test_class_without_batch_directories_is_rejected(tmp_path: Path) -> None:
    root = build_dataset_tree(tmp_path / "data", classes=("甲", "乙"))
    flat = root / "images" / "甲" / "loose.png"
    flat.parent.mkdir(parents=True, exist_ok=True)
    flat.write_bytes(b"\x89PNG\r\n\x1a\n")
    for batch in (root / "images" / "甲").iterdir():
        if batch.is_dir():
            for image in batch.iterdir():
                image.unlink()
            batch.rmdir()
    with pytest.raises(DatasetError) as error:
        build_dataset_manifest(root, classes=("甲", "乙"), dataset_id=DATASET_ID)
    assert error.value.code is Code.DATASET_BATCH_INVALID


def test_single_batch_cannot_be_split(tmp_path: Path) -> None:
    root = build_dataset_tree(tmp_path / "data", classes=("甲", "乙"), train_batches=1)
    with pytest.raises(DatasetError) as error:
        build_dataset_manifest(root, classes=("甲", "乙"), dataset_id=DATASET_ID)
    assert error.value.code is Code.DATASET_BATCH_INVALID


# --------------------------------------------------------------------------- #
# 校验：成功路径
# --------------------------------------------------------------------------- #


def test_valid_dataset_passes(dataset: tuple[Path, dict[str, Any]]) -> None:
    root, manifest = dataset
    report = validate(root, manifest)
    assert report.ok, report.issues


def test_test_split_is_recognized(dataset: tuple[Path, dict[str, Any]]) -> None:
    root, manifest = dataset
    policy = DatasetPolicy(require_test_split=True, min_test_per_class=1)
    report = validate(root, manifest, policy)
    assert report.ok, report.issues
    assert summarize(manifest)["splits"]["test"] == len(CLASSES)


# --------------------------------------------------------------------------- #
# 校验：文件与内容
# --------------------------------------------------------------------------- #


def test_missing_file_is_rejected(dataset: tuple[Path, dict[str, Any]]) -> None:
    root, manifest = dataset
    (root / manifest["samples"][0]["path"]).unlink()
    assert_code(root, manifest, Code.DATASET_FILE_MISSING)


def test_digest_mismatch_is_rejected(dataset: tuple[Path, dict[str, Any]]) -> None:
    root, manifest = dataset
    path = root / manifest["samples"][0]["path"]
    path.write_bytes(path.read_bytes() + b"\x00")
    assert_code(root, manifest, Code.DATASET_DIGEST_MISMATCH)


def test_duplicate_content_is_rejected(dataset: tuple[Path, dict[str, Any]]) -> None:
    root, manifest = dataset
    source = manifest["samples"][0]
    copied = copy.deepcopy(source)
    copied["path"] = "images/副本.png"
    target = root / copied["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((root / source["path"]).read_bytes())
    manifest["samples"].append(copied)
    assert_code(root, manifest, Code.DATASET_CONTENT_DUPLICATE)


def test_duplicate_path_is_rejected(dataset: tuple[Path, dict[str, Any]]) -> None:
    root, manifest = dataset
    manifest["samples"].append(copy.deepcopy(manifest["samples"][0]))
    duplicate_index = len(manifest["samples"]) - 1
    report = assert_code(root, manifest, Code.DATASET_SAMPLE_DUPLICATE)
    assert any(
        issue.location == f"samples[{duplicate_index}].path" for issue in report.issues
    )


def test_undecodable_image_is_rejected(dataset: tuple[Path, dict[str, Any]]) -> None:
    root, manifest = dataset
    sample = manifest["samples"][0]
    path = root / sample["path"]
    path.write_bytes(b"not an image")
    import hashlib

    sample["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    assert_code(root, manifest, Code.DATASET_IMAGE_UNDECODABLE)


def test_decoder_can_be_injected(dataset: tuple[Path, dict[str, Any]]) -> None:
    root, manifest = dataset

    def reject(_: Path) -> None:
        raise DatasetDecodeError("模拟解码失败")

    report = validate(root, manifest, decoder=reject)
    assert report.has(Code.DATASET_IMAGE_UNDECODABLE)


def test_decode_can_be_disabled(dataset: tuple[Path, dict[str, Any]]) -> None:
    root, manifest = dataset
    sample = manifest["samples"][0]
    path = root / sample["path"]
    path.write_bytes(b"not an image")
    import hashlib

    sample["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    report = validate(root, manifest, DatasetPolicy(decode_images=False))
    assert report.ok, report.issues


# --------------------------------------------------------------------------- #
# 校验：划分与类别
# --------------------------------------------------------------------------- #


def test_batch_must_not_span_splits(dataset: tuple[Path, dict[str, Any]]) -> None:
    root, manifest = dataset
    val_sample = next(s for s in manifest["samples"] if s["split"] == "val")
    val_sample["split"] = "train"
    assert_code(root, manifest, Code.DATASET_BATCH_MIXED_SPLITS)


def test_same_batch_name_across_classes_is_independent(
    dataset: tuple[Path, dict[str, Any]],
) -> None:
    """不同类别的同名批次是不同采集批次，不应互相触发批次泄漏。"""
    root, manifest = dataset
    class_one = [s for s in manifest["samples"] if s["class_id"] == 1]
    train_batch = sorted(
        {s["capture_batch"] for s in class_one if s["split"] == "train"}
    )[0]
    val_batch = next(s["capture_batch"] for s in class_one if s["split"] == "val")
    for sample in class_one:
        if sample["capture_batch"] == train_batch:
            sample["split"] = "val"
        elif sample["capture_batch"] == val_batch:
            sample["split"] = "train"

    report = validate(root, manifest)
    assert not report.has(Code.DATASET_BATCH_MIXED_SPLITS), report.issues
    assert report.ok, report.issues
    same_name = [
        s
        for s in manifest["samples"]
        if s["class_id"] == 0 and s["capture_batch"] == train_batch
    ]
    assert same_name and all(s["split"] == "train" for s in same_name)


def test_each_class_needs_validation_samples(dataset: tuple[Path, dict[str, Any]]) -> None:
    root, manifest = dataset
    val_batches = {
        sample["capture_batch"]
        for sample in manifest["samples"]
        if sample["split"] == "val" and sample["class_id"] == 0
    }
    for sample in manifest["samples"]:
        if sample["capture_batch"] in val_batches:
            sample["split"] = "train"
    assert_code(root, manifest, Code.DATASET_CLASS_MISSING_IN_SPLIT)


def test_test_split_can_be_required(dataset: tuple[Path, dict[str, Any]]) -> None:
    root, manifest = dataset
    manifest["samples"] = [s for s in manifest["samples"] if s["split"] != "test"]
    report = validate(root, manifest, DatasetPolicy(require_test_split=True))
    assert report.has(Code.DATASET_TEST_SPLIT_MISSING)


def test_minimum_samples_per_class_is_enforced(dataset: tuple[Path, dict[str, Any]]) -> None:
    root, manifest = dataset
    report = validate(root, manifest, DatasetPolicy(min_train_per_class=99))
    assert report.has(Code.DATASET_CLASS_TOO_FEW_SAMPLES)


def test_class_id_out_of_range_is_rejected(dataset: tuple[Path, dict[str, Any]]) -> None:
    root, manifest = dataset
    manifest["samples"][0]["class_id"] = 9
    assert_code(root, manifest, Code.DATASET_CLASS_ID_INVALID)


def test_traversal_path_is_rejected(dataset: tuple[Path, dict[str, Any]]) -> None:
    root, manifest = dataset
    manifest["samples"][0]["path"] = "../outside.png"
    assert_code(root, manifest, Code.DATASET_SAMPLE_PATH_INVALID)


# --------------------------------------------------------------------------- #
# 版本与结构
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("version", "code"),
    [
        ("2.0", Code.DATASET_VERSION_UNSUPPORTED_MAJOR),
        ("1.1", Code.DATASET_VERSION_UNSUPPORTED_MINOR),
    ],
)
def test_unsupported_dataset_versions(
    dataset: tuple[Path, dict[str, Any]], version: str, code: Code
) -> None:
    root, manifest = dataset
    manifest["dataset_version"] = version
    assert_code(root, manifest, code)


def test_duplicate_classes_are_rejected(dataset: tuple[Path, dict[str, Any]]) -> None:
    root, manifest = dataset
    manifest["classes"][1] = manifest["classes"][0]
    report = validate(root, manifest)
    assert report.has(Code.DATASET_SCHEMA_INVALID)


# --------------------------------------------------------------------------- #
# 命令行
# --------------------------------------------------------------------------- #


def test_cli_build_and_validate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from backend.classification.dataset import main

    root = build_dataset_tree(tmp_path / "data", classes=CLASSES)
    output = root / "dataset-manifest.json"
    exit_code = main(
        [
            "build",
            "--root",
            str(root),
            "--classes",
            *CLASSES,
            "--dataset-id",
            DATASET_ID,
            "--output",
            str(output),
        ]
    )
    built = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert built["ok"] is True
    assert built["counts"]["total"] == len(json.loads(output.read_text(encoding="utf-8"))["samples"])

    exit_code = main(["validate", str(output), "--root", str(root), "--require-test"])
    validated = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert validated["ok"] is True


def test_cli_reports_validation_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from backend.classification.dataset import main

    root = build_dataset_tree(tmp_path / "data", classes=CLASSES)
    output = root / "dataset-manifest.json"
    main(
        [
            "build",
            "--root",
            str(root),
            "--classes",
            *CLASSES,
            "--dataset-id",
            DATASET_ID,
            "--output",
            str(output),
        ]
    )
    capsys.readouterr()
    manifest = json.loads(output.read_text(encoding="utf-8"))
    (root / manifest["samples"][0]["path"]).unlink()
    exit_code = main(["validate", str(output), "--root", str(root)])
    result = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert result["issues"][0]["code"] == "DATASET_FILE_MISSING"
