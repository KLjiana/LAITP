"""训练前数据检查测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.contracts.errors import Code
from backend.project.dataset import check_dataset, rebuild_dataset
from backend.project.project import (
    PROJECT_FILE,
    ProjectError,
    create_project,
    load_project,
    save_project,
)
from tests.support.images import build_dataset_tree

CLASSES = ("水杯", "书本", "笔袋")
CREATED_AT = "2026-11-17T10:00:00+08:00"


def new_root(tmp_path: Path, *, test_batches: int = 1) -> Path:
    root = tmp_path / "学生 项目"
    create_project(
        root,
        project_id="proj-check-0001",
        name="检查项目",
        classes=CLASSES,
        created_at=CREATED_AT,
    )
    build_dataset_tree(
        root / "data",
        classes=CLASSES,
        train_batches=2,
        images_per_batch=1,
        test_batches=test_batches,
    )
    rebuild_dataset(root, dataset_id="ds-check-0001")
    return root


def test_check_passes_on_full_dataset(tmp_path: Path) -> None:
    root = new_root(tmp_path)
    payload = check_dataset(root)
    assert payload["ok"] is True
    assert payload["issues"] == []
    assert payload["counts"]["total"] == 9
    assert payload["policy"]["require_test_split"] is False


def test_check_require_test_passes_with_test_split(tmp_path: Path) -> None:
    root = new_root(tmp_path, test_batches=1)
    payload = check_dataset(root, require_test=True)
    assert payload["ok"] is True


def test_check_require_test_fails_without_test_split(tmp_path: Path) -> None:
    root = new_root(tmp_path, test_batches=0)
    payload = check_dataset(root, require_test=True)
    assert payload["ok"] is False
    codes = {issue["code"] for issue in payload["issues"]}
    assert "DATASET_TEST_SPLIT_MISSING" in codes


def test_check_rejects_missing_manifest(tmp_path: Path) -> None:
    root = new_root(tmp_path)
    project = load_project(root / PROJECT_FILE)
    project.dataset_manifest = None
    save_project(project, root / PROJECT_FILE)
    with pytest.raises(ProjectError) as error:
        check_dataset(root)
    assert error.value.code is Code.PROJECT_DATASET_MISMATCH


def test_check_rejects_corrupted_manifest(tmp_path: Path) -> None:
    root = new_root(tmp_path)
    (root / "data" / "dataset-manifest.json").write_text("{bad json", encoding="utf-8")
    with pytest.raises(ProjectError) as error:
        check_dataset(root)
    assert error.value.code is Code.PROJECT_DATASET_MISMATCH


def test_check_detects_missing_validation_split(tmp_path: Path) -> None:
    root = new_root(tmp_path)
    manifest_path = root / "data" / "dataset-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for sample in manifest["samples"]:
        if sample["split"] == "val":
            sample["split"] = "train"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )

    payload = check_dataset(root)
    assert payload["ok"] is False
    codes = {issue["code"] for issue in payload["issues"]}
    assert "DATASET_CLASS_MISSING_IN_SPLIT" in codes


def test_cli_check_dataset(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from backend.project.cli import main

    root = new_root(tmp_path, test_batches=0)
    exit_code = main(["check-dataset", "--root", str(root)])
    passed = json.loads(capsys.readouterr().out)
    assert exit_code == 0 and passed["ok"] is True

    exit_code = main(["check-dataset", "--root", str(root), "--require-test"])
    failed = json.loads(capsys.readouterr().out)
    assert exit_code == 1 and failed["ok"] is False


def test_check_strict_min_counts_pass(tmp_path: Path) -> None:
    root = new_root(tmp_path, test_batches=1)
    payload = check_dataset(
        root,
        require_test=True,
        min_train_per_class=1,
        min_val_per_class=1,
        min_test_per_class=1,
    )
    assert payload["ok"] is True
    assert payload["policy"] == {
        "require_test_split": True,
        "min_train_per_class": 1,
        "min_val_per_class": 1,
        "min_test_per_class": 1,
    }


def test_check_strict_min_counts_fail(tmp_path: Path) -> None:
    root = new_root(tmp_path, test_batches=1)
    payload = check_dataset(
        root,
        require_test=True,
        min_test_per_class=2,
    )
    assert payload["ok"] is False
    codes = {issue["code"] for issue in payload["issues"]}
    assert "DATASET_CLASS_TOO_FEW_SAMPLES" in codes


def test_check_rejects_negative_min(tmp_path: Path) -> None:
    root = new_root(tmp_path)
    with pytest.raises(ProjectError) as error:
        check_dataset(root, min_train_per_class=-1)
    assert error.value.code is Code.PROJECT_IMPORT_INVALID


def test_cli_check_strict_flags(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from backend.project.cli import main

    root = new_root(tmp_path, test_batches=1)
    exit_code = main(
        [
            "check-dataset",
            "--root", str(root),
            "--require-test",
            "--min-train", "1",
            "--min-val", "1",
            "--min-test", "2",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1 and payload["ok"] is False
    assert payload["policy"]["min_test_per_class"] == 2

    exit_code = main(
        ["check-dataset", "--root", str(root), "--require-test", "--min-test", "1"]
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0 and payload["ok"] is True
