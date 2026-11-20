"""类别改名与样本重命名测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.contracts.errors import Code
from backend.project.dataset import (
    rebuild_dataset,
    rename_class,
    rename_sample,
)
from backend.project.project import (
    PROJECT_FILE,
    ProjectError,
    create_project,
    load_project,
    verify_project,
)
from tests.support.images import build_dataset_tree

CLASSES = ("水杯", "书本", "笔袋")
CREATED_AT = "2026-11-17T10:00:00+08:00"


def new_project(tmp_path: Path) -> Path:
    root = tmp_path / "学生 项目"
    create_project(
        root,
        project_id="proj-rename-0001",
        name="改名测试",
        classes=CLASSES,
        created_at=CREATED_AT,
    )
    build_dataset_tree(
        root / "data", classes=CLASSES, train_batches=2, images_per_batch=1
    )
    rebuild_dataset(root, dataset_id="ds-rename-0001")
    return root


def test_rename_class_moves_data_and_keeps_order(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    result = rename_class(root, old="书本", new="课本")

    assert result["project"]["classes"] == ["水杯", "课本", "笔袋"]
    assert result["manifest_path"] is not None and result["manifest_error"] is None
    assert (root / "data" / "images" / "课本").is_dir()
    assert not (root / "data" / "images" / "书本").exists()
    assert (root / "data" / "test-images" / "课本").is_dir()

    manifest = json.loads(
        (root / "data" / "dataset-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["classes"] == ["水杯", "课本", "笔袋"]
    assert any("课本" in sample["path"] for sample in manifest["samples"])
    assert verify_project(root).ok


def test_rename_class_rejects_conflict(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    with pytest.raises(ProjectError) as error:
        rename_class(root, old="书本", new="水杯")
    assert error.value.code is Code.PROJECT_CLASS_INVALID


def test_rename_class_rejects_missing_class(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    with pytest.raises(ProjectError) as error:
        rename_class(root, old="桌子", new="椅子")
    assert error.value.code is Code.PROJECT_CLASS_INVALID


def test_rename_class_without_data(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    from backend.project.project import add_class

    add_class(root, name="桌子")
    result = rename_class(root, old="桌子", new="椅子")
    assert "椅子" in result["project"]["classes"]
    # 新类别仍无数据，清单无法重建；改名本身成功。
    assert result["manifest_path"] is None
    assert result["manifest_error"] is not None
    assert load_project(root / PROJECT_FILE).classes[-1] == "椅子"


def test_rename_sample_moves_file_and_updates_manifest(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    payload = json.loads(
        (root / "data" / "dataset-manifest.json").read_text(encoding="utf-8")
    )
    target = payload["samples"][0]["path"]

    result = rename_sample(root, path=target, name="课堂样本")
    assert result["manifest_path"] is not None
    assert result["new_path"].endswith("课堂样本.png")
    assert result["new_path"] != target
    assert (root / "data" / result["new_path"]).is_file()
    assert not (root / "data" / target).exists()

    manifest = json.loads(
        (root / "data" / "dataset-manifest.json").read_text(encoding="utf-8")
    )
    paths = [sample["path"] for sample in manifest["samples"]]
    assert result["new_path"] in paths
    assert verify_project(root).ok


def test_rename_sample_rejects_conflict(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    payload = json.loads(
        (root / "data" / "dataset-manifest.json").read_text(encoding="utf-8")
    )
    first, second = payload["samples"][0]["path"], payload["samples"][1]["path"]
    existing = Path(second).stem
    with pytest.raises(ProjectError) as error:
        rename_sample(root, path=first, name=existing)
    assert error.value.code is Code.PROJECT_IMPORT_INVALID


def test_rename_sample_rejects_outside_path(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    with pytest.raises(ProjectError) as error:
        rename_sample(root, path="../project.json", name="x")
    assert error.value.code is Code.PROJECT_IMPORT_INVALID


def test_rename_sample_rejects_missing_file(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    with pytest.raises(ProjectError) as error:
        rename_sample(root, path="images/水杯/batch-1/nope.png", name="x")
    assert error.value.code is Code.PROJECT_IMPORT_INVALID


def test_cli_rename_class_and_sample(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from backend.project.cli import main

    root = new_project(tmp_path)
    exit_code = main(
        ["rename-class", "--root", str(root), "--old", "笔袋", "--new", "文具袋"]
    )
    renamed = json.loads(capsys.readouterr().out)
    assert exit_code == 0 and "文具袋" in renamed["project"]["classes"]

    payload = json.loads(
        (root / "data" / "dataset-manifest.json").read_text(encoding="utf-8")
    )
    target = payload["samples"][0]["path"]
    exit_code = main(
        [
            "rename-sample",
            "--root",
            str(root),
            "--path",
            target,
            "--name",
            "cli样本",
        ]
    )
    sample = json.loads(capsys.readouterr().out)
    assert exit_code == 0 and sample["new_path"].endswith("cli样本.png")
