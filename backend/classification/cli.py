"""分类命令行：训练与导出入口（T04/T05）。

这不是最终产品 CLI；标准输出为 UTF-8 JSON，退出码 0 表示成功、1 表示失败。
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Sequence

from ..console import emit_json
from ..contracts.errors import Code, Issue, Report, Stage
from .export import DEFAULT_OPSET, ExportConfig, ExportError, export_model
from .model import DEFAULT_WEIGHTS_ID, TrainingError
from .preprocess import PreprocessSpec
from .report import load_training_report
from .training import TrainingConfig, TrainingDataRejected, train


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backend.classification",
        description="LAITP 分类后端命令行（train / export / report）",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    train_parser = subparsers.add_parser("train", help="训练线性分类头")
    train_parser.add_argument("--dataset", required=True, help="数据清单路径")
    train_parser.add_argument("--data-root", required=True, help="数据集根目录")
    train_parser.add_argument("--output", required=True, help="训练输出根目录")
    train_parser.add_argument("--run-id", required=True, help="本次训练记录 ID")
    source = train_parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--weights-config", help="预训练权重配置，例如 configs/weights.v1.json"
    )
    source.add_argument(
        "--random-init",
        action="store_true",
        help="诊断用：不加载预训练权重，产物会标记 pretrained=false",
    )
    train_parser.add_argument("--weights-id", default=DEFAULT_WEIGHTS_ID)
    train_parser.add_argument("--epochs", type=int, default=30)
    train_parser.add_argument("--batch-size", type=int, default=16)
    train_parser.add_argument("--learning-rate", type=float, default=0.001)
    train_parser.add_argument("--weight-decay", type=float, default=0.0001)
    train_parser.add_argument("--seed", type=int, default=20261117)
    train_parser.add_argument("--threads", type=int, default=None)
    train_parser.add_argument("--image-size", type=int, default=224)

    export_parser = subparsers.add_parser(
        "export", help="把训练产物导出为契约 1.0 的 ONNX 模型包"
    )
    export_parser.add_argument("--run", required=True, help="训练运行目录")
    export_parser.add_argument("--output", required=True, help="导出根目录")
    export_parser.add_argument("--artifact-id", required=True, help="新产物 ID")
    export_parser.add_argument("--project-id", required=True)
    export_parser.add_argument(
        "--platform", default="windows-x64", choices=["windows-x64", "linux-x64"]
    )
    export_parser.add_argument("--opset", type=int, default=DEFAULT_OPSET)
    export_parser.add_argument(
        "--weights-config",
        default=None,
        help="可选：提供时校验特征提取器权重摘要与训练记录一致",
    )
    export_parser.add_argument("--weights-id", default=DEFAULT_WEIGHTS_ID)
    export_parser.add_argument(
        "--data-root", default=None, help="数据根目录；默认取训练配置中的值"
    )
    export_parser.add_argument("--samples-per-class", type=int, default=1)
    export_parser.add_argument("--abs-tolerance", type=float, default=1e-3)
    export_parser.add_argument("--rel-tolerance", type=float, default=1e-3)
    export_parser.add_argument(
        "--created-at", default=None, help="RFC 3339 时间，用于可复现记录"
    )

    report_parser = subparsers.add_parser(
        "report", help="读取训练结果摘要（准确率、召回、混淆矩阵、误判样本）"
    )
    report_parser.add_argument("--run", required=True, help="训练运行目录")
    return parser


def _emit_failure(
    error: Exception, code: Code, stage: Stage, issues: Sequence[Issue] = ()
) -> int:
    report = Report([Issue(code, stage, "$", str(error)), *issues])
    emit_json({"ok": False, **report.to_dict()})
    return 1


def _train(args: argparse.Namespace) -> int:
    config = TrainingConfig(
        run_id=args.run_id,
        dataset_manifest=Path(args.dataset),
        dataset_root=Path(args.data_root),
        output_root=Path(args.output),
        weights_config=Path(args.weights_config) if args.weights_config else None,
        weights_id=args.weights_id,
        seed=args.seed,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        weight_decay=args.weight_decay,
        threads=args.threads,
        preprocess=PreprocessSpec(width=args.image_size, height=args.image_size),
    )
    try:
        result = train(config)
    except TrainingDataRejected as rejection:
        emit_json({"ok": False, **rejection.report.to_dict()})
        return 1
    except TrainingError as error:
        return _emit_failure(error, error.code, Stage.TRAINING)

    emit_json(
        {
            "ok": True,
            "run_id": result.run_id,
            "run_dir": str(result.run_dir),
            "model_path": str(result.model_path),
            "training_record": str(result.training_record_path),
            "metrics": result.metrics,
        }
    )
    return 0


def _export(args: argparse.Namespace) -> int:
    created_at = None
    if args.created_at:
        try:
            created_at = datetime.fromisoformat(args.created_at.replace("Z", "+00:00"))
        except ValueError:
            return _emit_bad_timestamp(args.created_at)

    config = ExportConfig(
        run_dir=Path(args.run),
        output_root=Path(args.output),
        artifact_id=args.artifact_id,
        project_id=args.project_id,
        platform=args.platform,
        opset=args.opset,
        weights_config=Path(args.weights_config) if args.weights_config else None,
        weights_id=args.weights_id,
        data_root=Path(args.data_root) if args.data_root else None,
        samples_per_class=args.samples_per_class,
        logit_abs_tolerance=args.abs_tolerance,
        logit_rel_tolerance=args.rel_tolerance,
        created_at=created_at,
    )
    try:
        result = export_model(config)
    except ExportError as error:
        return _emit_failure(error, error.code, Stage.ARTIFACTS, error.issues)
    except TrainingError as error:
        return _emit_failure(error, error.code, Stage.TRAINING)

    emit_json(
        {
            "ok": True,
            "artifact_id": result.artifact_id,
            "package_dir": str(result.package_dir),
            "manifest_path": str(result.manifest_path),
            "conversion_record": str(result.conversion_record_path),
            "checks": result.checks,
        }
    )
    return 0


def _report(args: argparse.Namespace) -> int:
    try:
        report = load_training_report(Path(args.run))
    except TrainingError as error:
        return _emit_failure(error, error.code, Stage.TRAINING)
    emit_json({"ok": True, "report": report})
    return 0


def _emit_bad_timestamp(value: str) -> int:
    return _emit_failure(
        ValueError(f"created_at {value!r} 不是有效 RFC 3339 时间"),
        Code.EXPORT_CONFIG_INVALID,
        Stage.ARTIFACTS,
    )

def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "train":
        return _train(args)
    if args.command == "report":
        return _report(args)
    return _export(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
