"""任务工作进程：按协议 1.0 输出进度、结果或错误。

标准输出只承载按行 JSON 消息，日志写入标准错误；失败时发送 error 消息并以
非零码退出。父进程由 :mod:`backend.runtime.supervisor` 实现或参照其行为。

用法::

    python -m backend.runtime.worker predict --package <包目录> --image <图片> \\
        --request-id req-1 --project-id proj-1 --task-id task-1

    python -m backend.runtime.worker validate --package <包目录> ...
    python -m backend.runtime.worker train --dataset <清单> --data-root <目录> \\
        --output <输出目录> --run-id <运行 ID> ...
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from ..contracts import integrity
from ..contracts.errors import Code, Report, Stage
from .inference import RuntimeInferenceError
from .loading import load_runtime, report_failure
from .messages import MessageWriter, ProtocolError


def _package_reference(package: Path) -> dict[str, Any]:
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        "artifact_id": str(manifest["artifact_id"]),
        "manifest_path": "manifest.json",
        "manifest_sha256": integrity.sha256_file(manifest_path),
    }


def _fail(writer: MessageWriter, report: Report) -> int:
    code, stage, message, location = report_failure(
        report, default_code=Code.TASK_INTERNAL_ERROR.value
    )
    writer.error(code, stage, message, location=location)
    return 1


def _run_predict(args: argparse.Namespace, writer: MessageWriter) -> int:
    writer.progress("load", 0, 2)
    runtime, report = load_runtime(Path(args.package))
    if runtime is None:
        return _fail(writer, report)
    writer.artifact_id = runtime.artifact_id
    writer.progress("load", 1, 2)
    try:
        result = runtime.predict_file(args.image)
    except RuntimeInferenceError as error:
        writer.error(error.code.value, Stage.RUNTIME.value, error.message)
        return 1
    writer.progress("inference", 2, 2)
    predictions = [
        {
            "class_id": item.class_id,
            "label": item.label,
            "probability": item.probability,
        }
        for item in result.predictions
    ]
    writer.result("predict", _package_reference(Path(args.package)), predictions=predictions)
    return 0


def _run_validate(args: argparse.Namespace, writer: MessageWriter) -> int:
    from .checks import check_fixed_samples

    writer.progress("load", 0, 2)
    runtime, report = load_runtime(Path(args.package))
    if runtime is None:
        return _fail(writer, report)
    writer.artifact_id = runtime.artifact_id
    writer.progress("load", 1, 2)
    check_fixed_samples(runtime, report)
    writer.progress("fixed_samples", 2, 2)
    if not report.ok:
        return _fail(writer, report)
    writer.result("validate", _package_reference(Path(args.package)))
    return 0


def _run_train(args: argparse.Namespace, writer: MessageWriter) -> int:
    from ..classification.model import TrainingError
    from ..classification.preprocess import PreprocessSpec
    from ..classification.training import (
        TrainingConfig,
        TrainingDataRejected,
        train,
    )

    writer.progress("accepted", 0, 1)
    config = TrainingConfig(
        run_id=args.run_id,
        dataset_manifest=Path(args.dataset),
        dataset_root=Path(args.data_root),
        output_root=Path(args.output),
        weights_config=Path(args.weights_config) if args.weights_config else None,
        epochs=args.epochs,
        batch_size=args.batch_size,
        threads=args.threads,
        preprocess=PreprocessSpec(width=args.image_size, height=args.image_size),
    )

    def report(stage: str, completed: int, total: int) -> None:
        writer.progress(stage, completed, total)

    try:
        result = train(config, progress=report)
    except TrainingDataRejected as rejection:
        return _fail(writer, rejection.report)
    except TrainingError as error:
        writer.error(error.code.value, Stage.TRAINING.value, error.message)
        return 1
    record = json.loads(result.training_record_path.read_text(encoding="utf-8"))
    reference = {
        "artifact_id": record["artifact_id"],
        "manifest_path": "training-artifact.json",
        "manifest_sha256": integrity.sha256_file(result.training_record_path),
    }
    writer.result("train", reference)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backend.runtime.worker",
        description="LAITP 任务工作进程（协议 1.0）",
    )
    subparsers = parser.add_subparsers(dest="job", required=True)

    def add_common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--request-id", required=True)
        sub.add_argument("--project-id", required=True)
        sub.add_argument("--task-id", required=True)

    predict = subparsers.add_parser("predict", help="预测单张图片")
    add_common(predict)
    predict.add_argument("--package", required=True)
    predict.add_argument("--image", required=True)

    validate = subparsers.add_parser("validate", help="校验模型包与固定样本")
    add_common(validate)
    validate.add_argument("--package", required=True)

    train = subparsers.add_parser("train", help="训练线性分类头")
    add_common(train)
    train.add_argument("--dataset", required=True)
    train.add_argument("--data-root", required=True)
    train.add_argument("--output", required=True)
    train.add_argument("--run-id", required=True)
    train.add_argument("--weights-config", default=None)
    train.add_argument("--epochs", type=int, default=30)
    train.add_argument("--batch-size", type=int, default=16)
    train.add_argument("--threads", type=int, default=None)
    train.add_argument("--image-size", type=int, default=224)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    writer = MessageWriter(
        request_id=args.request_id,
        project_id=args.project_id,
        task_id=args.task_id,
    )
    try:
        if args.job == "predict":
            return _run_predict(args, writer)
        if args.job == "validate":
            return _run_validate(args, writer)
        return _run_train(args, writer)
    except ProtocolError as error:  # pragma: no cover - 构造消息失败属于实现缺陷
        print(f"协议消息构造失败：{error}", file=sys.stderr)
        return 2
    except Exception as error:  # 未预期异常也必须以协议错误结束
        writer.error(
            Code.TASK_INTERNAL_ERROR.value,
            Stage.RUNTIME.value,
            f"工作进程内部错误：{error}",
        )
        print(f"未处理异常：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
