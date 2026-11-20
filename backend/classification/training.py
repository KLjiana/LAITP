"""CPU 训练：冻结 MobileNetV3-Small，只训练线性分类头（T04）。

训练只使用数据清单的 train/val 划分；test 划分不参与训练与调参，只在指标中
记录样本数，防止测试集泄漏。训练产物包含配置、数据集清单副本、指标和可重载
的分类头权重，并记录权重、数据与环境的追溯信息。
"""

from __future__ import annotations

import json
import platform
import random
import shutil
import time
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np
import torch
import torchvision
from torch import nn

from ..contracts import integrity
from ..contracts.errors import Code, Issue, Report, Stage
from .dataset import (
    TEST,
    TRAIN,
    VAL,
    DatasetPolicy,
    summarize,
    validate_dataset_manifest,
)
from .model import (
    ARCHITECTURE,
    DEFAULT_WEIGHTS_ID,
    TrainingError,
    WeightReference,
    build_classifier,
    build_feature_extractor,
    build_inference_model,
    extract_features,
    feature_dim,
    load_weight_reference,
)
from .preprocess import PreprocessSpec, load_image

ARTIFACT_FORMAT = "laitp-training-model-1.0"
TRAINING_RECORD_FORMAT = "laitp-training-record-1.0"
ProgressCallback = Callable[[str, int, int], None]


class TrainingDataRejected(Exception):
    """数据清单未通过校验；``report`` 保留具体错误码与定位。"""

    def __init__(self, report: Report) -> None:
        super().__init__("数据清单未通过校验")
        self.report = report


@dataclass(frozen=True)
class TrainingConfig:
    run_id: str
    dataset_manifest: Path
    dataset_root: Path
    output_root: Path
    weights_config: Path | None = None
    weights_id: str = DEFAULT_WEIGHTS_ID
    seed: int = 20261117
    epochs: int = 30
    batch_size: int = 16
    learning_rate: float = 0.001
    weight_decay: float = 0.0001
    threads: int | None = None
    preprocess: PreprocessSpec = PreprocessSpec()

    def with_image_size(self, size: int) -> "TrainingConfig":
        return replace(self, preprocess=replace(self.preprocess, width=size, height=size))


@dataclass(frozen=True)
class TrainingResult:
    run_id: str
    run_dir: Path
    model_path: Path
    training_record_path: Path
    metrics: dict[str, Any]


@dataclass(frozen=True)
class LoadedTrainingArtifact:
    metadata: dict[str, Any]
    model: nn.Module
    classes: list[str]
    preprocess: PreprocessSpec


# --------------------------------------------------------------------------- #
# 训练
# --------------------------------------------------------------------------- #


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _validate_config(config: TrainingConfig) -> None:
    if not config.run_id or any(
        char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
        for char in config.run_id
    ):
        raise TrainingError(
            Code.TRAINING_CONFIG_INVALID,
            f"run_id {config.run_id!r} 只能包含字母、数字、点、下划线和连字符",
        )
    if config.epochs < 1:
        raise TrainingError(Code.TRAINING_CONFIG_INVALID, "epochs 必须 ≥ 1")
    if config.batch_size < 1:
        raise TrainingError(Code.TRAINING_CONFIG_INVALID, "batch_size 必须 ≥ 1")
    if config.learning_rate <= 0:
        raise TrainingError(Code.TRAINING_CONFIG_INVALID, "learning_rate 必须 > 0")
    if config.weight_decay < 0:
        raise TrainingError(Code.TRAINING_CONFIG_INVALID, "weight_decay 不能为负")
    if config.threads is not None and config.threads < 1:
        raise TrainingError(Code.TRAINING_CONFIG_INVALID, "threads 必须 ≥ 1")


def _load_dataset(
    config: TrainingConfig,
) -> tuple[dict[str, Any], bytes]:
    manifest_path = Path(config.dataset_manifest)
    try:
        raw = manifest_path.read_bytes()
    except OSError as error:
        raise TrainingDataRejected(
            Report(
                [
                    Issue(
                        Code.DATASET_JSON_INVALID,
                        Stage.SCHEMA,
                        str(manifest_path),
                        f"无法读取数据清单：{error.strerror or error}",
                    )
                ]
            )
        ) from error
    try:
        manifest = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TrainingDataRejected(
            Report(
                [
                    Issue(
                        Code.DATASET_JSON_INVALID,
                        Stage.SCHEMA,
                        str(manifest_path),
                        f"数据清单不是有效 JSON：{error}",
                    )
                ]
            )
        ) from error

    report = validate_dataset_manifest(manifest, dataset_root=Path(config.dataset_root))
    if not report.ok:
        raise TrainingDataRejected(report)
    return manifest, raw


def _set_determinism(seed: int, threads: int | None) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if threads is not None:
        torch.set_num_threads(threads)


