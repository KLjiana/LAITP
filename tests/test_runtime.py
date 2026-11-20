"""独立推理运行时测试（T06）。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from backend.classification.dataset import build_dataset_manifest
from backend.classification.export import ExportConfig, export_model
from backend.classification.preprocess import PreprocessSpec
from backend.classification.training import TrainingConfig, train
from backend.contracts.errors import Code
from tests.support.images import build_dataset_tree

CLASSES = ("水杯", "书本", "笔袋")
FIXED_TIME = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)
EXPORTED_AT = datetime(2026, 11, 17, 11, 0, tzinfo=timezone.utc)
REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def package(tmp_path_factory: pytest.TempPathFactory):
    base = tmp_path_factory.mktemp("runtime")
    root = build_dataset_tree(
        base / "data", classes=CLASSES, train_batches=3, images_per_batch=2
    )
    manifest = build_dataset_manifest(
        root,
        classes=CLASSES,
        dataset_id="ds-20261117-0300",
        created_at=FIXED_TIME,
    )
    manifest_path = root / "dataset-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    training = train(
        TrainingConfig(
            run_id="run-runtime-0001",
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
    export = export_model(
        ExportConfig(
            run_dir=training.run_dir,
            output_root=base / "exports",
            artifact_id="art-runtime-0001",
            project_id="proj-test",
            data_root=root,
            created_at=EXPORTED_AT,
        )
    )
    return export.package_dir, manifest, root


def run_cli(*args: str) -> tuple[int, dict[str, Any]]:
    from backend.runtime.cli import main

    import io
    import contextlib

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        exit_code = main(list(args))
    return exit_code, json.loads(buffer.getvalue())


def copy_package(package: Path, tmp_path: Path, name: str = "pkg-copy") -> Path:
    target = tmp_path / name
    shutil.copytree(package, target)
    return target


def rewrite_manifest_entry(package: Path, relative: str) -> None:
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    data = (package / relative).read_bytes()
    for entry in manifest["files"]:
        if entry["path"] == relative:
            entry["sha256"] = hashlib.sha256(data).hexdigest()
            entry["size_bytes"] = len(data)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def val_image(package_root: Path, manifest: dict[str, Any]) -> Path:
    sample = next(item for item in manifest["samples"] if item["split"] == "val")
    return package_root / sample["path"]


def test_validate_passes_fixed_samples(package) -> None:
    package_dir, _, _ = package
    exit_code, payload = run_cli("validate", "--package", str(package_dir))
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["checks"]["fixed_samples"]["passed"] is True
    assert payload["checks"]["fixed_samples"]["count"] == 3
    assert payload["checks"]["fixed_samples"]["max_abs_diff"] == 0.0


def test_predict_returns_all_classes(package) -> None:
    package_dir, manifest, root = package
    image = val_image(root, manifest)
    exit_code, payload = run_cli(
        "predict", "--package", str(package_dir), "--image", str(image)
    )
    assert exit_code == 0
    assert payload["artifact_id"] == "art-runtime-0001"
    assert len(payload["predictions"]) == 3
    assert {item["label"] for item in payload["predictions"]} == set(CLASSES)
    assert {item["class_id"] for item in payload["predictions"]} == {0, 1, 2}
    for item in payload["predictions"]:
        assert item["label"] == CLASSES[item["class_id"]]
    total = sum(item["probability"] for item in payload["predictions"])
    assert total == pytest.approx(1.0, abs=1e-5)
    assert payload["top_prediction"]["class_id"] == max(
        payload["predictions"], key=lambda item: item["probability"]
    )["class_id"]
    assert payload["input_shape"] == [1, 3, 32, 32]


def test_predict_top_k(package) -> None:
    package_dir, manifest, root = package
    image = val_image(root, manifest)
    exit_code, payload = run_cli(
        "predict",
        "--package",
        str(package_dir),
        "--image",
        str(image),
        "--top-k",
        "2",
    )
    assert exit_code == 0
    assert len(payload["predictions"]) == 2


def test_predict_rejects_invalid_image(package, tmp_path: Path) -> None:
    package_dir, _, _ = package
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")
    exit_code, payload = run_cli(
        "predict", "--package", str(package_dir), "--image", str(broken)
    )
    assert exit_code == 1
    assert payload["issues"][0]["code"] == Code.RUNTIME_IMAGE_INVALID.value


def test_predict_rejects_tampered_model(package, tmp_path: Path) -> None:
    package_dir, manifest, root = package
    tampered = copy_package(package_dir, tmp_path)
    with (tampered / "model.onnx").open("ab") as handle:
        handle.write(b"\x00")
    exit_code, payload = run_cli(
        "predict",
        "--package",
        str(tampered),
        "--image",
        str(val_image(root, manifest)),
    )
    assert exit_code == 1
    assert any(
        issue["code"] == Code.FILE_DIGEST_MISMATCH.value for issue in payload["issues"]
    )


def test_validate_detects_reference_mismatch(package, tmp_path: Path) -> None:
    package_dir, _, _ = package
    tampered = copy_package(package_dir, tmp_path)
    expected_path = tampered / "validation" / "expected-class-0.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    expected["raw_output"] = [value + 10.0 for value in expected["raw_output"]]
    expected_path.write_text(json.dumps(expected, ensure_ascii=False), encoding="utf-8")
    rewrite_manifest_entry(tampered, "validation/expected-class-0.json")

    exit_code, payload = run_cli("validate", "--package", str(tampered))
    assert exit_code == 1
    assert any(
        issue["code"] == Code.RUNTIME_FIXED_SAMPLE_MISMATCH.value
        for issue in payload["issues"]
    )


def test_validate_detects_input_preprocessing_drift(package, tmp_path: Path) -> None:
    package_dir, _, _ = package
    tampered = copy_package(package_dir, tmp_path)
    expected_path = tampered / "validation" / "expected-class-0.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    expected["input"]["tensor_sha256"] = "0" * 64
    expected_path.write_text(json.dumps(expected, ensure_ascii=False), encoding="utf-8")
    rewrite_manifest_entry(tampered, "validation/expected-class-0.json")

    exit_code, payload = run_cli("validate", "--package", str(tampered))
    assert exit_code == 1
    assert any(
        issue["code"] == Code.RUNTIME_INPUT_MISMATCH.value
        for issue in payload["issues"]
    )


def test_evaluate_reports_metrics(package) -> None:
    package_dir, manifest, root = package
    exit_code, payload = run_cli(
        "evaluate",
        "--package",
        str(package_dir),
        "--manifest",
        str(root / "dataset-manifest.json"),
        "--data-root",
        str(root),
        "--split",
        "test",
    )
    assert exit_code == 0
    counts = payload["counts"]
    assert counts["samples"] == 3
    assert counts["correct"] + counts["incorrect"] == counts["samples"]
    matrix = payload["confusion_matrix"]
    assert len(matrix) == 3 and all(len(row) == 3 for row in matrix)
    assert sum(sum(row) for row in matrix) == counts["samples"]
    assert payload["accuracy"] == pytest.approx(counts["correct"] / counts["samples"])
    assert len(payload["misclassifications"]) == counts["incorrect"]
    assert len(payload["per_class_recall"]) == 3
    for index in range(3):
        row_total = sum(matrix[index])
        expected_recall = matrix[index][index] / row_total
        assert payload["per_class_recall"][index] == pytest.approx(expected_recall)


def test_evaluate_rejects_class_order_mismatch(package, tmp_path: Path) -> None:
    package_dir, manifest, root = package
    modified = json.loads(json.dumps(manifest))
    modified["classes"] = list(reversed(modified["classes"]))
    manifest_path = tmp_path / "dataset-manifest.json"
    manifest_path.write_text(json.dumps(modified, ensure_ascii=False), encoding="utf-8")

    exit_code, payload = run_cli(
        "evaluate",
        "--package",
        str(package_dir),
        "--manifest",
        str(manifest_path),
        "--data-root",
        str(root),
        "--split",
        "test",
    )
    assert exit_code == 1
    assert any(
        issue["code"] == Code.RUNTIME_CONFIG_INVALID.value for issue in payload["issues"]
    )


def test_evaluate_accepts_test_only_manifest(package, tmp_path: Path) -> None:
    package_dir, manifest, root = package
    test_only = {
        **{key: value for key, value in manifest.items() if key != "samples"},
        "samples": [item for item in manifest["samples"] if item["split"] == "test"],
    }
    manifest_path = tmp_path / "test-only.json"
    manifest_path.write_text(json.dumps(test_only, ensure_ascii=False), encoding="utf-8")

    exit_code, payload = run_cli(
        "evaluate",
        "--package",
        str(package_dir),
        "--manifest",
        str(manifest_path),
        "--data-root",
        str(root),
        "--split",
        "test",
    )
    assert exit_code == 0
    assert payload["counts"]["samples"] == 3

    exit_code, payload = run_cli(
        "evaluate",
        "--package",
        str(package_dir),
        "--manifest",
        str(manifest_path),
        "--data-root",
        str(root),
        "--split",
        "val",
    )
    assert exit_code == 1
    assert any(
        issue["code"] == Code.RUNTIME_CONFIG_INVALID.value for issue in payload["issues"]
    )


def test_unsupported_preprocessing_is_rejected(package, tmp_path: Path) -> None:
    package_dir, manifest, root = package
    tampered = copy_package(package_dir, tmp_path)
    manifest_path = tampered / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    step = data["preprocessing"]["steps"][0]
    step["mode"] = "letterbox"
    step["pad_color"] = [0, 0, 0]
    step["pad_position"] = "center"
    manifest_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    exit_code, payload = run_cli(
        "predict",
        "--package",
        str(tampered),
        "--image",
        str(val_image(root, manifest)),
    )
    assert exit_code == 1
    assert any(
        issue["code"] == Code.RUNTIME_PREPROCESSING_UNSUPPORTED.value
        for issue in payload["issues"]
    )


def test_package_path_with_chinese_and_spaces(package, tmp_path: Path) -> None:
    package_dir, manifest, root = package
    target = tmp_path / "学生 项目" / "模型 包 v1"
    shutil.copytree(package_dir, target)
    exit_code, payload = run_cli(
        "predict",
        "--package",
        str(target),
        "--image",
        str(val_image(root, manifest)),
    )
    assert exit_code == 0
    assert payload["artifact_id"] == "art-runtime-0001"


def test_cli_runs_in_independent_process(package, tmp_path: Path) -> None:
    package_dir, manifest, root = package
    isolated = copy_package(package_dir, tmp_path, "isolated-package")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backend.runtime",
            "predict",
            "--package",
            str(isolated),
            "--image",
            str(val_image(root, manifest)),
        ],
        capture_output=True,
        cwd=tmp_path,
        env=environment,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    payload = json.loads(result.stdout.decode("utf-8"))
    assert payload["ok"] is True
    assert payload["artifact_id"] == "art-runtime-0001"
