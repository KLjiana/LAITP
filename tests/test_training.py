"""CPU 训练与训练产物测试（T04）。

默认用例使用随机初始化的特征提取器（``weights_config=None``），只验证训练
流程、指标、确定性和可重载性，不依赖本地预训练权重文件；依赖真实权重的
用例在权重缺失时跳过。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
import torch

from backend.classification.dataset import build_dataset_manifest
from backend.classification.model import TrainingError
from backend.classification.preprocess import PreprocessSpec, load_image
from backend.classification.report import load_training_report
from backend.classification.training import (
    TrainingConfig,
    TrainingDataRejected,
    load_training_artifact,
    train,
)
from backend.contracts.errors import Code
from tests.support.images import build_dataset_tree

CLASSES = ("水杯", "书本", "笔袋")
FIXED_TIME = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)
WEIGHTS_CONFIG = Path("configs/weights.v1.json")
WEIGHTS_FILE = Path("artifacts/weights/mobilenet_v3_small-047dcff4.pth")


@pytest.fixture()
def prepared(tmp_path: Path) -> tuple[Path, Path]:
    root = build_dataset_tree(
        tmp_path / "data", classes=CLASSES, train_batches=3, images_per_batch=2
    )
    manifest = build_dataset_manifest(
        root, classes=CLASSES, dataset_id="ds-20261117-0100", created_at=FIXED_TIME
    )
    path = root / "dataset-manifest.json"
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return root, path


def make_config(
    root: Path,
    manifest: Path,
    tmp_path: Path,
    *,
    run_id: str = "run-test-0001",
    **overrides: Any,
) -> TrainingConfig:
    values: dict[str, Any] = {
        "run_id": run_id,
        "dataset_manifest": manifest,
        "dataset_root": root,
        "output_root": tmp_path / "runs",
        "weights_config": None,
        "epochs": 2,
        "batch_size": 8,
        "threads": 1,
        "preprocess": PreprocessSpec(width=32, height=32),
    }
    values.update(overrides)
    return TrainingConfig(**values)


def test_training_produces_complete_artifacts(
    prepared: tuple[Path, Path], tmp_path: Path
) -> None:
    root, manifest = prepared
    result = train(make_config(root, manifest, tmp_path))

    assert (result.run_dir / "config.json").is_file()
    assert (result.run_dir / "metrics.json").is_file()
    assert (result.run_dir / "dataset-manifest.json").is_file()
    assert result.model_path.is_file()

    metrics = result.metrics
    assert metrics["dataset"]["used_splits"] == ["train", "val"]
    assert metrics["dataset"]["unused_test_samples"] == 3
    assert metrics["model"]["pretrained"] is False
    assert metrics["model"]["num_classes"] == 3
    assert 0.0 <= metrics["evaluation"]["accuracy"] <= 1.0
    assert len(metrics["evaluation"]["confusion_matrix"]) == 3
    assert len(metrics["evaluation"]["per_class_recall"]) == 3
    assert metrics["timings_seconds"]["feature_extraction"] >= 0
    assert metrics["timings_seconds"]["head_training"] >= 0
    assert "test" not in json.dumps(metrics["evaluation"])


def test_training_reports_progress(
    prepared: tuple[Path, Path], tmp_path: Path
) -> None:
    root, manifest = prepared
    events: list[tuple[str, int, int]] = []
    result = train(
        make_config(root, manifest, tmp_path, epochs=2),
        progress=lambda stage, completed, total: events.append((stage, completed, total)),
    )

    stages = [event[0] for event in events]
    assert stages[0] == "load"
    assert ("load", 0, 1) in events
    assert ("load", 1, 1) in events
    assert stages[-1] == "publish"
    assert events[-1] == ("publish", 1, 1)

    features = [event for event in events if event[0] == "feature_extraction"]
    assert features[0][1] == 0
    assert features[-1][1] == features[-1][2]
    assert features[-1][2] > 0

    head = [event[1] for event in events if event[0] == "head_training"]
    assert head == [1, 2]
    assert result.metrics["evaluation"]["accuracy"] >= 0


def test_training_is_deterministic(prepared: tuple[Path, Path], tmp_path: Path) -> None:
    root, manifest = prepared
    first = train(make_config(root, manifest, tmp_path, run_id="run-det-1"))
    second = train(make_config(root, manifest, tmp_path, run_id="run-det-2"))

    for key in ("train_loss", "val_loss", "val_accuracy"):
        assert first.metrics["training"][key] == pytest.approx(
            second.metrics["training"][key], rel=1e-6, abs=1e-6
        )
    assert (
        first.metrics["evaluation"]["accuracy"]
        == second.metrics["evaluation"]["accuracy"]
    )


def test_reloaded_artifact_matches_recorded_accuracy(
    prepared: tuple[Path, Path], tmp_path: Path
) -> None:
    root, manifest = prepared
    result = train(make_config(root, manifest, tmp_path))
    loaded = load_training_artifact(result.model_path)

    val_samples = json.loads(
        (result.run_dir / "dataset-manifest.json").read_text(encoding="utf-8")
    )["samples"]
    val = [sample for sample in val_samples if sample["split"] == "val"]
    transform = loaded.preprocess.transform()
    images = torch.stack([transform(load_image(root / sample["path"])) for sample in val])
    labels = torch.tensor([sample["class_id"] for sample in val], dtype=torch.long)
    with torch.no_grad():
        accuracy = float((loaded.model(images).argmax(dim=1) == labels).float().mean())

    assert loaded.classes == list(CLASSES)
    assert accuracy == pytest.approx(result.metrics["evaluation"]["accuracy"], abs=1e-6)


def test_dataset_digest_mismatch_blocks_training(
    prepared: tuple[Path, Path], tmp_path: Path
) -> None:
    root, manifest = prepared
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["samples"][0]["sha256"] = "0" * 64
    manifest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(TrainingDataRejected) as error:
        train(make_config(root, manifest, tmp_path))
    assert error.value.report.has(Code.DATASET_DIGEST_MISMATCH)


def test_existing_run_directory_is_rejected(
    prepared: tuple[Path, Path], tmp_path: Path
) -> None:
    root, manifest = prepared
    train(make_config(root, manifest, tmp_path, run_id="run-once"))
    with pytest.raises(TrainingError) as error:
        train(make_config(root, manifest, tmp_path, run_id="run-once"))
    assert error.value.code is Code.TRAINING_CONFIG_INVALID


def test_invalid_run_id_is_rejected(
    prepared: tuple[Path, Path], tmp_path: Path
) -> None:
    root, manifest = prepared
    with pytest.raises(TrainingError) as error:
        train(make_config(root, manifest, tmp_path, run_id="bad id!"))
    assert error.value.code is Code.TRAINING_CONFIG_INVALID


def test_weight_digest_mismatch_is_rejected(tmp_path: Path) -> None:
    config = json.loads(WEIGHTS_CONFIG.read_text(encoding="utf-8"))
    entry = config["entries"][0]
    entry["local_path"] = str(WEIGHTS_FILE.resolve())
    entry["sha256"] = "f" * 64
    broken = tmp_path / "configs" / "weights-broken.json"
    broken.parent.mkdir(parents=True)
    broken.write_text(json.dumps(config), encoding="utf-8")

    from backend.classification.model import load_weight_reference

    with pytest.raises(TrainingError) as error:
        load_weight_reference(broken)
    assert error.value.code is Code.TRAINING_WEIGHTS_DIGEST_MISMATCH


def test_missing_weight_file_is_rejected(tmp_path: Path) -> None:
    config = json.loads(WEIGHTS_CONFIG.read_text(encoding="utf-8"))
    entry = config["entries"][0]
    entry["local_path"] = str(tmp_path / "missing.pth")
    broken = tmp_path / "configs" / "weights-missing.json"
    broken.parent.mkdir(parents=True)
    broken.write_text(json.dumps(config), encoding="utf-8")

    from backend.classification.model import load_weight_reference

    with pytest.raises(TrainingError) as error:
        load_weight_reference(broken)
    assert error.value.code is Code.TRAINING_WEIGHTS_MISSING


@pytest.mark.skipif(
    not WEIGHTS_FILE.is_file(), reason="本地未准备预训练权重，跳过真实权重用例"
)
def test_pretrained_training_and_reload(
    prepared: tuple[Path, Path], tmp_path: Path
) -> None:
    root, manifest = prepared
    result = train(
        make_config(
            root,
            manifest,
            tmp_path,
            weights_config=WEIGHTS_CONFIG,
            epochs=1,
            preprocess=PreprocessSpec(width=64, height=64),
        )
    )
    assert result.metrics["model"]["pretrained"] is True
    assert (
        result.metrics["model"]["weights_sha256"]
        == "047dcff4addef86ea5bc2eff13c9614dc11f47ab1160d0a71a25e7db994f4e1f"
    )

    loaded = load_training_artifact(result.model_path, weights_path=WEIGHTS_FILE)
    assert loaded.metadata["model"]["weights_id"] == "mobilenet_v3_small-imagenet"

    tampered = tmp_path / "tampered.pth"
    tampered.write_bytes(WEIGHTS_FILE.read_bytes() + b"\x00")
    with pytest.raises(TrainingError) as error:
        load_training_artifact(result.model_path, weights_path=tampered)
    assert error.value.code is Code.TRAINING_ARTIFACT_INVALID


@pytest.mark.skipif(
    not WEIGHTS_FILE.is_file(), reason="本地未准备预训练权重，跳过命令行用例"
)
def test_cli_train(
    prepared: tuple[Path, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from backend.classification.cli import main

    root, manifest = prepared
    exit_code = main(
        [
            "train",
            "--dataset",
            str(manifest),
            "--data-root",
            str(root),
            "--output",
            str(tmp_path / "runs"),
            "--run-id",
            "run-cli-0001",
            "--weights-config",
            str(WEIGHTS_CONFIG),
            "--epochs",
            "1",
            "--batch-size",
            "8",
            "--threads",
            "2",
            "--image-size",
            "32",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["metrics"]["model"]["pretrained"] is True
    assert Path(payload["run_dir"]).is_dir()


def test_cli_requires_weight_source(
    prepared: tuple[Path, Path], tmp_path: Path
) -> None:
    from backend.classification.cli import main

    root, manifest = prepared
    with pytest.raises(SystemExit):
        main(
            [
                "train",
                "--dataset",
                str(manifest),
                "--data-root",
                str(root),
                "--output",
                str(tmp_path / "runs"),
                "--run-id",
                "run-missing-source",
            ]
        )


def test_training_report_matches_metrics(
    prepared: tuple[Path, Path], tmp_path: Path
) -> None:
    root, manifest = prepared
    result = train(make_config(root, manifest, tmp_path, epochs=1))

    report = load_training_report(result.run_dir)
    metrics = result.metrics
    assert report["accuracy"] == metrics["evaluation"]["accuracy"]
    assert report["classes"] == metrics["dataset"]["classes"]
    assert report["confusion_matrix"] == metrics["evaluation"]["confusion_matrix"]
    assert len(report["per_class_recall"]) == len(report["classes"])
    assert report["best_epoch"] == metrics["training"]["best_epoch"]
    total = sum(sum(row) for row in metrics["evaluation"]["confusion_matrix"])
    assert len(report["samples"]) == total == report["validation_samples"]
    assert all(
        0 <= sample["true_class_id"] < len(report["classes"])
        and 0 <= sample["predicted_class_id"] < len(report["classes"])
        for sample in report["samples"]
    )


def test_training_report_rejects_tampered_metrics(
    prepared: tuple[Path, Path], tmp_path: Path
) -> None:
    root, manifest = prepared
    result = train(make_config(root, manifest, tmp_path, epochs=1))
    metrics_path = result.run_dir / "metrics.json"
    data = json.loads(metrics_path.read_text(encoding="utf-8"))
    data["evaluation"]["accuracy"] = 0.99
    metrics_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(TrainingError) as error:
        load_training_report(result.run_dir)
    assert error.value.code is Code.TRAINING_ARTIFACT_INVALID


def test_training_report_rejects_missing_model(
    prepared: tuple[Path, Path], tmp_path: Path
) -> None:
    root, manifest = prepared
    result = train(make_config(root, manifest, tmp_path, epochs=1))
    (result.run_dir / "model.pt").unlink()

    with pytest.raises(TrainingError) as error:
        load_training_report(result.run_dir)
    assert error.value.code is Code.TRAINING_ARTIFACT_INVALID


def test_report_cli_emits_summary(
    prepared: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from backend.classification.cli import main

    root, manifest = prepared
    result = train(make_config(root, manifest, tmp_path, epochs=1))

    exit_code = main(["report", "--run", str(result.run_dir)])
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["report"]["accuracy"] == result.metrics["evaluation"]["accuracy"]