def _split_samples(
    manifest: dict[str, Any], split: str
) -> list[dict[str, Any]]:
    return [sample for sample in manifest["samples"] if sample["split"] == split]


def _features(
    samples: Sequence[dict[str, Any]],
    config: TrainingConfig,
    transform: Any,
    extractor: nn.Module,
    *,
    progress: ProgressCallback | None = None,
    offset: int = 0,
    total: int = 0,
) -> tuple[torch.Tensor, torch.Tensor]:
    root = Path(config.dataset_root)
    batches: list[torch.Tensor] = []
    processed = 0
    for start in range(0, len(samples), config.batch_size):
        chunk = samples[start : start + config.batch_size]
        images = torch.stack([transform(load_image(root / item["path"])) for item in chunk])
        batches.append(extract_features(extractor, images))
        processed += len(chunk)
        if progress is not None:
            progress("feature_extraction", offset + processed, total)
    labels = torch.tensor([item["class_id"] for item in samples], dtype=torch.long)
    if not batches:
        return torch.empty((0, feature_dim(extractor))), labels
    return torch.cat(batches, dim=0), labels


def _evaluate(
    head: nn.Module,
    features: torch.Tensor,
    labels: torch.Tensor,
    criterion: nn.Module,
) -> tuple[float, float, torch.Tensor]:
    head.eval()
    with torch.no_grad():
        logits = head(features)
        loss = float(criterion(logits, labels).item())
        predictions = logits.argmax(dim=1)
    accuracy = float((predictions == labels).float().mean().item()) if len(labels) else 0.0
    return loss, accuracy, predictions


def _train_head(
    train_x: torch.Tensor,
    train_y: torch.Tensor,
    val_x: torch.Tensor,
    val_y: torch.Tensor,
    num_classes: int,
    config: TrainingConfig,
    *,
    progress: ProgressCallback | None = None,
) -> tuple[nn.Module, dict[str, list[float]], dict[str, Any]]:
    head = build_classifier(int(train_x.shape[1]), num_classes)
    optimizer = torch.optim.AdamW(
        head.parameters(), lr=config.learning_rate, weight_decay=config.weight_decay
    )
    criterion = nn.CrossEntropyLoss()
    history: dict[str, list[float]] = {
        "train_loss": [],
        "val_loss": [],
        "val_accuracy": [],
    }
    best: dict[str, Any] = {
        "epoch": 0,
        "accuracy": -1.0,
        "loss": float("inf"),
        "state": None,
    }

    for epoch in range(1, config.epochs + 1):
        head.train()
        permutation = torch.randperm(train_x.shape[0])
        total_loss = 0.0
        for start in range(0, train_x.shape[0], config.batch_size):
            index = permutation[start : start + config.batch_size]
            optimizer.zero_grad()
            logits = head(train_x[index])
            loss = criterion(logits, train_y[index])
            loss.backward()
            optimizer.step()
            total_loss += float(loss.item()) * len(index)

        train_loss = total_loss / max(1, train_x.shape[0])
        val_loss, val_accuracy, _ = _evaluate(head, val_x, val_y, criterion)
        history["train_loss"].append(train_loss)
        history["val_loss"].append(val_loss)
        history["val_accuracy"].append(val_accuracy)

        if val_accuracy > best["accuracy"] or (
            val_accuracy == best["accuracy"] and val_loss < best["loss"]
        ):
            best = {
                "epoch": epoch,
                "accuracy": val_accuracy,
                "loss": val_loss,
                "state": {
                    name: value.detach().clone()
                    for name, value in head.state_dict().items()
                },
            }

        if progress is not None:
            progress("head_training", epoch, config.epochs)
    if best["state"] is not None:
        head.load_state_dict(best["state"])
    return head, history, best


def _confusion_matrix(
    predictions: torch.Tensor, labels: torch.Tensor, num_classes: int
) -> list[list[int]]:
    matrix = [[0] * num_classes for _ in range(num_classes)]
    for prediction, target in zip(predictions.tolist(), labels.tolist()):
        matrix[target][prediction] += 1
    return matrix


def _per_class_recall(matrix: list[list[int]]) -> list[float | None]:
    recalls: list[float | None] = []
    for index, row in enumerate(matrix):
        total = sum(row)
        recalls.append(row[index] / total if total else None)
    return recalls


def _environment() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "torch": torch.__version__,
        "torchvision": torchvision.__version__,
        "platform": platform.platform(),
        "machine": platform.machine(),
    }


