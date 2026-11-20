"""批量预测历史汇总 CLI 测试（秒级，直接构造历史 JSON，不训练）。"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from backend.project.project import create_project
from scripts.batch_history_export import main

CLASSES = ("水杯", "书本")
CREATED_AT = "2026-11-17T10:00:00+08:00"

NEWER_RUN = {
    "ok": True,
    "artifact_id": "art-20261118-0001",
    "count": 4,
    "labeled": 4,
    "accuracy": 0.75,
    "per_class": {
        "水杯": {"count": 2, "correct": 2, "accuracy": 1.0},
        "书本": {"count": 2, "correct": 1, "accuracy": 0.5},
    },
    "per_batch": {
        "batch-1": {"count": 2, "correct": 2, "accuracy": 1.0},
        "batch-2": {"count": 2, "correct": 1, "accuracy": 0.5},
    },
    "errors": [{"image": "坏图.png", "error": "无法解码"}],
}

OLDER_RUN = {
    "ok": True,
    "artifact_id": "art-20261117-0001",
    "count": 3,
    "labeled": 0,
    "accuracy": None,
    "per_class": {},
    "per_batch": {},
    "errors": [],
}

DETAIL_NEWER_RUN = {
    "ok": True,
    "artifact_id": "art-20261118-0002",
    "count": 6,
    "labeled": 6,
    "accuracy": 0.5,
    "per_class": {
        "水杯": {"count": 2, "correct": 2, "accuracy": 1.0},
        "书本": {"count": 2, "correct": 1, "accuracy": 0.5},
        "橡皮": {"count": 1, "correct": 0, "accuracy": None},
        "尺子": {"count": 1, "correct": 0},  # accuracy 缺失
    },
    "per_batch": {
        "batch-1": {"count": 2, "correct": 2, "accuracy": 1.0},
        "batch-2": {"count": 3, "correct": 1, "accuracy": 1 / 3},
    },
    "errors": [],
}

DETAIL_OLDER_RUN = {
    "ok": True,
    "artifact_id": "art-20261117-0002",
    "count": 2,
    "labeled": 2,
    "accuracy": 1.0,
    "per_class": {"旧类别": {"count": 2, "correct": 2, "accuracy": 1.0}},
    "per_batch": {"旧批次": {"count": 2, "correct": 2, "accuracy": 1.0}},
    "errors": [],
}


def new_project(tmp_path: Path) -> Path:
    root = tmp_path / "学生 项目"
    create_project(
        root,
        project_id="proj-history-0001",
        name="历史汇总项目",
        classes=CLASSES,
        created_at=CREATED_AT,
    )
    return root


def write_run(root: Path, filename: str, payload: dict) -> Path:
    runs = root / "runs"
    runs.mkdir(exist_ok=True)
    target = runs / filename
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return target


def run_cli(
    capsys: pytest.CaptureFixture[str], *arguments: str
) -> tuple[int, dict]:
    exit_code = main(list(arguments))
    payload = json.loads(capsys.readouterr().out)
    return exit_code, payload


def test_markdown_and_summary_are_sorted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = new_project(tmp_path)
    write_run(root, "batch-predict-20261117-100000.json", OLDER_RUN)
    write_run(root, "batch-predict-20261118-090000.json", NEWER_RUN)
    report = tmp_path / "输出 目录" / "批量预测历史.md"

    exit_code, payload = run_cli(
        capsys, "--project", str(root), "--markdown", str(report)
    )

    assert exit_code == 0
    assert {"ok", "project", "runs", "markdown", "csv", "skipped"} <= set(payload)
    assert payload["ok"] is True
    assert payload["project"] == str((root / "project.json").resolve())
    assert payload["markdown"] == str(report.resolve())
    assert payload["csv"] is None
    assert payload["details_csv"] is None
    assert payload["skipped"] == 0
    assert payload["warnings"] == []

    runs = payload["runs"]
    assert [run["file"] for run in runs] == [
        "runs/batch-predict-20261118-090000.json",
        "runs/batch-predict-20261117-100000.json",
    ]
    newest = runs[0]
    assert newest["time"] == "2026-11-18 09:00:00"
    assert newest["artifact_id"] == "art-20261118-0001"
    assert newest["count"] == 4 and newest["labeled"] == 4
    assert newest["accuracy"] == 0.75
    assert newest["per_class"]["水杯"]["correct"] == 2
    assert set(newest["per_batch"]) == {"batch-1", "batch-2"}
    assert len(newest["errors"]) == 1

    oldest = runs[1]
    assert oldest["time"] == "2026-11-17 10:00:00"
    assert oldest["accuracy"] is None
    assert oldest["labeled"] == 0
    assert oldest["per_class"] == {}
    assert oldest["errors"] == []

    text = report.read_text(encoding="utf-8")
    assert "# 批量预测历史汇总" in text
    assert "历史汇总项目" in text
    assert "| 时间 | 张数 | 准确率 | 错误数 | 产物 ID |" in text
    newest_row = "| 2026-11-18 09:00:00 | 4 | 75.0% | 1 | `art-20261118-0001` |"
    oldest_row = "| 2026-11-17 10:00:00 | 3 | — | 0 | `art-20261117-0001` |"
    assert newest_row in text
    assert oldest_row in text
    assert text.index(newest_row) < text.index(oldest_row)
    assert len([line for line in text.splitlines() if line.startswith("| 2026-")]) == 2
    assert "## 最近一次各类/各批次准确率" in text
    assert "| 水杯 | 100.0% | 2/2 |" in text
    assert "| 书本 | 50.0% | 1/2 |" in text
    assert "| batch-2 | 50.0% | 1/2 |" in text


def test_csv_rows_and_bom(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = new_project(tmp_path)
    write_run(root, "batch-predict-20261117-100000.json", OLDER_RUN)
    write_run(root, "batch-predict-20261118-090000.json", NEWER_RUN)
    csv_path = tmp_path / "输出" / "批量历史.csv"

    exit_code, payload = run_cli(
        capsys, "--project", str(root / "project.json"), "--csv", str(csv_path)
    )

    assert exit_code == 0
    assert payload["csv"] == str(csv_path.resolve())
    assert payload["markdown"] is None
    assert payload["skipped"] == 0
    assert csv_path.read_bytes().startswith(b"\xef\xbb\xbf")

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == ["时间", "张数", "有标签数", "准确率", "错误数", "artifact_id"]
    assert len(rows) == 3
    assert rows[1] == [
        "2026-11-18 09:00:00",
        "4",
        "4",
        "75.0%",
        "1",
        "art-20261118-0001",
    ]
    assert rows[2] == [
        "2026-11-17 10:00:00",
        "3",
        "0",
        "",
        "0",
        "art-20261117-0001",
    ]


def test_details_csv_uses_latest_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = new_project(tmp_path)
    write_run(root, "batch-predict-20261117-100000.json", DETAIL_OLDER_RUN)
    write_run(root, "batch-predict-20261118-090000.json", DETAIL_NEWER_RUN)
    details_path = tmp_path / "输出 目录" / "最近一次明细.csv"

    exit_code, payload = run_cli(
        capsys,
        "--project",
        str(root),
        "--details-csv",
        str(details_path),
    )

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["details_csv"] == str(details_path.resolve())
    assert payload["markdown"] is None
    assert payload["csv"] is None
    assert payload["warnings"] == []
    assert details_path.read_bytes().startswith(b"\xef\xbb\xbf")

    with details_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == ["类型", "名称", "总数", "正确数", "准确率"]
    # 先“类别”行、后“批次”行；全部来自最近一次运行（2026-11-18 09:00:00）。
    assert [row[0] for row in rows[1:]] == ["类别"] * 4 + ["批次"] * 2
    assert rows[1:] == [
        ["类别", "水杯", "2", "2", "100.0%"],
        ["类别", "书本", "2", "1", "50.0%"],
        ["类别", "橡皮", "1", "0", "—"],
        ["类别", "尺子", "1", "0", "—"],
        ["批次", "batch-1", "2", "2", "100.0%"],
        ["批次", "batch-2", "3", "1", "33.3%"],
    ]
    assert len(rows) == 7
    text = details_path.read_text(encoding="utf-8-sig")
    assert "旧类别" not in text
    assert "旧批次" not in text
    assert "art-20261117-0002" not in text


def test_details_csv_empty_history_is_skipped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = new_project(tmp_path)
    details_path = tmp_path / "无历史明细.csv"

    exit_code, payload = run_cli(
        capsys,
        "--project",
        str(root),
        "--details-csv",
        str(details_path),
    )

    # 实现选择：没有可用历史时不生成明细文件，JSON details_csv 为 null，
    # 并在 warnings 中说明已跳过（避免留下仅表头/过期文件被误读为有效明细）。
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["runs"] == []
    assert payload["details_csv"] is None
    assert not details_path.exists()
    assert any(
        "没有可用的批量预测历史" in warning and "明细 CSV" in warning
        for warning in payload["warnings"]
    )


def test_corrupt_result_is_skipped_without_affecting_others(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = new_project(tmp_path)
    write_run(root, "batch-predict-20261117-100000.json", OLDER_RUN)
    corrupt = root / "runs" / "batch-predict-20261119-120000.json"
    corrupt.write_text('{"count": 2, "accuracy": ', encoding="utf-8")
    report = tmp_path / "损坏跳过.md"

    exit_code, payload = run_cli(
        capsys, "--project", str(root), "--markdown", str(report)
    )

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["skipped"] == 1
    assert [run["file"] for run in payload["runs"]] == [
        "runs/batch-predict-20261117-100000.json"
    ]
    assert any(
        "batch-predict-20261119-120000.json" in warning
        for warning in payload["warnings"]
    )

    text = report.read_text(encoding="utf-8")
    assert "art-20261117-0001" in text
    assert "2026-11-19 12:00:00" not in text


def test_empty_history_warns_and_missing_project_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = new_project(tmp_path)
    report = tmp_path / "无历史.md"

    exit_code, payload = run_cli(
        capsys, "--project", str(root), "--markdown", str(report)
    )

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["runs"] == []
    assert payload["skipped"] == 0
    assert payload["warnings"]
    assert any(
        "没有可用的批量预测历史" in warning for warning in payload["warnings"]
    )
    text = report.read_text(encoding="utf-8")
    assert "还没有可用的批量预测历史" in text
    assert "暂无历史运行" in text

    missing_project = tmp_path / "缺失 项目" / "project.json"
    missing_report = tmp_path / "缺失.md"
    exit_code, payload = run_cli(
        capsys,
        "--project",
        str(missing_project),
        "--markdown",
        str(missing_report),
    )

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["code"] == "PROJECT_NOT_FOUND"
    assert "不存在" in payload["error"]
    assert not missing_report.exists()
