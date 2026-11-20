"""训练历史与按运行重新导出测试。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.classification.dataset import build_dataset_manifest
from backend.classification.preprocess import PreprocessSpec
from backend.classification.training import TrainingConfig, train
from backend.contracts.errors import Code
from backend.project.project import (
    PROJECT_FILE,
    ProjectError,
    create_project,
    export_run,
    list_runs,
    load_project,
    publish_training,
    verify_project,
)
from tests.support.images import build_dataset_tree

CLASSES = ("水杯", "书本", "笔袋")
CREATED_AT = "2026-11-17T10:00:00+08:00"


def new_project(tmp_path: Path) -> Path:
    root = tmp_path / "学生 项目"
    create_project(
        root,
        project_id="proj-runs-0001",
        name="运行测试",
        classes=CLASSES,
        created_at=CREATED_AT,
    )
    data = root / "data"
    build_dataset_tree(
        data, classes=CLASSES, train_batches=2, images_per_batch=2
    )
    manifest = build_dataset_manifest(
        data,
        classes=CLASSES,
        dataset_id="ds-runs-0001",
        created_at=datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc),
    )
    (data / "dataset-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    from backend.project.dataset import rebuild_dataset

    rebuild_dataset(root, dataset_id="ds-runs-0001")
    return root


def train_run(root: Path, run_id: str = "run-runs-0001"):
    data = root / "data"
    result = train(
        TrainingConfig(
            run_id=run_id,
            dataset_manifest=data / "dataset-manifest.json",
            dataset_root=data,
            output_root=root / "runs",
            weights_config=None,
            epochs=1,
            batch_size=4,
            threads=1,
            preprocess=PreprocessSpec(width=32, height=32),
        )
    )
    return result


def test_list_runs_empty(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    payload = list_runs(root)
    assert payload["total"] == 0
    assert payload["runs"] == []
    assert payload["current_model_artifact_id"] is None


def test_list_runs_after_training(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    result = train_run(root)
    payload = list_runs(root)
    assert payload["total"] == 1
    entry = payload["runs"][0]
    assert entry["run_id"] == "run-runs-0001"
    assert entry["training_artifact_id"] == result.metrics["run_id"].join(
        ["train-", ""]
    )
    assert entry["registered"] is False
    assert entry["accuracy"] == result.metrics["evaluation"]["accuracy"]
    assert entry["classes"] == list(CLASSES)


def test_list_runs_marks_registered_after_publish(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    result = train_run(root)
    publish_training(root, run_dir=result.run_dir)

    payload = list_runs(root)
    assert payload["runs"][0]["registered"] is True
    assert payload["current_model_artifact_id"] is not None
    project = load_project(root / PROJECT_FILE)
    assert payload["current_model_artifact_id"] == project.current_model_artifact_id


def test_export_run_registers_and_sets_current(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    result = train_run(root)

    exported = export_run(root, run_dir=result.run_dir)
    assert exported["artifact_id"].startswith("art-")
    assert exported["training_artifact_id"] == "train-run-runs-0001"

    project = load_project(root / PROJECT_FILE)
    assert project.current_model_artifact_id == exported["artifact_id"]
    assert {model.kind for model in project.models} == {"training", "export"}
    assert verify_project(root).ok
    assert Path(exported["package_dir"]).is_dir()


def test_export_run_twice_creates_new_artifact(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    result = train_run(root)
    first = export_run(root, run_dir=result.run_dir)
    second = export_run(root, run_dir=result.run_dir)

    assert first["artifact_id"] != second["artifact_id"]
    assert second["artifact_id"].endswith("-2")
    project = load_project(root / PROJECT_FILE)
    assert project.current_model_artifact_id == second["artifact_id"]
    exports = [model for model in project.models if model.kind == "export"]
    assert len(exports) == 2


def test_export_run_rejects_outside_directory(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    outside = tmp_path / "outside" / "run-0001"
    outside.mkdir(parents=True)
    with pytest.raises(ProjectError) as error:
        export_run(root, run_dir=outside)
    assert error.value.code is Code.PROJECT_MODEL_INVALID


def test_export_run_rejects_missing_run(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    with pytest.raises(ProjectError) as error:
        export_run(root, run_dir="runs/missing")
    assert error.value.code is Code.PROJECT_MODEL_INVALID


def test_cli_runs_and_export_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from backend.project.cli import main

    root = new_project(tmp_path)
    result = train_run(root)

    exit_code = main(["runs", "--root", str(root)])
    listed = json.loads(capsys.readouterr().out)
    assert exit_code == 0 and listed["total"] == 1
    assert listed["runs"][0]["registered"] is False

    exit_code = main(
        ["export-run", "--root", str(root), "--run", result.run_dir.name]
    )
    exported = json.loads(capsys.readouterr().out)
    assert exit_code == 0 and exported["ok"] is True, exported
    assert exported["artifact_id"].startswith("art-")

    exit_code = main(["runs", "--root", str(root)])
    listed = json.loads(capsys.readouterr().out)
    assert exit_code == 0 and listed["runs"][0]["registered"] is True
