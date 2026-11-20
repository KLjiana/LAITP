"""独立推理命令行：validate / predict / evaluate（T06）。

只接收模型产物包、图片和数据清单，不访问训练目录或训练框架。
标准输出为 UTF-8 JSON，退出码 0 表示成功、1 表示失败。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

import onnxruntime as ort

from ..classification.dataset import DatasetPolicy, validate_dataset_manifest
from ..console import emit_json
from ..contracts.errors import Code, Report, Stage
from .checks import check_fixed_samples
from .inference import RuntimeInferenceError
from .loading import load_runtime


def _finish(report: Report, payload: dict[str, Any]) -> int:
    if report.ok:
        emit_json({"ok": True, **payload})
        return 0
    emit_json({"ok": False, **report.to_dict()})
    return 1


def _validate(args: argparse.Namespace) -> int:
    package = Path(args.package)
    runtime, report = load_runtime(package, platform=args.platform)
    if runtime is None:
        return _finish(report, {})
    summary = check_fixed_samples(runtime, report)
    payload = {
        "artifact_id": runtime.artifact_id,
        "package": str(package),
        "checks": {
            "package_validation": {"ok": True},
            "fixed_samples": summary,
        },
        "runtime": {"name": "onnxruntime", "version": ort.__version__},
    }
    return _finish(report, payload)


def _predict(args: argparse.Namespace) -> int:
    package = Path(args.package)
    runtime, report = load_runtime(package, platform=args.platform)
    if runtime is None:
        return _finish(report, {})
    image_path = Path(args.image)
    try:
        result = runtime.predict_file(image_path)
    except RuntimeInferenceError as error:
        report.add(error.code, Stage.RUNTIME, "image", error.message)
        return _finish(report, {})

    predictions = [
        {
            "class_id": item.class_id,
            "label": item.label,
            "probability": item.probability,
        }
        for item in result.predictions
    ]
    if args.top_k:
        predictions = predictions[: args.top_k]
    payload = {
        "artifact_id": result.artifact_id,
        "image": str(image_path),
        "input_shape": list(result.input_shape),
        "predictions": predictions,
        "top_prediction": predictions[0] if predictions else None,
        "runtime": {"name": "onnxruntime", "version": ort.__version__},
    }
    return _finish(report, payload)


def _evaluate(args: argparse.Namespace) -> int:
    package = Path(args.package)
    runtime, report = load_runtime(package, platform=args.platform)
    if runtime is None:
        return _finish(report, {})

    manifest_path = Path(args.manifest)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        report.add(
            Code.RUNTIME_CONFIG_INVALID,
            Stage.RUNTIME,
            "dataset_manifest",
            f"无法读取数据清单 {manifest_path}：{error}",
        )
        return _finish(report, {})

    policy = DatasetPolicy(min_train_per_class=0, min_val_per_class=0)
    dataset_report = validate_dataset_manifest(
        manifest, dataset_root=Path(args.data_root), policy=policy
    )
    report.extend(dataset_report.issues)
    if not dataset_report.ok:
        return _finish(report, {})

    classes = list(manifest["classes"])
    if classes != runtime.labels:
        report.add(
            Code.RUNTIME_CONFIG_INVALID,
            Stage.RUNTIME,
            "dataset_manifest.classes",
            "数据清单类别表与模型包标签顺序不一致，评估结果会整体错位",
        )
        return _finish(report, {})

    split = args.split
    samples = [sample for sample in manifest["samples"] if sample["split"] == split]
    if not samples:
        report.add(
            Code.RUNTIME_CONFIG_INVALID,
            Stage.RUNTIME,
            "dataset_manifest.samples",
            f"数据清单在 {split!r} 划分中没有样本",
        )
        return _finish(report, {})

    data_root = Path(args.data_root)
    num_classes = len(classes)
    matrix = [[0] * num_classes for _ in range(num_classes)]
    misclassifications: list[dict[str, Any]] = []

    for index, sample in enumerate(samples):
        try:
            result = runtime.predict_file(data_root / sample["path"])
        except RuntimeInferenceError as error:
            report.add(
                error.code,
                Stage.RUNTIME,
                f"samples[{index}]",
                error.message,
            )
            continue
        expected = int(sample["class_id"])
        predicted = result.predictions[0]
        matrix[expected][predicted.class_id] += 1
        if predicted.class_id != expected:
            misclassifications.append(
                {
                    "path": sample["path"],
                    "expected_class_id": expected,
                    "expected_label": classes[expected],
                    "predicted_class_id": predicted.class_id,
                    "predicted_label": predicted.label,
                    "probability": predicted.probability,
                }
            )

    if not report.ok:
        return _finish(report, {})

    correct = sum(matrix[index][index] for index in range(num_classes))
    per_class_recall = [
        (matrix[index][index] / sum(matrix[index])) if sum(matrix[index]) else None
        for index in range(num_classes)
    ]
    payload = {
        "artifact_id": runtime.artifact_id,
        "dataset_id": manifest["dataset_id"],
        "split": split,
        "counts": {
            "samples": len(samples),
            "correct": correct,
            "incorrect": len(misclassifications),
        },
        "accuracy": correct / len(samples),
        "per_class_recall": per_class_recall,
        "confusion_matrix": matrix,
        "misclassifications": misclassifications,
        "runtime": {"name": "onnxruntime", "version": ort.__version__},
    }
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        payload = {**payload, "report_path": str(report_path)}
    return _finish(report, payload)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backend.runtime",
        description="LAITP 独立推理运行时（validate / predict / evaluate）",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser(
        "validate", help="校验模型包并执行固定样本验证"
    )
    validate_parser.add_argument("--package", required=True, help="模型产物包目录")
    validate_parser.add_argument("--platform", default="windows-x64")

    predict_parser = subparsers.add_parser("predict", help="预测单张图片")
    predict_parser.add_argument("--package", required=True, help="模型产物包目录")
    predict_parser.add_argument("--image", required=True, help="待测图片路径")
    predict_parser.add_argument("--top-k", type=int, default=0, dest="top_k")
    predict_parser.add_argument("--platform", default="windows-x64")

    evaluate_parser = subparsers.add_parser(
        "evaluate", help="在数据清单的指定划分上评估"
    )
    evaluate_parser.add_argument("--package", required=True, help="模型产物包目录")
    evaluate_parser.add_argument("--manifest", required=True, help="数据清单路径")
    evaluate_parser.add_argument("--data-root", required=True, dest="data_root")
    evaluate_parser.add_argument(
        "--split", default="test", choices=["train", "val", "test"]
    )
    evaluate_parser.add_argument("--report", default=None, help="指标输出文件（可选）")
    evaluate_parser.add_argument("--platform", default="windows-x64")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "validate":
        return _validate(args)
    if args.command == "predict":
        return _predict(args)
    return _evaluate(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