def train(
    config: TrainingConfig, *, progress: ProgressCallback | None = None
) -> TrainingResult:
    """训练线性分类头并保存可重载产物。

    ``progress(stage, completed, total)`` 可选，用于向父进程报告粗粒度进度：
    ``load``、``feature_extraction``（按图片数）、``head_training``（按轮次）、
    ``publish``。不改变训练结果。
    """
    _validate_config(config)
    if progress is not None:
        progress("load", 0, 1)
    manifest, raw_manifest = _load_dataset(config)
    if progress is not None:
        progress("load", 1, 1)
    manifest_digest = integrity.sha256_bytes(raw_manifest)
    classes = list(manifest["classes"])
    train_samples = _split_samples(manifest, TRAIN)
    val_samples = _split_samples(manifest, VAL)
    test_samples = _split_samples(manifest, TEST)

    weight: WeightReference | None = None
    if config.weights_config is not None:
        weight = load_weight_reference(config.weights_config, weights_id=config.weights_id)

    _set_determinism(config.seed, config.threads)
    started = time.perf_counter()
    extractor = build_feature_extractor(weight.path if weight is not None else None)
    transform = config.preprocess.transform()

    feature_started = time.perf_counter()
    total_images = len(train_samples) + len(val_samples)
    if progress is not None:
        progress("feature_extraction", 0, total_images)
    train_x, train_y = _features(
        train_samples,
        config,
        transform,
        extractor,
        progress=progress,
        offset=0,
        total=total_images,
    )
    val_x, val_y = _features(
        val_samples,
        config,
        transform,
        extractor,
        progress=progress,
        offset=len(train_samples),
        total=total_images,
    )
    feature_seconds = time.perf_counter() - feature_started

    head_started = time.perf_counter()
    head, history, best = _train_head(
        train_x, train_y, val_x, val_y, len(classes), config, progress=progress
    )
    head_seconds = time.perf_counter() - head_started

    criterion = nn.CrossEntropyLoss()
    val_loss, val_accuracy, predictions = _evaluate(head, val_x, val_y, criterion)
    matrix = _confusion_matrix(predictions, val_y, len(classes))
    total_seconds = time.perf_counter() - started

    created_at = _utc_now()
    model_info = {
        "architecture": ARCHITECTURE,
        "weights_id": weight.id if weight is not None else None,
        "weights_sha256": weight.sha256 if weight is not None else None,
        "pretrained": weight is not None,
        "frozen_features": True,
        "head": "linear",
        "num_classes": len(classes),
        "input_size": [config.preprocess.width, config.preprocess.height],
    }
    metrics: dict[str, Any] = {
        "run_id": config.run_id,
        "created_at": created_at,
        "dataset": {
            "dataset_id": manifest["dataset_id"],
            "dataset_manifest_sha256": manifest_digest,
            "classes": classes,
            "splits": summarize(manifest)["splits"],
            "used_splits": [TRAIN, VAL],
            "unused_test_samples": len(test_samples),
        },
        "model": model_info,
        "training": {
            "seed": config.seed,
            "epochs": config.epochs,
            "batch_size": config.batch_size,
            "learning_rate": config.learning_rate,
            "weight_decay": config.weight_decay,
            "threads": torch.get_num_threads(),
            "best_epoch": best["epoch"],
            **history,
        },
        "evaluation": {
            "split": VAL,
            "loss": val_loss,
            "accuracy": val_accuracy,
            "per_class_recall": _per_class_recall(matrix),
            "confusion_matrix": matrix,
            "samples": [
                {
                    "path": sample["path"],
                    "true_class_id": int(sample["class_id"]),
                    "predicted_class_id": int(prediction),
                }
                for sample, prediction in zip(val_samples, predictions.tolist())
            ],
        },
        "timings_seconds": {
            "feature_extraction": feature_seconds,
            "head_training": head_seconds,
            "total": total_seconds,
        },
        "environment": _environment(),
    }

    if progress is not None:
        progress("publish", 0, 1)
    run_dir = _write_artifacts(
        config,
        raw_manifest=raw_manifest,
        manifest_digest=manifest_digest,
        weight=weight,
        head=head,
        classes=classes,
        metrics=metrics,
        created_at=created_at,
    )
    if progress is not None:
        progress("publish", 1, 1)
    model_path = run_dir / "model.pt"
    return TrainingResult(
        run_id=config.run_id,
        run_dir=run_dir,
        model_path=model_path,
        training_record_path=run_dir / "training-artifact.json",
        metrics=metrics,
    )


