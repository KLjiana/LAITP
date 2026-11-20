"""批量预测历史汇总：把项目 ``runs/`` 下的多次批量预测结果汇总给老师对比。

用法：
    python scripts/batch_history_export.py --project <project.json 或项目目录> \\
        [--markdown <out.md>] [--csv <out.csv>] [--details-csv <out.csv>]

只读取项目文件与 ``runs/batch-predict-*.json``，不修改项目、不重新预测：

- 结果文件按文件名（``batch-predict-<yyyyMMdd-HHmmss>.json``）倒序读取，新的在前；
- 单个文件损坏、不是 UTF-8 文本或顶层不是 JSON 对象时跳过并计入 ``skipped``，
  不影响其它历史记录；
- 标准输出为 UTF-8 JSON 摘要：``ok``、``project``、``runs``、``markdown``、
  ``csv``、``details_csv``、``skipped``、``warnings``；每个 run 含 ``file``（项目相对路径）、
  ``time``（取自文件名时间戳，解析失败时退回文件修改时间）、``artifact_id``、
  ``count``、``labeled``、``accuracy``、``per_class``、``per_batch`` 与
  ``errors``（原始错误条目数组）；
- ``--markdown`` 输出中文汇总表格（时间、张数、准确率、错误数、产物 ID），
  并附“最近一次各类/各批次准确率”小节；
- ``--csv`` 输出逐次运行一行（时间、张数、有标签数、准确率、错误数、artifact_id），
  编码为带 BOM 的 UTF-8，Excel 可直接打开；
- ``--details-csv`` 输出“最近一次运行”的类别/批次明细（表头：类型、名称、总数、
  正确数、准确率），先写“类别”行再写“批次”行，编码为带 BOM 的 UTF-8；准确率保留
  一位小数百分比，``accuracy`` 为 null 或缺失时显示 ``—``；
- 没有可用历史文件时 ``ok`` 仍为 true、``runs`` 为空，并在 ``warnings`` 中提示；
  此时即使指定了 ``--details-csv`` 也不生成文件，JSON 中 ``details_csv`` 为 null，
  并在 ``warnings`` 中说明已跳过（避免留下易被误读的空/过期明细文件）；
- 项目文件缺失/不可读、或报告写入失败时输出错误 JSON 并返回退出码 1。

字段缺失或类型不符合预期时按“无该统计”处理（例如 ``accuracy`` 显示 ``—``），
不把文件当作损坏；只有无法解析的文件才计入 ``skipped``。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.console import emit_json
from backend.project.project import (
    PROJECT_FILE,
    Project,
    ProjectError,
    load_project,
)

RUNS_DIR_NAME = "runs"
BATCH_PREFIX = "batch-predict-"
BATCH_GLOB = f"{BATCH_PREFIX}*.json"
TIMESTAMP_PATTERN = re.compile(r"^batch-predict-(\d{8})-(\d{6})$")
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

MARKDOWN_TABLE_HEADER = "| 时间 | 张数 | 准确率 | 错误数 | 产物 ID |"
MARKDOWN_TABLE_RULE = "| --- | ---: | ---: | ---: | --- |"
CSV_HEADER = ["时间", "张数", "有标签数", "准确率", "错误数", "artifact_id"]
DETAILS_CSV_HEADER = ["类型", "名称", "总数", "正确数", "准确率"]
DETAIL_TYPE_CLASS = "类别"
DETAIL_TYPE_BATCH = "批次"


class HistoryError(Exception):
    """历史报告无法生成（输出写入失败等），``code`` 是稳定错误码。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class HistoryResult:
    project_file: Path
    runs: list[dict[str, Any]] = field(default_factory=list)
    skipped: int = 0
    warnings: list[str] = field(default_factory=list)
    markdown_path: Path | None = None
    csv_path: Path | None = None
    details_csv_path: Path | None = None


