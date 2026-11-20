"""数据集体检报告 CLI 测试（秒级，构造小图片，不训练）。"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from backend.project.dataset import rebuild_dataset
from backend.project.project import create_project
from scripts.dataset_report import main
from tests.support.images import build_dataset_tree

CLASSES = ("水杯", "书本")
CREATED_AT = "2026-11-17T10:00:00+08:00"


def new_project(tmp_path: Path, *, test_batches: int = 0) -> Path:
    """按项目格式创建 data/images/<类别>/<批次>/ 与 data/test-images/...。"""
    root = tmp_path / "学生 项目"
    create_project(
        root,
        project_id="proj-report-0001",
        name="体检项目",
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
    return root


def run_cli(
    capsys: pytest.CaptureFixture[str], *arguments: str
) -> tuple[int, dict]:
    exit_code = main(list(arguments))
    payload = json.loads(capsys.readouterr().out)
    return exit_code, payload


def test_markdown_report_has_info_tables_and_risks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = new_project(tmp_path, test_batches=1)
    rebuild_dataset(root, dataset_id="ds-report-0001")
    report = tmp_path / "输出" / "report.md"

    exit_code, payload = run_cli(
        capsys, "--project", str(root / "project.json"), "--output", str(report)
    )

    assert exit_code == 0
    assert set(payload) == {
        "ok",
        "project",
        "report",
        "csv",
        "classes",
        "samples",
        "duplicates",
        "invalid",
        "warnings",
    }
    assert payload["ok"] is True
    assert payload["project"] == str((root / "project.json").resolve())
    assert payload["report"] == str(report.resolve())
    assert payload["csv"] is None
    assert payload["classes"] == 2
    assert payload["samples"] == 6
    assert payload["duplicates"] == 0
    assert payload["invalid"] == 0
    assert payload["warnings"] == 2  # 两个类别各少于 30 张

    text = report.read_text(encoding="utf-8")
    assert "# 数据集体检报告" in text
    assert "体检项目" in text
    assert "类别（2 个） | 水杯、书本" in text
    assert "| 当前模型 | 未设置 |" in text
    assert "## 2. 训练/验证/测试样本数" in text
    assert "| 合计 | 6 |" in text
    assert "## 3. 每类每批次样本数" in text
    assert "| 类别 | 批次 | 来源目录 | 清单划分 | 样本数 |" in text
    assert "| 水杯 | batch-1 | `data/images` |" in text
    assert "| 书本 | test-batch-1 | `data/test-images` |" in text
    assert "## 6. 风险提示" in text
    assert "少于建议的 30 张" in text
    assert "未生成" not in text


def test_csv_rows_and_duplicate_detection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = new_project(tmp_path)
    source = root / "data" / "images" / CLASSES[0] / "batch-1" / "001.png"
    copied = root / "data" / "images" / CLASSES[0] / "batch-2" / "002.png"
    copied.write_bytes(source.read_bytes())
    rebuild_dataset(root, dataset_id="ds-report-dup-0001")

    report = tmp_path / "report.md"
    csv_path = tmp_path / "样本明细.csv"
    exit_code, payload = run_cli(
        capsys,
        "--project",
        str(root),  # 也支持直接传项目目录
        "--output",
        str(report),
        "--csv",
        str(csv_path),
    )

    assert exit_code == 0
    assert payload["samples"] == 5  # 4 张原始训练图片 + 1 张复制图
    assert payload["duplicates"] == 1
    assert payload["invalid"] == 0
    assert payload["csv"] == str(csv_path.resolve())

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    assert len(rows) == payload["samples"] + 1
    assert rows[0] == [
        "相对路径",
        "类别",
        "批次",
        "划分",
        "宽度",
        "高度",
        "sha256前12位",
        "是否重复",
    ]
    assert all(len(row) == 8 for row in rows)
    assert all(len(row[6]) == 12 for row in rows[1:])
    assert all(row[3] in {"训练", "验证", "测试", "未划分"} for row in rows[1:])

    duplicated = [row for row in rows[1:] if row[-1] == "是"]
    assert len(duplicated) == 2
    assert {row[0] for row in duplicated} == {
        "data/images/水杯/batch-1/001.png",
        "data/images/水杯/batch-2/002.png",
    }

    text = report.read_text(encoding="utf-8")
    assert "重复组 1" in text
    assert "sha256 前 12 位" in text
    assert "data/images/水杯/batch-2/002.png" in text


def test_missing_project_exits_one_with_error_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "没有项目" / "project.json"
    report = tmp_path / "report.md"

    exit_code, payload = run_cli(
        capsys, "--project", str(missing), "--output", str(report)
    )

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["code"] == "PROJECT_NOT_FOUND"
    assert "不存在" in payload["error"]
    assert not report.exists()


def test_missing_manifest_still_scans_data_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = new_project(tmp_path, test_batches=1)  # 不调用 rebuild_dataset
    report = tmp_path / "report.md"

    exit_code, payload = run_cli(
        capsys, "--project", str(root / "project.json"), "--output", str(report)
    )

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["samples"] == 6
    assert payload["warnings"] >= 1

    text = report.read_text(encoding="utf-8")
    assert "## 2. 训练/验证/测试样本数" in text
    assert "| 训练（train） | 未生成 |" in text
    assert "## 3. 每类每批次样本数" in text
    assert "| 水杯 | batch-1 | `data/images` | 未划分 | 1 |" in text
    assert "## 6. 风险提示" in text
