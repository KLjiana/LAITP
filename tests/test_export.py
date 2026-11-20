"""ONNX 导出与模型产物包发布测试（T05）。"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort
import pytest

from backend.classification.dataset import build_dataset_manifest
from backend.classification.export import ExportConfig, ExportError, export_model
from backend.classification.preprocess import PreprocessSpec, load_image
from backend.classification.training import TrainingConfig, train
from backend.contracts.errors import Code, Report, Stage
from backend.contracts.manifest import validate_model_package
from backend.contracts.runtime_spec import RuntimeProfile
from tests.support.images import build_dataset_tree

CLASSES = ("水杯", "书本", "笔袋")
FIXED_TIME = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)
EXPORTED_AT = datetime(2026, 11, 17, 11, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def trained_run(tmp_path_factory: pytest.TempPathFactory):
    base = tmp_path_factory.mktemp("training")
    root = build_dataset_tree(base / "data", classes=CLASSES, train_batches=3, images_per_batch=2)
    manifest = build_dataset_manifest(
        root, classes=CLASSES, dataset_id="ds-20261117-0200", created_at=FIXED_TIME
    )
    manifest_path = root / "dataset-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    result = train(
        TrainingConfig(
            run_id="run-export-0001",
            dataset_manifest=manifest_path,
            dataset_root=root,
            output_root=base / "runs",
            weights_config=None,
            epochs=1,
            batch_size=8,
            threads=1,
            preprocess=PreprocessSpec(width=32, height=32),
        )
    )
    return result, root


def make_export(tmp_path: Path, training, root: Path, **overrides: Any):
    values: dict[str, Any] = {
        "run_dir": training.run_dir,
        "output_root": tmp_path / "exports",
        "artifact_id": "art-20261117-0200",
        "project_id": "proj-test",
        "data_root": root,
        "created_at": EXPORTED_AT,
    }
    values.update(overrides)
    return ExportConfig(**values)


def test_export_produces_valid_package(
    trained_run, tmp_path: Path
) -> None:
    training, root = trained_run
    result = export_model(make_export(tmp_path, training, root))

    package = result.package_dir
    assert (package / "manifest.json").is_file()
    assert (package / "model.onnx").is_file()
    assert (package / "labels.json").is_file()
    assert result.conversion_record_path.is_file()

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["contract_version"] == "1.0"
    assert manifest["artifact_id"] == "art-20261117-0200"
    assert manifest["provenance"]["source"]["artifact_id"] == "train-run-export-0001"
    assert manifest["provenance"]["run_id"] == "run-export-0001"
    assert manifest["inputs"][0]["shape"] == [1, 3, 32, 32]
    assert manifest["outputs"][0]["shape"] == [1, 3]
    assert manifest["labels"]["count"] == 3
    assert manifest["conversion"]["quantization"]["mode"] == "none"
    assert len(manifest["validation"]["samples"]) == 3

    assert json.loads((package / "labels.json").read_text(encoding="utf-8")) == list(CLASSES)

    record = json.loads(result.conversion_record_path.read_text(encoding="utf-8"))
    assert record["status"] == "passed"
    assert record["checks"]["package_validation"]["ok"] is True
    assert record["checks"]["fixed_samples"]["prediction_agreement"] == 1.0
    assert record["manifest"]["sha256"] == _sha256(result.manifest_path)
    assert record["source"]["manifest_sha256"] == _sha256(
        training.run_dir / "training-artifact.json"
    )

    # T02 校验器必须接受已发布的包
    profile = RuntimeProfile(
        runtime="onnxruntime",
        version=ort.__version__,
        platform="windows-x64",
        capabilities=frozenset({"onnxruntime-cpu"}),
    )
    report = validate_model_package(package, runtime_profile=profile)
    assert report.ok, report.issues


def test_fixed_sample_reference_matches_packaged_model(
    trained_run, tmp_path: Path
) -> None:
    training, root = trained_run
    result = export_model(make_export(tmp_path, training, root))
    package = result.package_dir

    expected = json.loads(
        (package / "validation" / "expected-class-0.json").read_text(encoding="utf-8")
    )
    preprocess = PreprocessSpec.from_dict(expected["input"]["preprocess"])
    image = load_image(package / expected["sample"]["path"]).convert("RGB")
    tensor = preprocess.transform()(image).unsqueeze(0).numpy()
    assert tensor.shape == tuple(expected["input"]["shape"])
    assert _sha256_bytes(tensor.tobytes()) == expected["input"]["tensor_sha256"]

    session = ort.InferenceSession(
        str(package / "model.onnx"), providers=["CPUExecutionProvider"]
    )
    output = session.run(["logits"], {"images": tensor})[0][0]
    assert np.allclose(output, expected["raw_output"], atol=1e-6)
    assert int(np.argmax(output)) == expected["prediction"]["class_id"]
    assert expected["prediction"]["label"] == CLASSES[expected["prediction"]["class_id"]]
    probabilities = np.asarray(expected["probabilities"])
    assert probabilities.sum() == pytest.approx(1.0, abs=1e-5)


def test_existing_artifact_directory_is_rejected(
    trained_run, tmp_path: Path
) -> None:
    training, root = trained_run
    export_model(make_export(tmp_path, training, root))
    with pytest.raises(ExportError) as error:
        export_model(make_export(tmp_path, training, root))
    assert error.value.code is Code.EXPORT_CONFIG_INVALID


@pytest.mark.parametrize("artifact_id", ["bad id", "", "../escape", "art/../x"])
def test_invalid_artifact_id_is_rejected(
    trained_run, tmp_path: Path, artifact_id: str
) -> None:
    training, root = trained_run
    with pytest.raises(ExportError) as error:
        export_model(make_export(tmp_path, training, root, artifact_id=artifact_id))
    assert error.value.code is Code.EXPORT_CONFIG_INVALID


def test_tampered_training_artifact_is_rejected(
    trained_run, tmp_path: Path
) -> None:
    training, root = trained_run
    copied = tmp_path / "run"
    shutil.copytree(training.run_dir, copied)
    record_path = copied / "training-artifact.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["files"]["model.pt"]["sha256"] = "0" * 64
    record_path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(ExportError) as error:
        export_model(make_export(tmp_path, training, root, run_dir=copied))
    assert error.value.code is Code.EXPORT_SOURCE_INVALID


def test_preprocessing_mismatch_is_rejected(
    trained_run, tmp_path: Path
) -> None:
    training, root = trained_run
    copied = tmp_path / "run"
    shutil.copytree(training.run_dir, copied)
    record_path = copied / "training-artifact.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["preprocess"]["width"] = 64
    record_path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(ExportError) as error:
        export_model(make_export(tmp_path, training, root, run_dir=copied))
    assert error.value.code is Code.EXPORT_SOURCE_INVALID


def test_missing_fixed_sample_is_rejected(
    trained_run, tmp_path: Path
) -> None:
    training, root = trained_run
    copied = tmp_path / "run"
    shutil.copytree(training.run_dir, copied)
    data_copy = tmp_path / "data"
    shutil.copytree(root, data_copy)
    manifest = json.loads((copied / "dataset-manifest.json").read_text(encoding="utf-8"))
    val_sample = next(sample for sample in manifest["samples"] if sample["split"] == "val")
    (data_copy / val_sample["path"]).unlink()

    with pytest.raises(ExportError) as error:
        export_model(
            make_export(tmp_path, training, data_copy, run_dir=copied)
        )
    assert error.value.code is Code.EXPORT_SAMPLE_MISSING


def test_validator_rejection_is_not_published(
    trained_run, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    training, root = trained_run
    from backend.classification import export as export_module

    def reject(package, **kwargs):
        report = Report()
        report.add(Code.LABELS_COUNT_MISMATCH, Stage.SCHEMA, "labels.count", "模拟拒绝")
        return report

    monkeypatch.setattr(export_module, "validate_model_package", reject)
    with pytest.raises(ExportError) as error:
        export_model(make_export(tmp_path, training, root))
    assert error.value.code is Code.EXPORT_PACKAGE_REJECTED
    assert not (tmp_path / "exports" / "art-20261117-0200").exists()
    assert not list((tmp_path / "exports").glob(".tmp-*"))


def test_cli_export(trained_run, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from backend.classification.cli import main

    training, root = trained_run
    exit_code = main(
        [
            "export",
            "--run",
            str(training.run_dir),
            "--output",
            str(tmp_path / "exports"),
            "--artifact-id",
            "art-cli-0200",
            "--project-id",
            "proj-test",
            "--data-root",
            str(root),
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert Path(payload["manifest_path"]).is_file()
    assert payload["checks"]["fixed_samples"]["count"] == 3


def test_cli_export_reports_failure(
    trained_run, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from backend.classification.cli import main

    training, root = trained_run
    exit_code = main(
        [
            "export",
            "--run",
            str(training.run_dir),
            "--output",
            str(tmp_path / "exports"),
            "--artifact-id",
            "bad id",
            "--project-id",
            "proj-test",
            "--data-root",
            str(root),
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["issues"][0]["code"] == "EXPORT_CONFIG_INVALID"


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()