def _as_int(value: Any) -> int | None:
    """只接受 JSON 整数（排除布尔值），其余视为缺失。"""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _as_float(value: Any) -> float | None:
    """只接受有限数值（排除布尔值），其余视为缺失。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _as_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _cell(value: object) -> str:
    """转义 Markdown 表格单元格。"""
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def _format_accuracy(accuracy: float | None, *, empty: str = "—") -> str:
    if accuracy is None:
        return empty
    return f"{accuracy * 100:.1f}%"


def _format_int(value: int | None, *, empty: str = "—") -> str:
    return empty if value is None else str(value)


def _run_time(path: Path) -> str:
    """优先取文件名时间戳，取不到时退回文件修改时间。"""
    match = TIMESTAMP_PATTERN.match(path.stem)
    if match is not None:
        try:
            stamp = datetime.strptime(
                f"{match.group(1)}{match.group(2)}", "%Y%m%d%H%M%S"
            )
        except ValueError:
            stamp = None
        if stamp is not None:
            return stamp.strftime(TIME_FORMAT)
    try:
        modified = path.stat().st_mtime
    except OSError:
        return "—"
    return datetime.fromtimestamp(modified).strftime(TIME_FORMAT)


def _load_run(path: Path, root: Path) -> tuple[dict[str, Any] | None, str | None]:
    """读取一个结果文件；无法解析时返回 ``(None, 跳过提示)``。"""
    relative = path.relative_to(root).as_posix()
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError as error:
        return None, f"{relative} 已跳过：无法读取（{error.strerror or error}）"
    except UnicodeDecodeError as error:
        return None, f"{relative} 已跳过：不是 UTF-8 文本（{error}）"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        return (
            None,
            f"{relative} 已跳过：不是有效 JSON"
            f"（{error.msg}，第 {error.lineno} 行第 {error.colno} 列）",
        )
    if not isinstance(data, dict):
        return None, f"{relative} 已跳过：JSON 顶层不是对象"

    per_class = data.get("per_class")
    per_batch = data.get("per_batch")
    errors = data.get("errors")
    return (
        {
            "file": relative,
            "time": _run_time(path),
            "artifact_id": _as_text(data.get("artifact_id")),
            "count": _as_int(data.get("count")),
            "labeled": _as_int(data.get("labeled")),
            "accuracy": _as_float(data.get("accuracy")),
            "per_class": dict(per_class) if isinstance(per_class, dict) else {},
            "per_batch": dict(per_batch) if isinstance(per_batch, dict) else {},
            "errors": list(errors) if isinstance(errors, list) else [],
        },
        None,
    )


def collect_runs(root: Path) -> tuple[list[dict[str, Any]], int, list[str]]:
    """扫描 ``root/runs/batch-predict-*.json``，返回 (按文件名倒序的 runs, 跳过数, 提示)。"""
    runs_dir = root / RUNS_DIR_NAME
    if not runs_dir.is_dir():
        return [], 0, []
    paths = sorted(
        (path for path in runs_dir.glob(BATCH_GLOB) if path.is_file()),
        key=lambda path: path.name,
        reverse=True,
    )
    runs: list[dict[str, Any]] = []
    warnings: list[str] = []
    skipped = 0
    for path in paths:
        entry, warning = _load_run(path, root)
        if entry is None:
            skipped += 1
            if warning is not None:
                warnings.append(warning)
            continue
        runs.append(entry)
    return runs, skipped, warnings


def _stats_table_lines(stats_map: dict[str, Any]) -> list[str]:
    """把 ``per_class``/``per_batch`` 渲染为表格行；脏数据条目跳过而不是崩溃。"""
    lines: list[str] = []
    for name, stats in stats_map.items():
        if not isinstance(stats, dict):
            continue
        count = _as_int(stats.get("count"))
        correct = _as_int(stats.get("correct"))
        accuracy = _as_float(stats.get("accuracy"))
        if accuracy is None and count and correct is not None:
            accuracy = correct / count
        lines.append(
            f"| {_cell(name)} | {_format_accuracy(accuracy)} "
            f"| {_format_int(correct)}/{_format_int(count)} |"
        )
    return lines


def _now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def render_markdown(
    *,
    project: Project,
    project_file: Path,
    runs: Sequence[dict[str, Any]],
    skipped: int,
    generated_at: str,
) -> str:
    lines: list[str] = [
        "# 批量预测历史汇总",
        "",
        f"生成时间：{generated_at}",
        "",
        f"项目：{_cell(project.name)}（`{project.project_id}`）",
        f"项目文件：`{project_file}`",
        "",
        "## 历次运行",
        "",
    ]

    if runs:
        lines.append(MARKDOWN_TABLE_HEADER)
        lines.append(MARKDOWN_TABLE_RULE)
        for run in runs:
            artifact = run["artifact_id"]
            artifact_cell = f"`{_cell(artifact)}`" if artifact else "—"
            lines.append(
                f"| {run['time']} | {_format_int(run['count'])} "
                f"| {_format_accuracy(run['accuracy'])} "
                f"| {len(run['errors'])} | {artifact_cell} |"
            )
        lines.append("")
        lines.append(f"> 共 {len(runs)} 次运行，按时间从新到旧排列。")
        if skipped:
            lines.append(f"> 另有 {skipped} 个损坏或无法解析的结果文件已跳过。")
        lines.append("")
    else:
        lines.append("项目 `runs/` 下还没有可用的批量预测历史（未找到有效的 `batch-predict-*.json`）。")
        if skipped:
            lines.append("")
            lines.append(f"> 已扫描到 {skipped} 个结果文件，但都损坏或无法解析。")
        lines.append("")

    lines.append("## 最近一次各类/各批次准确率")
    lines.append("")
    if not runs:
        lines.append("暂无历史运行，无法汇总。")
        lines.append("")
    else:
        latest = runs[0]
        artifact = latest["artifact_id"]
        artifact_text = f"，产物 `{_cell(artifact)}`" if artifact else ""
        lines.append(
            f"最近一次运行：{latest['time']}"
            f"（`{latest['file']}`{artifact_text}）"
        )
        lines.append("")
        for title, key, label, empty_text in (
            (
                "各类准确率",
                "per_class",
                "类别",
                "最近一次运行没有各类准确率统计（可能没有真实类别标签）。",
            ),
            (
                "各批次准确率",
                "per_batch",
                "批次",
                "最近一次运行没有各批次准确率统计。",
            ),
        ):
            stats_lines = _stats_table_lines(latest[key])
            lines.append(f"### {title}")
            lines.append("")
            if stats_lines:
                lines.append(f"| {label} | 准确率 | 正确/总数 |")
                lines.append("| --- | ---: | ---: |")
                lines.extend(stats_lines)
            else:
                lines.append(empty_text)
            lines.append("")

    lines.extend(
        [
            "---",
            "",
            "本报告只读取项目 `project.json` 与 `runs/batch-predict-*.json`，"
            "不修改项目、不重新预测。",
            "",
        ]
    )
    return "\n".join(lines)


def _write_text(path: Path, text: str, label: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as error:
        raise HistoryError(
            "BATCH_HISTORY_WRITE_FAILED",
            f"无法写入 {label} {path}：{error.strerror or error}",
        ) from error


def _write_bom_csv(
    path: Path,
    header: Sequence[str],
    rows: Iterable[Sequence[object]],
    label: str,
) -> None:
    """写 Excel 可直接打开的 UTF-8 BOM CSV；失败时抛出 ``HistoryError``。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(rows)
    except OSError as error:
        raise HistoryError(
            "BATCH_HISTORY_WRITE_FAILED",
            f"无法写入 {label} {path}：{error.strerror or error}",
        ) from error


