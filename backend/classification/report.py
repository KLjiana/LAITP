"""训练结果报告：读取训练运行目录并校验摘要与文件完整性。

供桌面界面显示准确率、每类召回、混淆矩阵与误判样本；不重新推理，
也不替代导出或模型包校验。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..contracts import integrity
from ..contracts.errors import Code
from .model import TrainingError
from .training import TRAINING_RECORD_FORMAT, load_training_artifact

_REQUIRED_FILES = ("training-artifact.json", "metrics.json", "model.pt")


def _read_json(path: Path, description: str) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise TrainingError(
            Code.TRAINING_ARTIFACT_INVALID, f"训练目录缺少 {description}：{path}"
        ) from None
    except (OSError, json.JSONDecodeError) as error:
        raise TrainingError(
            Code.TRAINING_ARTIFACT_INVALID, f"无法读取 {description}：{error}"
        ) from error


def _verify_files(run: Path, record: dict[str, Any]) -> None:
    files = record.get("files")
    if not isinstance(files, dict) or "model.pt" not in files:
        raise TrainingError(
            Code.TRAINING_ARTIFACT_INVALID, "训练记录缺少文件摘要（files.model.pt）"
        )
    for name, expected in files.items():
        path = run / name
        if not path.is_file():
            raise TrainingError(
                Code.TRAINING_ARTIFACT_INVALID, f"训练运行缺少文件 {name}：{path}"
            )
        if not isinstance(expected, dict) or not isinstance(
            expected.get("sha256"), str
        ):
            raise TrainingError(
                Code.TRAINING_ARTIFACT_INVALID, f"训练记录中 {name} 的摘要格式非法"
            )
        actual = integrity.sha256_file(path)
        if actual != expected["sha256"]:
            raise TrainingError(
                Code.TRAINING_ARTIFACT_INVALID,
                f"训练文件 {name} 的摘要 {actual} 与记录不一致",
            )


def load_training_report(run_dir: str | Path) -> dict[str, Any]:
    run = Path(run_dir)
    if not run.is_dir():
        raise TrainingError(
            Code.TRAINING_ARTIFACT_INVALID, f"训练目录不存在：{run}"
        )

    record = _read_json(run / "training-artifact.json", "training-artifact.json")
    if record.get("format") != TRAINING_RECORD_FORMAT:
        raise TrainingError(
            Code.TRAINING_ARTIFACT_INVALID,
            f"训练记录格式不是 {TRAINING_RECORD_FORMAT}",
        )
    _verify_files(run, record)
    # 训练产物应能被重新加载，报告不信任未通过重载校验的记录。
    load_training_artifact(run / "model.pt")

    metrics = _read_json(run / "metrics.json", "metrics.json")
    try:
        classes = list(metrics["dataset"]["classes"])
        evaluation = metrics["evaluation"]
        matrix = evaluation["confusion_matrix"]
        accuracy = float(evaluation["accuracy"])
        loss = float(evaluation["loss"])
        per_class_recall = list(evaluation["per_class_recall"])
        training = metrics["training"]
        run_id = str(metrics["run_id"])
        timings = metrics.get("timings_seconds", {})
    except (KeyError, TypeError, ValueError) as error:
        raise TrainingError(
            Code.TRAINING_ARTIFACT_INVALID, f"metrics.json 结构不完整：{error}"
        ) from error

    if len(classes) < 2:
        raise TrainingError(
            Code.TRAINING_ARTIFACT_INVALID, "训练报告至少需要 2 个类别"
        )
    count = len(classes)
    if (
        not isinstance(matrix, list)
        or len(matrix) != count
        or any(not isinstance(row, list) or len(row) != count for row in matrix)
    ):
        raise TrainingError(
            Code.TRAINING_ARTIFACT_INVALID, "混淆矩阵维度与类别数不一致"
        )
    if len(per_class_recall) != count:
        raise TrainingError(
            Code.TRAINING_ARTIFACT_INVALID, "每类召回数量与类别数不一致"
        )

    samples = evaluation.get("samples")
    if samples is None:
        samples = []
    if not isinstance(samples, list):
        raise TrainingError(
            Code.TRAINING_ARTIFACT_INVALID, "metrics.json 中的 samples 不是数组"
        )
    checked_samples: list[dict[str, Any]] = []
    for sample in samples:
        try:
            true_id = int(sample["true_class_id"])
            predicted_id = int(sample["predicted_class_id"])
            path = str(sample["path"])
        except (KeyError, TypeError, ValueError) as error:
            raise TrainingError(
                Code.TRAINING_ARTIFACT_INVALID, f"样本结果结构非法：{error}"
            ) from error
        if not 0 <= true_id < count or not 0 <= predicted_id < count:
            raise TrainingError(
                Code.TRAINING_ARTIFACT_INVALID, "样本类别 ID 越界"
            )
        checked_samples.append(
            {
                "path": path,
                "true_class_id": true_id,
                "predicted_class_id": predicted_id,
            }
        )

    return {
        "run_dir": str(run),
        "run_id": run_id,
        "artifact_id": str(record.get("artifact_id", "")),
        "classes": classes,
        "accuracy": accuracy,
        "loss": loss,
        "confusion_matrix": [[int(value) for value in row] for row in matrix],
        "per_class_recall": [
            None if value is None else float(value) for value in per_class_recall
        ],
        "validation_samples": len(checked_samples) or sum(sum(row) for row in matrix),
        "best_epoch": int(training.get("best_epoch", 0)),
        "epochs": int(training.get("epochs", 0)),
        "timings_seconds": timings,
        "samples": checked_samples,
    }
