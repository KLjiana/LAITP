"""``scripts/project_archive.py`` 的错误路径测试（秒级，不改生产脚本）。

现有 ``tests/test_project_archive.py`` 已覆盖函数级往返、非空目标拒绝、
缺 project.json 归档拒绝，以及 ``main()`` 导入缺失归档返回退出码 1。本文件只补
它未覆盖的 CLI 级行为：退出码与标准输出的错误 JSON；同一场景已被现有测试覆盖的
不再重复（例如“导入 ZIP 不存在”只保留现有用例）。

先读脚本确认的实现行为（与部分直觉不同）：

- 导出：项目目录不存在或目录内缺 ``project.json`` 时抛 ``FileNotFoundError``，
  退出码 1，错误 JSON 含 ``项目文件不存在`` 与期望的 project.json 路径，且不会
  生成目标 ZIP。
- 导出：目标 ZIP 已存在时脚本**不拒绝而是覆盖**（``shutil.move`` 在 Windows 上
  落为 ``copy2`` 覆盖），退出码 0；测试按实际行为断言并记录。
- 导入：归档不是 ZIP 时 ``zipfile.BadZipFile``（``File is not a zip file``），
  退出码 1，目标目录不会被创建。
- 导入：目标目录已存在且非空时在解压前拒绝（``目标目录已存在且非空``），退出码
  1，目录内原有文件保持不变。
- 导入：ZIP 缺少 ``project.json`` 时解压后校验失败，删除已恢复的目标目录并退出 1
  （``归档内缺少 project.json``）。
"""

from __future__ import annotations

import json
import zipfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

from backend.project.project import create_project
from scripts.project_archive import PROJECT_FILE, export_project
from scripts.project_archive import main as archive_main

CLASSES = ("水杯", "书本")
CREATED_AT = "2026-11-18T10:00:00+08:00"
PROJECT_ID = "proj-archive-error-0001"

Main = Callable[[Sequence[str] | None], int]


def make_project(tmp_path: Path) -> Path:
    root = tmp_path / "学生 项目"
    create_project(
        root,
        project_id=PROJECT_ID,
        name="归档项目",
        classes=CLASSES,
        created_at=CREATED_AT,
    )
    (root / "data").mkdir(exist_ok=True)
    (root / "data" / "note.txt").write_text("hello", encoding="utf-8")
    return root


def run_cli(
    main: Main,
    capsys: pytest.CaptureFixture[str],
    *arguments: str,
) -> tuple[int, dict[str, Any]]:
    exit_code = main(list(arguments))
    captured = capsys.readouterr()
    return exit_code, json.loads(captured.out)


@pytest.mark.parametrize("root_exists", [False, True], ids=["missing-dir", "dir-without-project-json"])
def test_export_missing_project_file_exits_one(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    root_exists: bool,
) -> None:
    root = tmp_path / "学生 项目"
    if root_exists:
        root.mkdir()
        (root / "readme.txt").write_text("没有 project.json", encoding="utf-8")
    output = tmp_path / "导出 归档.zip"

    exit_code, payload = run_cli(
        archive_main,
        capsys,
        "export",
        "--project",
        str(root),
        "--output",
        str(output),
    )

    assert exit_code == 1
    assert payload["ok"] is False
    assert "项目文件不存在" in payload["error"]
    assert str(root / PROJECT_FILE) in payload["error"]
    assert not output.exists()


def test_export_overwrites_existing_archive(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """实测行为：目标 ZIP 已存在时覆盖（不拒绝），退出码 0。"""
    root = make_project(tmp_path)
    archive = tmp_path / "已有 归档.zip"
    archive.write_bytes(b"stale-content")

    exit_code, payload = run_cli(
        archive_main,
        capsys,
        "export",
        "--project",
        str(root),
        "--output",
        str(archive),
    )

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["archive"] == str(archive)
    assert payload["files"] == 2
    with zipfile.ZipFile(archive) as bundle:
        assert sorted(bundle.namelist()) == ["data/note.txt", "project.json"]
    assert b"stale-content" not in archive.read_bytes()


@pytest.mark.parametrize(
    ("kind", "expected_error"),
    [
        ("not-a-zip", "not a zip"),
        ("missing-project-json", "缺少 project.json"),
    ],
    ids=["not-a-zip", "zip-without-project"],
)
def test_import_invalid_archive_exits_one_without_target(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    kind: str,
    expected_error: str,
) -> None:
    archive = tmp_path / "坏 归档.zip"
    if kind == "not-a-zip":
        archive.write_text("这不是 ZIP 文件", encoding="utf-8")
    else:
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("readme.txt", "no project")
    target = tmp_path / "恢复 目标"

    exit_code, payload = run_cli(
        archive_main,
        capsys,
        "import",
        "--archive",
        str(archive),
        "--target",
        str(target),
    )

    assert exit_code == 1
    assert payload["ok"] is False
    assert expected_error in payload["error"].lower()
    assert not target.exists()


def test_import_rejects_existing_non_empty_target(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_project(tmp_path)
    archive = tmp_path / "归档.zip"
    export_project(root, archive)
    target = tmp_path / "已有 项目"
    target.mkdir()
    keep = target / "keep.txt"
    keep.write_text("keep", encoding="utf-8")

    exit_code, payload = run_cli(
        archive_main,
        capsys,
        "import",
        "--archive",
        str(archive),
        "--target",
        str(target),
    )

    assert exit_code == 1
    assert payload["ok"] is False
    assert "目标目录已存在且非空" in payload["error"]
    assert str(target) in payload["error"]
    assert keep.read_text(encoding="utf-8") == "keep"
    assert sorted(path.name for path in target.iterdir()) == ["keep.txt"]