def _write_csv(path: Path, runs: Iterable[dict[str, Any]]) -> None:
    rows = [
        [
            run["time"],
            "" if run["count"] is None else run["count"],
            "" if run["labeled"] is None else run["labeled"],
            _format_accuracy(run["accuracy"], empty=""),
            len(run["errors"]),
            run["artifact_id"] or "",
        ]
        for run in runs
    ]
    _write_bom_csv(path, CSV_HEADER, rows, "CSV")


def _detail_rows(stats_map: dict[str, Any], kind: str) -> list[list[str]]:
    """把 ``per_class``/``per_batch`` 渲染为明细 CSV 行。

    每个条目都保留一行；统计值缺失或类型不符合预期时显示 ``—``。
    准确率只取条目里的 ``accuracy``（缺失时为 ``—``），不从正确/总数反推，
    以保证与 JSON 数据一一对应。
    """
    rows: list[list[str]] = []
    for name, stats in stats_map.items():
        if isinstance(stats, dict):
            count = _as_int(stats.get("count"))
            correct = _as_int(stats.get("correct"))
            accuracy = _as_float(stats.get("accuracy"))
        else:
            count = correct = accuracy = None
        rows.append(
            [
                kind,
                str(name),
                _format_int(count),
                _format_int(correct),
                _format_accuracy(accuracy),
            ]
        )
    return rows


