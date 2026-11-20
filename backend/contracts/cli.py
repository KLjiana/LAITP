"""契约校验命令行（开发与验收用）。

这不是 M0-01 第 7 节计划中的训练/预测 CLI，只用于对现有产物包和消息样例
执行契约校验。标准输出为 JSON 结果，退出码 0 表示通过、1 表示存在问题。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from ..console import emit_json
from .envelope import validate_envelope
from .errors import Code, Issue, Report, Stage
from .manifest import validate_model_package
from .runtime_spec import RuntimeProfile


def _build_profile(args: argparse.Namespace) -> RuntimeProfile | None:
    if args.runtime is None:
        return None
    if args.runtime_version is None or args.platform is None:
        raise SystemExit("指定 --runtime 时必须同时提供 --runtime-version 与 --platform")
    return RuntimeProfile(
        runtime=args.runtime,
        version=args.runtime_version,
        platform=args.platform,
        capabilities=frozenset(args.capability or ()),
    )


def _emit(report: Report, target: str) -> int:
    emit_json({"target": target, **report.to_dict()})
    return 0 if report.ok else 1


def _load_envelope(path: Path) -> tuple[Any, Issue | None]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as error:
        return None, Issue(
            code=Code.ENVELOPE_JSON_INVALID,
            stage=Stage.SCHEMA,
            location=str(path),
            message=f"无法读取消息文件：{error.strerror or error}",
        )
    try:
        return json.loads(text), None
    except json.JSONDecodeError as error:
        return None, Issue(
            code=Code.ENVELOPE_JSON_INVALID,
            stage=Stage.SCHEMA,
            location=str(path),
            message=f"JSON 解析失败：第 {error.lineno} 行第 {error.colno} 列：{error.msg}",
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m backend.contracts",
        description="LAITP 模型产物与进程消息契约校验",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    package = subparsers.add_parser("package", help="校验模型产物包目录")
    package.add_argument("path", help="产物包根目录（含 manifest.json）")
    package.add_argument("--runtime", help="目标运行时，例如 onnxruntime")
    package.add_argument("--runtime-version", help="当前运行时版本，例如 1.19.2")
    package.add_argument("--platform", help="目标平台，例如 windows-x64")
    package.add_argument(
        "--capability",
        action="append",
        help="当前运行环境具备的能力，例如 onnxruntime-cpu；可重复",
    )

    envelope = subparsers.add_parser("envelope", help="校验单条 JSON 消息")
    envelope.add_argument("path", help="消息 JSON 文件；每行一条消息的文件请逐行校验")

    args = parser.parse_args(argv)
    if args.command == "package":
        report = validate_model_package(
            Path(args.path), runtime_profile=_build_profile(args)
        )
        return _emit(report, str(args.path))

    data, issue = _load_envelope(Path(args.path))
    if issue is not None:
        report = Report([issue])
    else:
        report = validate_envelope(data)
    return _emit(report, str(args.path))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
