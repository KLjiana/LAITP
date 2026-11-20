"""数据体检/历史汇总 CLI 的错误路径测试（秒级，不训练、不改生产脚本）。

覆盖离线现场常见异常：项目文件缺失或损坏、图片目录缺失、输出路径不可写、
``runs/`` 缺失等。测试直接调用两个脚本的 ``main()``：其 ``__main__`` 均为
``raise SystemExit(main())``，因此返回值就是进程退出码；标准输出由
``backend.console.emit_json`` 写成 UTF-8 JSON，用 ``capsys`` 读取后解析。

实现行为记录（先读脚本确认，与部分直觉不同）：

- ``dataset_report.py``：``data/`` 整体缺失，或 ``data/`` 下 ``images/`` 与
  ``test-images/`` 都不存在时，抛 ``REPORT_IMAGE_DIR_MISSING``、退出码 1，不生成
  报告；只有 ``data/images/`` 已存在但其中没有图片时，报告仍生成、退出码 0，
  数据风险只写入报告和 ``warnings`` 计数（见
  ``test_dataset_report_empty_images_dir_still_generates_report``）。
- ``dataset_report.py``：输出路径不可写（父路径是普通文件，或目标本身是已存在
  目录）时抛 ``REPORT_WRITE_FAILED``、退出码 1。
- ``batch_history_export.py``：``runs/`` 不存在不是错误，``ok`` 仍为 true、
  ``runs`` 为空并在 ``warnings`` 中提示；输出路径不可写时抛
  ``BATCH_HISTORY_WRITE_FAILED``、退出码 1。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

from backend.project.project import create_project
from scripts.batch_history_export import main as batch_history_main
from scripts.dataset_report import main as dataset_report_main

CLASSES = ("水杯", "书本")
CREATED_AT = "2026-11-17T10:00:00+08:00"
PROJECT_ID = "proj-cli-error-0001"

Main = Callable[[Sequence[str] | None], int]


def make_project(tmp_path: Path, name: str = "异常路径 项目") -> Path:
    """创建只含 project.json 的项目，用于制造缺失目录/不可写输出等异常。"""
    root = tmp_path / name
    create_project(
        root,
        project_id=PROJECT_ID,
        name=name,
        classes=CLASSES,
        created_at=CREATED_AT,
    )
    return root


def run_cli(
    main: Main,
    capsys: pytest.CaptureFixture[str],
    *arguments: str,
) -> tuple[int, dict[str, Any]]:
    exit_code = main(list(arguments))
    captured = capsys.readouterr()
    return exit_code, json.loads(captured.out)


# ---------------------------------------------------------------------------
# dataset_report.py
# ---------------------------------------------------------------------------


def test_dataset_report_missing_project_exits_one_with_error_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "不存在 项目" / "project.json"
    report = tmp_path / "不应生成.md"

    exit_code, payload = run_cli(
        dataset_report_main,
        capsys,
        "--project",
        str(missing),
        "--output",
        str(report),
    )

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["code"] == "PROJECT_NOT_FOUND"
    assert payload["project"] == str(missing)
    assert payload["error"]
    assert "不存在" in payload["error"]
    assert not report.exists()


def test_dataset_report_corrupt_project_json_exits_one_with_error_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "损坏 项目"
    root.mkdir()
    project_file = root / "project.json"
    project_file.write_text('{"project_id": "proj-bad", "classes": [', encoding="utf-8")
    report = tmp_path / "不应生成.md"

    exit_code, payload = run_cli(
        dataset_report_main,
        capsys,
        "--project",
        str(project_file),
        "--output",
        str(report),
    )

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["code"] == "PROJECT_JSON_INVALID"
    assert "JSON" in payload["error"]
    assert "不是有效 JSON" in payload["error"]
    assert not report.exists()


@pytest.mark.parametrize("layout", ["no-data-dir", "empty-data-dir"])
def test_dataset_report_without_image_dirs_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], layout: str
) -> None:
    """实现选择：图片目录缺失是错误（退出码 1），不会生成只有风险提示的报告。"""
    root = make_project(tmp_path)
    if layout == "empty-data-dir":
        (root / "data").mkdir()
    report = tmp_path / "不应生成.md"

    exit_code, payload = run_cli(
        dataset_report_main,
        capsys,
        "--project",
        str(root),
        "--output",
        str(report),
    )

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["code"] == "REPORT_IMAGE_DIR_MISSING"
    assert "图片目录不存在" in payload["error"]
    assert not report.exists()


def test_dataset_report_empty_images_dir_still_generates_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``data/images/`` 存在但没有图片：报告生成成功，风险只进报告与计数。"""
    root = make_project(tmp_path)
    (root / "data" / "images").mkdir(parents=True)
    report = tmp_path / "空数据体检报告.md"

    exit_code, payload = run_cli(
        dataset_report_main,
        capsys,
        "--project",
        str(root),
        "--output",
        str(report),
    )

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["samples"] == 0
    assert payload["classes"] == len(CLASSES)
    assert payload["warnings"] >= 1
    assert report.is_file()
    text = report.read_text(encoding="utf-8")
    assert "没有扫描到任何图片样本" in text
    assert "类别「水杯」没有任何图片样本" in text


