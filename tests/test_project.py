"""项目文件（project.json）测试。"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.classification.dataset import build_dataset_manifest
from backend.classification.export import ExportError
from backend.classification.preprocess import PreprocessSpec
from backend.classification.training import TrainingConfig, train
from backend.contracts import schemas
from backend.contracts.errors import Code
from backend.project import project as project_module
from backend.project.project import (
    PROJECT_FILE,
    ProjectError,
    add_model,
    create_project,
    load_project,
    publish_training,
    register_export,
    register_training_artifact,
    save_project,
    set_current_model,
    verify_project,
)
from tests.support.images import build_dataset_tree

CLASSES = ("水杯", "书本", "笔袋")
CREATED_AT = "2026-11-17T10:00:00+08:00"


def new_project(tmp_path: Path) -> tuple[Path, object]:
    root = tmp_path / "学生 项目"
    project = create_project(
        root,
        project_id="proj-test-0001",
        name="我的分类项目",
        classes=CLASSES,
        created_at=CREATED_AT,
    )
    return root, project


def add_model_file(root: Path, relative: str = "exports/art-0001/model-package/manifest.json") -> Path:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{"contract_version": "1.0"}', encoding="utf-8")
    return target


def test_create_writes_schema_valid_project(tmp_path: Path) -> None:
    root, project = new_project(tmp_path)
    path = root / PROJECT_FILE
    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert schemas.schema_issues(project_module.PROJECT_SCHEMA_NAME, data) == []
    assert project.classes == list(CLASSES)
    assert project.name == "我的分类项目"

    reloaded = load_project(path)
    assert reloaded.to_dict() == data


def test_create_rejects_duplicate_classes(tmp_path: Path) -> None:
    with pytest.raises(ProjectError) as error:
        create_project(
            tmp_path / "p",
            project_id="proj-0001",
            name="重复类别",
            classes=["水杯", "水杯"],
        )
    assert error.value.code is Code.PROJECT_CLASS_INVALID


def test_create_rejects_existing_project(tmp_path: Path) -> None:
    root, _ = new_project(tmp_path)
    with pytest.raises(ProjectError) as error:
        create_project(root, project_id="proj-0002", name="重复", classes=CLASSES)
    assert error.value.code is Code.PROJECT_ALREADY_EXISTS


@pytest.mark.parametrize(
    ("version", "code"),
    [
        ("2.0", Code.PROJECT_VERSION_UNSUPPORTED_MAJOR),
        ("1.1", Code.PROJECT_VERSION_UNSUPPORTED_MINOR),
    ],
)
def test_unsupported_project_versions(
    tmp_path: Path, version: str, code: Code
) -> None:
    root, _ = new_project(tmp_path)
    path = root / PROJECT_FILE
    data = json.loads(path.read_text(encoding="utf-8"))
    data["project_format"] = version
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ProjectError) as error:
        load_project(path)
    assert error.value.code is code


def test_load_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ProjectError) as error:
        load_project(tmp_path / "missing" / PROJECT_FILE)
    assert error.value.code is Code.PROJECT_NOT_FOUND


def test_load_rejects_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / PROJECT_FILE
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ProjectError) as error:
        load_project(path)
    assert error.value.code is Code.PROJECT_JSON_INVALID


def test_load_rejects_missing_required_field(tmp_path: Path) -> None:
    root, _ = new_project(tmp_path)
    path = root / PROJECT_FILE
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["name"]
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ProjectError) as error:
        load_project(path)
    assert error.value.code is Code.PROJECT_SCHEMA_INVALID


def test_load_rejects_absolute_model_path(tmp_path: Path) -> None:
    root, _ = new_project(tmp_path)
    path = root / PROJECT_FILE
    data = json.loads(path.read_text(encoding="utf-8"))
    data["models"] = [
        {
            "artifact_id": "art-0001",
            "kind": "export",
            "path": "/data/manifest.json",
            "sha256": "0" * 64,
            "created_at": CREATED_AT,
        }
    ]
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ProjectError) as error:
        load_project(path)
    assert error.value.code is Code.PROJECT_SCHEMA_INVALID


def test_add_model_computes_digest_and_persists(tmp_path: Path) -> None:
    root, project = new_project(tmp_path)
    target = add_model_file(root)
    reference = add_model(
        project,
        root=root,
        artifact_id="art-0001",
        kind="export",
        path="exports/art-0001/model-package/manifest.json",
    )
    assert reference.sha256 == __import__("hashlib").sha256(target.read_bytes()).hexdigest()
    save_project(project, root / PROJECT_FILE)

    reloaded = load_project(root / PROJECT_FILE)
    assert len(reloaded.models) == 1
    assert reloaded.models[0].sha256 == reference.sha256


def test_add_model_missing_file_is_rejected(tmp_path: Path) -> None:
    root, project = new_project(tmp_path)
    with pytest.raises(ProjectError) as error:
        add_model(
            project,
            root=root,
            artifact_id="art-0002",
            kind="export",
            path="exports/missing/manifest.json",
        )
    assert error.value.code is Code.PROJECT_MODEL_INVALID


def test_add_model_digest_mismatch_is_rejected(tmp_path: Path) -> None:
    root, project = new_project(tmp_path)
    add_model_file(root)
    with pytest.raises(ProjectError) as error:
        add_model(
            project,
            root=root,
            artifact_id="art-0003",
            kind="export",
            path="exports/art-0001/model-package/manifest.json",
            sha256="f" * 64,
        )
    assert error.value.code is Code.PROJECT_MODEL_DIGEST_MISMATCH


def test_add_model_duplicate_id_is_rejected(tmp_path: Path) -> None:
    root, project = new_project(tmp_path)
    add_model_file(root)
    add_model(project, root=root, artifact_id="art-0001", kind="export",
              path="exports/art-0001/model-package/manifest.json")
    with pytest.raises(ProjectError) as error:
        add_model(project, root=root, artifact_id="art-0001", kind="export",
                  path="exports/art-0001/model-package/manifest.json")
    assert error.value.code is Code.PROJECT_MODEL_INVALID


def test_add_model_path_escape_is_rejected(tmp_path: Path) -> None:
    root, project = new_project(tmp_path)
    with pytest.raises(ProjectError) as error:
        add_model(project, root=root, artifact_id="art-0004", kind="export",
                  path="../outside/manifest.json")
    assert error.value.code is Code.PROJECT_MODEL_INVALID


def test_set_current_model(tmp_path: Path) -> None:
    root, project = new_project(tmp_path)
    add_model_file(root)
    add_model(project, root=root, artifact_id="art-0001", kind="export",
              path="exports/art-0001/model-package/manifest.json")
    set_current_model(project, "art-0001")
    save_project(project, root / PROJECT_FILE)

    reloaded = load_project(root / PROJECT_FILE)
    assert reloaded.current_model_artifact_id == "art-0001"
    assert reloaded.current_model() is not None
    assert reloaded.current_model().artifact_id == "art-0001"


def test_set_current_unknown_model_is_rejected(tmp_path: Path) -> None:
    _, project = new_project(tmp_path)
    with pytest.raises(ProjectError) as error:
        set_current_model(project, "art-missing")
    assert error.value.code is Code.PROJECT_MODEL_INVALID


def test_save_is_atomic_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, project = new_project(tmp_path)
    path = root / PROJECT_FILE
    original = path.read_text(encoding="utf-8")

    def broken_replace(source, target):
        raise OSError(13, "模拟写入失败")

    monkeypatch.setattr(project_module.os, "replace", broken_replace)
    project.name = "改名失败"
    with pytest.raises(ProjectError) as error:
        save_project(project, path)
    assert error.value.code is Code.PROJECT_SAVE_FAILED
    assert path.read_text(encoding="utf-8") == original
    assert not list(root.glob(".project.json.tmp-*"))


def _build_manifest(root: Path) -> Path:
    data_root = root / "data"
    build_dataset_tree(data_root, classes=CLASSES, train_batches=2, images_per_batch=2)
    manifest = build_dataset_manifest(
        data_root,
        classes=CLASSES,
        dataset_id="ds-project-0001",
        created_at=datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc),
    )
    path = data_root / "dataset-manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _train_into_project(root: Path):
    data_root = root / "data"
    build_dataset_tree(data_root, classes=CLASSES, train_batches=2, images_per_batch=2)
    manifest = build_dataset_manifest(
        data_root,
        classes=CLASSES,
        dataset_id="ds-project-0002",
        created_at=datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc),
    )
    manifest_path = data_root / "dataset-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    result = train(
        TrainingConfig(
            run_id="run-project-0001",
            dataset_manifest=manifest_path,
            dataset_root=data_root,
            output_root=root / "runs",
            weights_config=None,
            epochs=1,
            batch_size=4,
            threads=1,
            preprocess=PreprocessSpec(width=32, height=32),
        )
    )
    return result


def test_register_training_artifact(tmp_path: Path) -> None:
    root, project = new_project(tmp_path)
    result = _train_into_project(root)
    project.dataset_manifest = "data/dataset-manifest.json"
    save_project(project, root / PROJECT_FILE)

    reference = register_training_artifact(root, run_dir=result.run_dir)
    assert reference.kind == "training"
    assert reference.path == "runs/run-project-0001/training-artifact.json"

    reloaded = load_project(root / PROJECT_FILE)
    assert reloaded.current_model_artifact_id is None
    assert reloaded.models[0].artifact_id == reference.artifact_id
    assert verify_project(root).ok


def test_register_training_outside_project_is_rejected(tmp_path: Path) -> None:
    root, _ = new_project(tmp_path)
    outside = tmp_path / "outside" / "run-0001"
    outside.mkdir(parents=True)
    with pytest.raises(ProjectError) as error:
        register_training_artifact(root, run_dir=outside)
    assert error.value.code is Code.PROJECT_MODEL_INVALID


def test_register_training_without_record_is_rejected(tmp_path: Path) -> None:
    root, _ = new_project(tmp_path)
    (root / "runs" / "run-empty").mkdir(parents=True)
    with pytest.raises(ProjectError) as error:
        register_training_artifact(root, run_dir="runs/run-empty")
    assert error.value.code is Code.PROJECT_MODEL_INVALID


def test_register_export_sets_current_model(tmp_path: Path) -> None:
    root, _ = new_project(tmp_path)
    manifest = root / "exports" / "art-exp-0001" / "model-package" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"contract_version": "1.0"}', encoding="utf-8")

    reference = register_export(
        root,
        artifact_id="art-exp-0001",
        manifest_path="exports/art-exp-0001/model-package/manifest.json",
    )
    reloaded = load_project(root / PROJECT_FILE)
    assert reference.kind == "export"
    assert reloaded.current_model_artifact_id == "art-exp-0001"
    assert verify_project(root).ok


def test_publish_training_exports_and_sets_current(tmp_path: Path) -> None:
    root, project = new_project(tmp_path)
    result = _train_into_project(root)
    project.dataset_manifest = "data/dataset-manifest.json"
    save_project(project, root / PROJECT_FILE)

    published = publish_training(root, run_dir=result.run_dir, platform="windows-x64")

    assert published["artifact_id"].startswith("art-")
    assert published["training_artifact_id"].startswith("train-")
    package = Path(published["package_dir"])
    assert (package / "manifest.json").is_file()
    assert (package / "labels.json").is_file()
    assert (package / "model.onnx").is_file()

    reloaded = load_project(root / PROJECT_FILE)
    assert reloaded.current_model_artifact_id == published["artifact_id"]
    assert {model.kind for model in reloaded.models} == {"training", "export"}
    assert verify_project(root).ok


def test_publish_training_failure_does_not_set_current(tmp_path: Path) -> None:
    root, project = new_project(tmp_path)
    result = _train_into_project(root)
    project.dataset_manifest = "data/dataset-manifest.json"
    save_project(project, root / PROJECT_FILE)
    (result.run_dir / "model.pt").unlink()

    with pytest.raises(ExportError):
        publish_training(root, run_dir=result.run_dir)

    reloaded = load_project(root / PROJECT_FILE)
    assert reloaded.current_model_artifact_id is None
    assert [model.kind for model in reloaded.models] == ["training"]


def test_cli_publish_training(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from backend.project.cli import main

    root, project = new_project(tmp_path)
    result = _train_into_project(root)
    project.dataset_manifest = "data/dataset-manifest.json"
    save_project(project, root / PROJECT_FILE)

    exit_code = main(
        ["publish-training", "--root", str(root), "--run", str(result.run_dir)]
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0 and payload["ok"] is True
    assert Path(payload["package_dir"]).is_dir()


def test_verify_passes_with_dataset_and_model(tmp_path: Path) -> None:
    root, project = new_project(tmp_path)
    _build_manifest(root)
    project.dataset_manifest = "data/dataset-manifest.json"
    add_model_file(root)
    add_model(project, root=root, artifact_id="art-0001", kind="export",
              path="exports/art-0001/model-package/manifest.json")
    set_current_model(project, "art-0001")
    save_project(project, root / PROJECT_FILE)

    report = verify_project(root)
    assert report.ok, report.issues


def test_verify_detects_missing_dataset(tmp_path: Path) -> None:
    root, project = new_project(tmp_path)
    project.dataset_manifest = "data/missing.json"
    save_project(project, root / PROJECT_FILE)
    report = verify_project(root)
    assert report.has(Code.PROJECT_DATASET_MISMATCH)


def test_verify_detects_class_order_mismatch(tmp_path: Path) -> None:
    root, project = new_project(tmp_path)
    manifest_path = _build_manifest(root)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["classes"] = list(reversed(data["classes"]))
    manifest_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    project.dataset_manifest = "data/dataset-manifest.json"
    save_project(project, root / PROJECT_FILE)

    report = verify_project(root)
    assert report.has(Code.PROJECT_DATASET_MISMATCH)


def test_verify_detects_model_digest_mismatch(tmp_path: Path) -> None:
    root, project = new_project(tmp_path)
    target = add_model_file(root)
    add_model(project, root=root, artifact_id="art-0001", kind="export",
              path="exports/art-0001/model-package/manifest.json")
    save_project(project, root / PROJECT_FILE)
    target.write_text('{"contract_version": "1.1"}', encoding="utf-8")

    report = verify_project(root)
    assert report.has(Code.PROJECT_MODEL_DIGEST_MISMATCH)


def test_project_survives_copy_with_relative_paths(tmp_path: Path) -> None:
    root, project = new_project(tmp_path)
    add_model_file(root)
    add_model(project, root=root, artifact_id="art-0001", kind="export",
              path="exports/art-0001/model-package/manifest.json")
    save_project(project, root / PROJECT_FILE)

    copied = tmp_path / "复制 项目"
    shutil.copytree(root, copied)
    reloaded = load_project(copied / PROJECT_FILE)
    assert reloaded.models[0].path == "exports/art-0001/model-package/manifest.json"
    assert verify_project(copied).ok


def test_cli_create_inspect_and_verify(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from backend.project.cli import main

    root = tmp_path / "cli 项目"
    exit_code = main(
        [
            "create",
            "--root",
            str(root),
            "--project-id",
            "proj-cli-0001",
            "--name",
            "命令行项目",
            "--classes",
            *CLASSES,
        ]
    )
    created = json.loads(capsys.readouterr().out)
    assert exit_code == 0 and created["ok"] is True

    exit_code = main(["inspect", str(root / PROJECT_FILE)])
    inspected = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert inspected["summary"]["classes"] == list(CLASSES)

    exit_code = main(["verify", "--root", str(root)])
    verified = json.loads(capsys.readouterr().out)
    assert exit_code == 0 and verified["ok"] is True


def test_cli_create_generates_project_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from backend.project.cli import main

    exit_code = main(
        [
            "create",
            "--root",
            str(tmp_path / "自动项目"),
            "--name",
            "自动编号项目",
            "--classes",
            *CLASSES,
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    project_id = payload["project"]["project_id"]
    assert project_id.startswith("proj-")
    assert len(project_id) > len("proj-")


def test_cli_add_model_and_set_current(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from backend.project.cli import main

    root = tmp_path / "cli 项目"
    main(["create", "--root", str(root), "--project-id", "proj-cli-0002",
          "--name", "命令行项目", "--classes", *CLASSES])
    capsys.readouterr()
    add_model_file(root)
    exit_code = main(
        ["add-model", "--root", str(root), "--artifact-id", "art-cli-0001",
         "--kind", "export", "--path", "exports/art-0001/model-package/manifest.json"]
    )
    added = json.loads(capsys.readouterr().out)
    assert exit_code == 0 and added["ok"] is True

    exit_code = main(
        ["set-current", "--root", str(root), "--artifact-id", "art-cli-0001"]
    )
    current = json.loads(capsys.readouterr().out)
    assert exit_code == 0 and current["current_model_artifact_id"] == "art-cli-0001"
