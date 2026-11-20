"""项目编辑（改名、增删类别）测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.contracts.errors import Code
from backend.project.dataset import rebuild_dataset
from backend.project.project import (
    PROJECT_FILE,
    ProjectError,
    add_class,
    create_project,
    load_project,
    remove_class,
    rename_project,
    verify_project,
)
from tests.support.images import build_dataset_tree

CLASSES = ("水杯", "书本", "笔袋")
CREATED_AT = "2026-11-17T10:00:00+08:00"


def new_project(tmp_path: Path, *, with_data: bool = True) -> Path:
    root = tmp_path / "学生 项目"
    create_project(
        root,
        project_id="proj-edit-0001",
        name="编辑测试",
        classes=CLASSES,
        created_at=CREATED_AT,
    )
    if with_data:
        build_dataset_tree(
            root / "data", classes=CLASSES, train_batches=2, images_per_batch=1
        )
        rebuild_dataset(root, dataset_id="ds-edit-0001")
    return root


def test_rename_project(tmp_path: Path) -> None:
    root = new_project(tmp_path, with_data=False)
    result = rename_project(root, name="三年级一班 分类")
    assert result.project.name == "三年级一班 分类"

    reloaded = load_project(root / PROJECT_FILE)
    assert reloaded.name == "三年级一班 分类"
    assert reloaded.updated_at != CREATED_AT


def test_rename_rejects_blank_name(tmp_path: Path) -> None:
    root = new_project(tmp_path, with_data=False)
    with pytest.raises(ProjectError) as error:
        rename_project(root, name="   ")
    assert error.value.code is Code.PROJECT_SCHEMA_INVALID


def test_add_class_appends_and_reports_manifest(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    result = add_class(root, name="桌子")
    assert list(result.project.classes) == [*CLASSES, "桌子"]
    # 新类别尚无数据，清单按 T03 规则暂时无法重建。
    assert result.manifest_error is not None

    reloaded = load_project(root / PROJECT_FILE)
    assert reloaded.classes[-1] == "桌子"
    report = verify_project(root)
    assert report.has(Code.PROJECT_DATASET_MISMATCH)


def test_add_duplicate_class_is_rejected(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    with pytest.raises(ProjectError) as error:
        add_class(root, name="水杯")
    assert error.value.code is Code.PROJECT_CLASS_INVALID


def test_remove_class_with_data_requires_confirmation(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    with pytest.raises(ProjectError) as error:
        remove_class(root, name="笔袋")
    assert error.value.code is Code.PROJECT_CLASS_INVALID
    assert (root / "data" / "images" / "笔袋").is_dir()
    assert load_project(root / PROJECT_FILE).classes == list(CLASSES)


def test_remove_class_with_data_deletes_and_rebuilds(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    result = remove_class(root, name="笔袋", delete_data=True)

    assert list(result.project.classes) == ["水杯", "书本"]
    assert result.manifest_path is not None and result.manifest_error is None
    assert not (root / "data" / "images" / "笔袋").exists()
    assert not (root / "data" / "test-images" / "笔袋").exists()

    manifest = json.loads(
        (root / "data" / "dataset-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["classes"] == ["水杯", "书本"]
    assert verify_project(root).ok


def test_remove_class_without_data_rebuilds(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    add_class(root, name="桌子")
    result = remove_class(root, name="桌子")
    assert list(result.project.classes) == list(CLASSES)
    assert result.manifest_path is not None
    assert verify_project(root).ok


def test_remove_class_keeps_minimum_two(tmp_path: Path) -> None:
    root = new_project(tmp_path, with_data=False)
    remove_class(root, name="笔袋")  # 无数据，可删
    assert load_project(root / PROJECT_FILE).classes == ["水杯", "书本"]
    with pytest.raises(ProjectError) as error:
        remove_class(root, name="书本")
    assert error.value.code is Code.PROJECT_CLASS_INVALID


def test_cli_rename_add_and_remove(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from backend.project.cli import main

    root = new_project(tmp_path)

    exit_code = main(["rename", "--root", str(root), "--name", "新名字"])
    renamed = json.loads(capsys.readouterr().out)
    assert exit_code == 0 and renamed["project"]["name"] == "新名字"

    exit_code = main(["add-class", "--root", str(root), "--name", "桌子"])
    added = json.loads(capsys.readouterr().out)
    assert exit_code == 0 and added["project"]["classes"][-1] == "桌子"

    exit_code = main(["remove-class", "--root", str(root), "--name", "桌子"])
    removed = json.loads(capsys.readouterr().out)
    assert exit_code == 0 and "桌子" not in removed["project"]["classes"]

    exit_code = main(
        ["remove-class", "--root", str(root), "--name", "笔袋"]
    )
    failed = json.loads(capsys.readouterr().out)
    assert exit_code == 1 and failed["ok"] is False