@pytest.mark.parametrize("case", ["parent-is-file", "target-is-directory"])
def test_dataset_report_unwritable_output_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], case: str
) -> None:
    root = make_project(tmp_path)
    (root / "data" / "images").mkdir(parents=True)  # 先通过图片目录检查
    if case == "parent-is-file":
        # Windows 下父路径是普通文件时无法创建目录（稳定复现“目录不存在且无法创建”）。
        blocker = tmp_path / "被占用的父路径"
        blocker.write_text("not a directory", encoding="utf-8")
        output = blocker / "report.md"
    else:
        output = tmp_path / "已存在的输出目录"
        output.mkdir()

    exit_code, payload = run_cli(
        dataset_report_main,
        capsys,
        "--project",
        str(root),
        "--output",
        str(output),
    )

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["code"] == "REPORT_WRITE_FAILED"
    assert "无法写入" in payload["error"]
    assert "Markdown 报告" in payload["error"]


# ---------------------------------------------------------------------------
# batch_history_export.py
# ---------------------------------------------------------------------------


def test_batch_history_missing_project_exits_one_with_error_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "不存在 项目" / "project.json"
    markdown = tmp_path / "不应生成.md"

    exit_code, payload = run_cli(
        batch_history_main,
        capsys,
        "--project",
        str(missing),
        "--markdown",
        str(markdown),
    )

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["code"] == "PROJECT_NOT_FOUND"
    assert payload["project"] == str(missing)
    assert "不存在" in payload["error"]
    assert not markdown.exists()


def test_batch_history_without_runs_dir_returns_ok_with_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_project(tmp_path)
    assert not (root / "runs").exists()

    exit_code, payload = run_cli(batch_history_main, capsys, "--project", str(root))

    # 实现选择：没有历史不是错误，ok 为 true、runs 为空并在 warnings 中提示。
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["runs"] == []
    assert payload["skipped"] == 0
    assert payload["markdown"] is None
    assert payload["csv"] is None
    assert payload["details_csv"] is None
    assert payload["warnings"]
    assert any(
        "没有可用的批量预测历史" in warning for warning in payload["warnings"]
    )


@pytest.mark.parametrize(
    ("flag", "label"),
    [("--markdown", "Markdown 报告"), ("--csv", "CSV")],
)
def test_batch_history_unwritable_output_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], flag: str, label: str
) -> None:
    root = make_project(tmp_path)
    output = tmp_path / "已存在的输出目录"
    output.mkdir()

    exit_code, payload = run_cli(
        batch_history_main,
        capsys,
        "--project",
        str(root),
        flag,
        str(output),
    )

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["code"] == "BATCH_HISTORY_WRITE_FAILED"
    assert "无法写入" in payload["error"]
    assert label in payload["error"]