def _write_artifacts(
    config: TrainingConfig,
    *,
    raw_manifest: bytes,
    manifest_digest: str,
    weight: WeightReference | None,
    head: nn.Module,
    classes: Sequence[str],
    metrics: dict[str, Any],
    created_at: str,
) -> Path:
    output_root = Path(config.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    final_dir = output_root / config.run_id
    if final_dir.exists():
        raise TrainingError(
            Code.TRAINING_CONFIG_INVALID,
            f"运行目录已存在：{final_dir}；每次训练必须使用新的 run_id",
        )

    temporary = output_root / f".tmp-{config.run_id}-{uuid.uuid4().hex[:8]}"
    temporary.mkdir()
    try:
        config_payload = {
            "run_id": config.run_id,
            "created_at": created_at,
            "dataset_manifest": str(Path(config.dataset_manifest).resolve()),
            "dataset_root": str(Path(config.dataset_root).resolve()),
            "dataset_manifest_sha256": manifest_digest,
            "weights": None
            if weight is None
            else {
                "id": weight.id,
                "sha256": weight.sha256,
                "path": str(weight.path),
                "license": weight.license,
                "source": weight.source,
            },
            "seed": config.seed,
            "epochs": config.epochs,
            "batch_size": config.batch_size,
            "learning_rate": config.learning_rate,
            "weight_decay": config.weight_decay,
            "threads": torch.get_num_threads(),
            "preprocess": config.preprocess.to_dict(),
            "environment": _environment(),
        }
        (temporary / "config.json").write_text(
            json.dumps(config_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (temporary / "dataset-manifest.json").write_bytes(raw_manifest)
        (temporary / "metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        # 保存完整可推理模型（特征提取器 + 线性分类头），使训练产物自包含，
        # 重新加载与导出不依赖训练进程或随机初始化顺序。
        inference_model = build_inference_model(
            weight.path if weight is not None else None, len(classes)
        )
        inference_model.classifier.load_state_dict(head.state_dict())
        inference_model.eval()
        torch.save(
            {
                "format": ARTIFACT_FORMAT,
                "run_id": config.run_id,
                "created_at": created_at,
                "dataset_id": metrics["dataset"]["dataset_id"],
                "dataset_manifest_sha256": manifest_digest,
                "classes": list(classes),
                "model": metrics["model"],
                "preprocess": config.preprocess.to_dict(),
                "model_state_dict": inference_model.state_dict(),
            },
            temporary / "model.pt",
        )

        files = {
            name: {
                "sha256": integrity.sha256_file(temporary / name),
                "size_bytes": (temporary / name).stat().st_size,
            }
            for name in ("model.pt", "config.json", "metrics.json", "dataset-manifest.json")
        }
        training_record = {
            "format": TRAINING_RECORD_FORMAT,
            "artifact_id": f"train-{config.run_id}",
            "run_id": config.run_id,
            "created_at": created_at,
            "task": "image_classification",
            "dataset": metrics["dataset"],
            "model": metrics["model"],
            "preprocess": config.preprocess.to_dict(),
            "files": files,
            "environment": metrics["environment"],
        }
        (temporary / "training-artifact.json").write_text(
            json.dumps(training_record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.rename(final_dir)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final_dir


# --------------------------------------------------------------------------- #
# 重新加载
# --------------------------------------------------------------------------- #


def load_training_artifact(
    model_path: str | Path, *, weights_path: str | Path | None = None
) -> LoadedTrainingArtifact:
    """重新加载训练产物，用于导出或验证训练端可重载性。"""
    path = Path(model_path)
    try:
        data = torch.load(str(path), map_location="cpu", weights_only=True)
    except Exception as error:  # torch 的加载异常类型不固定
        raise TrainingError(
            Code.TRAINING_ARTIFACT_INVALID, f"无法读取训练产物 {path}：{error}"
        ) from error
    if not isinstance(data, dict) or data.get("format") != ARTIFACT_FORMAT:
        raise TrainingError(
            Code.TRAINING_ARTIFACT_INVALID,
            f"训练产物格式不是 {ARTIFACT_FORMAT}",
        )

    classes = list(data["classes"])
    model_info = data["model"]
    num_classes = int(model_info["num_classes"])
    if num_classes != len(classes):
        raise TrainingError(
            Code.TRAINING_ARTIFACT_INVALID,
            f"产物类别数 {num_classes} 与类别表长度 {len(classes)} 不一致",
        )

    resolved_weights = Path(weights_path) if weights_path is not None else None
    expected_digest = model_info.get("weights_sha256")
    if resolved_weights is not None and expected_digest:
        actual = integrity.sha256_file(resolved_weights)
        if actual != expected_digest:
            raise TrainingError(
                Code.TRAINING_ARTIFACT_INVALID,
                f"特征提取器权重摘要 {actual} 与训练记录 {expected_digest} 不一致",
            )

    model = build_inference_model(None, num_classes)
    try:
        model.load_state_dict(data["model_state_dict"], strict=True)
    except (KeyError, RuntimeError) as error:
        raise TrainingError(
            Code.TRAINING_ARTIFACT_INVALID,
            f"训练产物中的模型权重不完整或结构不符：{error}",
        ) from error
    model.eval()
    return LoadedTrainingArtifact(
        metadata=data,
        model=model,
        classes=classes,
        preprocess=PreprocessSpec.from_dict(data["preprocess"]),
    )