def _write_details_csv(path: Path, latest: dict[str, Any]) -> None:
    """写“最近一次运行”的类别/批次明细（先类别行，后批次行）。"""
    rows: list[list[str]] = [
        *_detail_rows(latest["per_class"], DETAIL_TYPE_CLASS),
        *_detail_rows(latest["per_batch"], DETAIL_TYPE_BATCH),
    ]
    _write_bom_csv(path, DETAILS_CSV_HEADER, rows, "明细 CSV")


def _load_project_root(project: str | Path) -> tuple[Path, Path, Project]:
    """解析 ``--project``（project.json 或项目目录）并加载项目。"""
    candidate = Path(project)
    project_file = candidate / PROJECT_FILE if candidate.is_dir() else candidate
    loaded = load_project(project_file)
    resolved = project_file.resolve()
    return resolved.parent, resolved, loaded


def export_history(
    project: str | Path,
    *,
    markdown: str | Path | None = None,
    csv_path: str | Path | None = None,
    details_csv: str | Path | None = None,
) -> HistoryResult:
    """汇总历史并写出可选报告；项目不可读时抛出 ``ProjectError``。"""
    root, project_file, loaded = _load_project_root(project)
    runs, skipped, warnings = collect_runs(root)
    if not runs:
        warnings.insert(
            0,
            "项目 runs/ 下没有可用的批量预测历史（未找到有效的 batch-predict-*.json）。",
        )

    result = HistoryResult(
        project_file=project_file,
        runs=runs,
        skipped=skipped,
        warnings=warnings,
    )
    if markdown is not None:
        target = Path(markdown).resolve()
        _write_text(
            target,
            render_markdown(
                project=loaded,
                project_file=project_file,
                runs=runs,
                skipped=skipped,
                generated_at=_now_text(),
            ),
            "Markdown 报告",
        )
        result.markdown_path = target
    if csv_path is not None:
        target = Path(csv_path).resolve()
        _write_csv(target, runs)
        result.csv_path = target
    if details_csv is not None:
        target = Path(details_csv).resolve()
        if runs:
            _write_details_csv(target, runs[0])
            result.details_csv_path = target
        else:
            warnings.append(
                "没有可用的批量预测历史，已跳过明细 CSV 导出："
                f"{target}"
            )
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python scripts/batch_history_export.py",
        description=(
            "LAITP 批量预测历史汇总：扫描项目 runs/batch-predict-*.json，"
            "输出中文 Markdown 表格与可选 CSV，方便对比多次批量预测。"
        ),
    )
    parser.add_argument("--project", required=True, help="project.json 或项目目录")
    parser.add_argument(
        "--markdown",
        default=None,
        help="可选：Markdown 汇总报告输出路径",
    )
    parser.add_argument(
        "--csv",
        default=None,
        help="可选：逐次运行 CSV 输出路径（UTF-8 BOM，Excel 可直接打开）",
    )
    parser.add_argument(
        "--details-csv",
        default=None,
        help=(
            "可选：最近一次运行的类别/批次明细 CSV 输出路径"
            "（UTF-8 BOM，Excel 可直接打开）"
        ),
    )
    return parser


def _emit_error(project: str | Path, code: str, message: str) -> None:
    emit_json(
        {"ok": False, "project": str(project), "code": code, "error": message}
    )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    args = _build_parser().parse_args(argv)
    try:
        result = export_history(
            args.project,
            markdown=args.markdown,
            csv_path=args.csv,
            details_csv=args.details_csv,
        )
    except ProjectError as error:
        _emit_error(args.project, error.code.value, error.message)
        return 1
    except HistoryError as error:
        _emit_error(args.project, error.code, error.message)
        return 1

    emit_json(
        {
            "ok": True,
            "project": str(result.project_file),
            "runs": result.runs,
            "markdown": (
                None if result.markdown_path is None else str(result.markdown_path)
            ),
            "csv": None if result.csv_path is None else str(result.csv_path),
            "details_csv": (
                None
                if result.details_csv_path is None
                else str(result.details_csv_path)
            ),
            "skipped": result.skipped,
            "warnings": result.warnings,
        }
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
