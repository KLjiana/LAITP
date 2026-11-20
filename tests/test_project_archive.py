"""项目归档导出/导入测试。"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from backend.project.project import create_project
from scripts.project_archive import export_project, import_project, main

CLASSES = ("水杯", "书本")


def make_project(tmp_path: Path) -> Path:
    root = tmp_path / "学生 项目"
    create_project(
        root,
        project_id="proj-archive-0001",
        name="归档项目",
        classes=CLASSES,
        created_at="2026-11-18T10:00:00+08:00",
    )
    (root / "data").mkdir(exist_ok=True)
    (root / "data" / "note.txt").write_text("hello", encoding="utf-8")
    return root


def test_export_then_import_roundtrip(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    archive = tmp_path / "导出 归档.zip"
    exported = export_project(root, archive)
    assert exported["ok"] is True
    with zipfile.ZipFile(archive) as bundle:
        assert "project.json" in bundle.namelist()
        assert "data/note.txt" in bundle.namelist()

    target = tmp_path / "恢复 项目"
    imported = import_project(archive, target)
    assert imported["ok"] is True
    original = json.loads((root / "project.json").read_text(encoding="utf-8"))
    restored = json.loads((target / "project.json").read_text(encoding="utf-8"))
    assert restored == original
    assert (target / "data" / "note.txt").read_text(encoding="utf-8") == "hello"


def test_import_rejects_non_empty_target(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    archive = tmp_path / "archive.zip"
    export_project(root, archive)
    target = tmp_path / "已有内容"
    target.mkdir()
    (target / "keep.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError):
        import_project(archive, target)


def test_import_rejects_archive_without_project(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("readme.txt", "no project")
    with pytest.raises(ValueError):
        import_project(archive, tmp_path / "bad-target")
    assert not (tmp_path / "bad-target").exists()


def test_main_reports_missing_archive(tmp_path: Path) -> None:
    exit_code = main(
        [
            "import",
            "--archive",
            str(tmp_path / "missing.zip"),
            "--target",
            str(tmp_path / "target"),
        ]
    )
    assert exit_code == 1
