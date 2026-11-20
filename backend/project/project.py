"""学生项目文件（project.json）的创建、读写与校验。

项目使用相对路径，复制到另一台电脑后仍可打开；保存采用临时文件写入后整体替换，
避免意外退出损坏已有记录。当前覆盖项目身份、类别表、数据集清单与模型引用；
采集、训练界面与恢复流程在后续任务补齐。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from ..contracts import integrity, paths, schemas
from ..contracts.errors import Code, Issue, Report, Stage

PROJECT_SCHEMA_NAME = "project.schema.json"
PROJECT_FILE = "project.json"
FORMAT_MAJOR = 1
FORMAT_MINOR = 0
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
KINDS = ("training", "export")


class ProjectError(Exception):
    """项目文件无法读取、校验或保存。``code`` 是稳定错误码。"""

    def __init__(self, code: Code, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ModelReference:
    artifact_id: str
    kind: str
    path: str
    sha256: str
    created_at: str

    def to_dict(self) -> dict[str, str]:
        return {
            "artifact_id": self.artifact_id,
            "kind": self.kind,
            "path": self.path,
            "sha256": self.sha256,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelReference":
        return cls(
            artifact_id=str(data["artifact_id"]),
            kind=str(data["kind"]),
            path=str(data["path"]),
            sha256=str(data["sha256"]),
            created_at=str(data["created_at"]),
        )


@dataclass
class Project:
    project_id: str
    name: str
    classes: list[str]
    created_at: str
    updated_at: str
    task: str = "image_classification"
    project_format: str = f"{FORMAT_MAJOR}.{FORMAT_MINOR}"
    dataset_manifest: str | None = None
    models: list[ModelReference] = field(default_factory=list)
    current_model_artifact_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_format": self.project_format,
            "project_id": self.project_id,
            "name": self.name,
            "task": self.task,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "classes": list(self.classes),
            "dataset_manifest": self.dataset_manifest,
            "models": [item.to_dict() for item in self.models],
            "current_model_artifact_id": self.current_model_artifact_id,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n"

    def current_model(self) -> ModelReference | None:
        if self.current_model_artifact_id is None:
            return None
        return next(
            (
                item
                for item in self.models
                if item.artifact_id == self.current_model_artifact_id
            ),
            None,
        )

    @classmethod
    def from_dict(cls, data: Any) -> "Project":
        if not isinstance(data, dict):
            raise ProjectError(Code.PROJECT_SCHEMA_INVALID, "项目文件顶层必须是 JSON 对象")
        issues = schemas.schema_issues(
            PROJECT_SCHEMA_NAME, data, code=Code.PROJECT_SCHEMA_INVALID
        )
        if issues:
            details = "；".join(f"{issue.location}: {issue.message}" for issue in issues)
            raise ProjectError(Code.PROJECT_SCHEMA_INVALID, details)

        _check_format(str(data["project_format"]))
        classes = _checked_classes(data["classes"])
        _parse_timestamp(str(data["created_at"]))
        _parse_timestamp(str(data["updated_at"]))

        models: list[ModelReference] = []
        seen: set[str] = set()
        for index, item in enumerate(data["models"]):
            reference = ModelReference.from_dict(item)
            _check_model_reference(reference, location=f"models[{index}]")
            if reference.artifact_id in seen:
                raise ProjectError(
                    Code.PROJECT_MODEL_INVALID,
                    f"产物 ID {reference.artifact_id!r} 重复",
                )
            seen.add(reference.artifact_id)
            models.append(reference)

        current = data["current_model_artifact_id"]
        if current is not None and current not in seen:
            raise ProjectError(
                Code.PROJECT_MODEL_INVALID,
                f"当前模型 {current!r} 不在 models 列表中",
            )

        dataset_manifest = data.get("dataset_manifest")
        if dataset_manifest is not None:
            reason = paths.check_rel_path(dataset_manifest)
            if reason is not None:
                raise ProjectError(
                    Code.PROJECT_SCHEMA_INVALID,
                    f"dataset_manifest {dataset_manifest!r}：{reason}",
                )

        return cls(
            project_id=str(data["project_id"]),
            name=str(data["name"]),
            classes=classes,
            created_at=str(data["created_at"]),
            updated_at=str(data["updated_at"]),
            task=str(data["task"]),
            project_format=str(data["project_format"]),
            dataset_manifest=dataset_manifest,
            models=models,
            current_model_artifact_id=current,
        )


def _check_format(text: str) -> None:
    try:
        major_text, minor_text = text.split(".", 1)
        major, minor = int(major_text), int(minor_text)
    except (ValueError, AttributeError):
        raise ProjectError(
            Code.PROJECT_SCHEMA_INVALID, f"项目格式版本 {text!r} 不符合 major.minor"
        ) from None
    if major != FORMAT_MAJOR:
        raise ProjectError(
            Code.PROJECT_VERSION_UNSUPPORTED_MAJOR,
            f"项目格式主版本 {major} 不受支持（当前仅支持 {FORMAT_MAJOR}.x）",
        )
    if minor > FORMAT_MINOR:
        raise ProjectError(
            Code.PROJECT_VERSION_UNSUPPORTED_MINOR,
            f"项目格式次版本 {text} 高于当前支持的 {FORMAT_MAJOR}.{FORMAT_MINOR}",
        )


def _checked_classes(classes: Sequence[str]) -> list[str]:
    if not isinstance(classes, list) or len(classes) < 2:
        raise ProjectError(Code.PROJECT_CLASS_INVALID, "至少需要 2 个类别")
    result: list[str] = []
    seen: set[str] = set()
    for name in classes:
        if not isinstance(name, str) or not name:
            raise ProjectError(Code.PROJECT_CLASS_INVALID, f"类别名 {name!r} 不能为空")
        if name != name.strip():
            raise ProjectError(
                Code.PROJECT_CLASS_INVALID, f"类别名 {name!r} 首尾不能含空白"
            )
        reason = paths.check_rel_path(name)
        if reason is not None:
            raise ProjectError(
                Code.PROJECT_CLASS_INVALID,
                f"类别名 {name!r} 不能用作目录名：{reason}",
            )
        if name in seen:
            raise ProjectError(Code.PROJECT_CLASS_INVALID, f"类别 {name!r} 重复")
        seen.add(name)
        result.append(name)
    return result


def _check_model_reference(reference: ModelReference, *, location: str) -> None:
    if not IDENTIFIER.match(reference.artifact_id):
        raise ProjectError(
            Code.PROJECT_MODEL_INVALID,
            f"{location}.artifact_id {reference.artifact_id!r} 格式非法",
        )
    if reference.kind not in KINDS:
        raise ProjectError(
            Code.PROJECT_MODEL_INVALID, f"{location}.kind {reference.kind!r} 不受支持"
        )
    reason = paths.check_rel_path(reference.path)
    if reason is not None:
        raise ProjectError(
            Code.PROJECT_MODEL_INVALID, f"{location}.path {reference.path!r}：{reason}"
        )
    if not re.fullmatch(r"[0-9a-f]{64}", reference.sha256):
        raise ProjectError(
            Code.PROJECT_MODEL_INVALID, f"{location}.sha256 必须是 64 位小写十六进制"
        )
    _parse_timestamp(reference.created_at)


def _parse_timestamp(text: str) -> datetime:
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        value = datetime.fromisoformat(normalized)
    except ValueError:
        raise ProjectError(
            Code.PROJECT_SCHEMA_INVALID, f"时间戳 {text!r} 不是 RFC 3339 时间"
        ) from None
    if value.tzinfo is None:
        raise ProjectError(
            Code.PROJECT_SCHEMA_INVALID, f"时间戳 {text!r} 缺少时区"
        )
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _project_path(root: str | Path) -> Path:
    return Path(root) / PROJECT_FILE


def load_project(path: str | Path) -> Project:
    project_path = Path(path)
    if project_path.is_dir():
        project_path = project_path / PROJECT_FILE
    try:
        raw = project_path.read_bytes()
    except FileNotFoundError:
        raise ProjectError(
            Code.PROJECT_NOT_FOUND, f"项目文件 {project_path} 不存在"
        ) from None
    except OSError as error:
        raise ProjectError(
            Code.PROJECT_JSON_INVALID,
            f"无法读取项目文件 {project_path}：{error.strerror or error}",
        ) from error
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProjectError(
            Code.PROJECT_JSON_INVALID, f"项目文件不是有效 JSON：{error}"
        ) from error
    return Project.from_dict(data)


def save_project(project: Project, path: str | Path) -> Path:
    project_path = Path(path)
    if project_path.is_dir():
        project_path = project_path / PROJECT_FILE
    project_path.parent.mkdir(parents=True, exist_ok=True)
    # 写盘前重新校验，避免内部修改产生非法项目文件。
    Project.from_dict(project.to_dict())
    temporary = project_path.with_name(
        f".{project_path.name}.tmp-{uuid.uuid4().hex[:8]}"
    )
    try:
        temporary.write_text(project.to_json(), encoding="utf-8")
        os.replace(temporary, project_path)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise ProjectError(
            Code.PROJECT_SAVE_FAILED,
            f"保存项目文件失败：{error.strerror or error}",
        ) from error
    return project_path


def create_project(
    root: str | Path,
    *,
    project_id: str,
    name: str,
    classes: Sequence[str],
    created_at: str | None = None,
) -> Project:
    root = Path(root)
    project_path = _project_path(root)
    if project_path.exists():
        raise ProjectError(
            Code.PROJECT_ALREADY_EXISTS, f"项目文件已存在：{project_path}"
        )
    if not IDENTIFIER.match(project_id):
        raise ProjectError(
            Code.PROJECT_SCHEMA_INVALID, f"project_id {project_id!r} 格式非法"
        )
    timestamp = created_at or _utc_now()
    _parse_timestamp(timestamp)
    project = Project(
        project_id=project_id,
        name=name,
        classes=_checked_classes(list(classes)),
        created_at=timestamp,
        updated_at=timestamp,
    )
    save_project(project, project_path)
    return project


def add_model(
    project: Project,
    *,
    root: str | Path,
    artifact_id: str,
    kind: str,
    path: str,
    sha256: str | None = None,
    created_at: str | None = None,
) -> ModelReference:
    root = Path(root)
    if any(item.artifact_id == artifact_id for item in project.models):
        raise ProjectError(
            Code.PROJECT_MODEL_INVALID, f"产物 ID {artifact_id!r} 已存在"
        )
    target = paths.resolve_in_package(root, path)
    if target is None:
        raise ProjectError(
            Code.PROJECT_MODEL_INVALID, f"模型路径 {path!r} 越出项目目录"
        )
    if not target.is_file():
        raise ProjectError(
            Code.PROJECT_MODEL_INVALID, f"模型文件 {path!r} 不存在"
        )
    actual = integrity.sha256_file(target)
    if sha256 is not None and sha256 != actual:
        raise ProjectError(
            Code.PROJECT_MODEL_DIGEST_MISMATCH,
            f"模型文件摘要 {actual} 与声明 {sha256} 不一致",
        )
    reference = ModelReference(
        artifact_id=artifact_id,
        kind=kind,
        path=path,
        sha256=actual,
        created_at=created_at or _utc_now(),
    )
    _check_model_reference(reference, location="model")
    project.models.append(reference)
    project.updated_at = _utc_now()
    return reference


def set_current_model(project: Project, artifact_id: str) -> None:
    if not any(item.artifact_id == artifact_id for item in project.models):
        raise ProjectError(
            Code.PROJECT_MODEL_INVALID, f"产物 {artifact_id!r} 不在项目模型中"
        )
    project.current_model_artifact_id = artifact_id
    project.updated_at = _utc_now()


def _resolve_run_dir(root: Path, run_dir: str | Path) -> Path:
    candidate = Path(run_dir)
    if candidate.is_absolute():
        options = [candidate]
    else:
        # 允许相对项目根目录（推荐）、项目 runs/ 下的运行 ID 或相对当前目录的写法；
        # 优先选择含训练记录的路径。
        options = [root / candidate, root / "runs" / candidate, Path.cwd() / candidate]
    for option in options:
        if (option / "training-artifact.json").is_file():
            return option.resolve()
    return options[0].resolve()


def _read_training_record(resolved: Path) -> dict[str, Any]:
    record_path = resolved / "training-artifact.json"
    if not record_path.is_file():
        raise ProjectError(
            Code.PROJECT_MODEL_INVALID,
            f"训练目录缺少 training-artifact.json：{resolved}",
        )
    try:
        return json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectError(
            Code.PROJECT_MODEL_INVALID, f"无法读取训练记录：{error}"
        ) from error


def register_training_artifact(
    root: str | Path, *, run_dir: str | Path
) -> ModelReference:
    """把已有训练运行登记到项目；训练产物不是预测模型，因此不设为当前模型。"""
    root = Path(root)
    project = load_project(root / PROJECT_FILE)
    resolved = _resolve_run_dir(root, run_dir)
    try:
        relative = resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        raise ProjectError(
            Code.PROJECT_MODEL_INVALID, f"训练目录 {resolved} 不在项目目录内"
        ) from None
    record = _read_training_record(resolved)
    artifact_id = record.get("artifact_id")
    if not isinstance(artifact_id, str):
        raise ProjectError(Code.PROJECT_MODEL_INVALID, "训练记录缺少 artifact_id")
    reference = add_model(
        project,
        root=root,
        artifact_id=artifact_id,
        kind="training",
        path=f"{relative}/training-artifact.json",
    )
    save_project(project, root / PROJECT_FILE)
    return reference


def register_export(
    root: str | Path, *, artifact_id: str, manifest_path: str
) -> ModelReference:
    """登记 ONNX 模型包并设为当前模型。"""
    root = Path(root)
    project = load_project(root / PROJECT_FILE)
    reference = add_model(
        project,
        root=root,
        artifact_id=artifact_id,
        kind="export",
        path=manifest_path,
    )
    set_current_model(project, artifact_id)
    save_project(project, root / PROJECT_FILE)
    return reference


def _next_artifact_id(exports_root: Path, run_name: str) -> str:
    base = f"art-{run_name}"
    if not (exports_root / base).exists():
        return base
    index = 2
    while (exports_root / f"{base}-{index}").exists():
        index += 1
    return f"{base}-{index}"


def _dataset_root_for_export(root: Path, project: Project, run: Path) -> Path:
    if project.dataset_manifest is not None:
        manifest_path = root / project.dataset_manifest
        if manifest_path.is_file():
            return manifest_path.parent
    config_path = run / "config.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        return Path(config["dataset_root"])
    except (OSError, json.JSONDecodeError, KeyError) as error:
        raise ProjectError(
            Code.PROJECT_MODEL_INVALID,
            f"无法确定导出所需的数据目录：{error}",
        ) from error


def _export_run_package(
    root: Path,
    project: Project,
    resolved: Path,
    *,
    artifact_id: str | None,
    platform: str,
    data_root: str | Path | None,
) -> dict[str, Any]:
    from ..classification.export import ExportConfig, export_model

    exports_root = root / "exports"
    chosen = artifact_id or _next_artifact_id(exports_root, resolved.name)
    if not IDENTIFIER.match(chosen):
        raise ProjectError(
            Code.PROJECT_MODEL_INVALID, f"导出的产物 ID {chosen!r} 格式非法"
        )
    resolved_data_root = (
        Path(data_root)
        if data_root is not None
        else _dataset_root_for_export(root, project, resolved)
    )
    config = ExportConfig(
        run_dir=resolved,
        output_root=exports_root,
        artifact_id=chosen,
        project_id=project.project_id,
        platform=platform,
        data_root=resolved_data_root,
    )
    result = export_model(config)
    manifest_relative = result.manifest_path.relative_to(root).as_posix()
    register_export(root, artifact_id=chosen, manifest_path=manifest_relative)
    return {
        "artifact_id": chosen,
        "package_dir": str(result.package_dir),
        "manifest_path": str(result.manifest_path),
        "conversion_record": str(result.conversion_record_path),
        "checks": result.checks,
    }


def publish_training(
    root: str | Path,
    *,
    run_dir: str | Path,
    artifact_id: str | None = None,
    platform: str = "windows-x64",
    data_root: str | Path | None = None,
) -> dict[str, Any]:
    """登记训练产物，导出 ONNX 模型包并设为当前模型。

    导出失败时项目只保留已登记的训练产物，不会出现“半发布”的当前模型。
    """
    root = Path(root)
    project = load_project(root / PROJECT_FILE)
    resolved = _resolve_run_dir(root, run_dir)
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        raise ProjectError(
            Code.PROJECT_MODEL_INVALID, f"训练目录 {resolved} 不在项目目录内"
        ) from None

    training_reference = register_training_artifact(root, run_dir=resolved)
    project = load_project(root / PROJECT_FILE)
    payload = _export_run_package(
        root,
        project,
        resolved,
        artifact_id=artifact_id,
        platform=platform,
        data_root=data_root,
    )
    return {"training_artifact_id": training_reference.artifact_id, **payload}


def export_run(
    root: str | Path,
    *,
    run_dir: str | Path,
    artifact_id: str | None = None,
    platform: str = "windows-x64",
    data_root: str | Path | None = None,
) -> dict[str, Any]:
    """从已有训练运行重新导出模型包（必要时先登记训练产物），并设为当前模型。"""
    root = Path(root)
    project = load_project(root / PROJECT_FILE)
    resolved = _resolve_run_dir(root, run_dir)
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        raise ProjectError(
            Code.PROJECT_MODEL_INVALID, f"训练目录 {resolved} 不在项目目录内"
        ) from None
    record = _read_training_record(resolved)
    training_id = record.get("artifact_id")
    if not any(item.artifact_id == training_id for item in project.models):
        register_training_artifact(root, run_dir=resolved)
        project = load_project(root / PROJECT_FILE)
    payload = _export_run_package(
        root,
        project,
        resolved,
        artifact_id=artifact_id,
        platform=platform,
        data_root=data_root,
    )
    return {"training_artifact_id": training_id, **payload}


def list_runs(root: str | Path) -> dict[str, Any]:
    """列出项目 runs/ 下的训练运行及其登记、准确率状态。"""
    root = Path(root)
    project = load_project(root / PROJECT_FILE)
    runs_root = root / "runs"
    entries: list[dict[str, Any]] = []
    if runs_root.is_dir():
        for run in sorted(runs_root.iterdir()):
            record_path = run / "training-artifact.json"
            if not record_path.is_file():
                continue
            try:
                record = json.loads(record_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            metrics: dict[str, Any] = {}
            metrics_path = run / "metrics.json"
            if metrics_path.is_file():
                try:
                    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    metrics = {}
            training_id = record.get("artifact_id")
            entries.append(
                {
                    "run_id": record.get("run_id", run.name),
                    "training_artifact_id": training_id,
                    "created_at": metrics.get("created_at") or record.get("created_at"),
                    "accuracy": metrics.get("evaluation", {}).get("accuracy"),
                    "classes": record.get("dataset", {}).get("classes", []),
                    "registered": any(
                        item.artifact_id == training_id for item in project.models
                    ),
                }
            )
    entries.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return {
        "runs": entries,
        "total": len(entries),
        "current_model_artifact_id": project.current_model_artifact_id,
    }


@dataclass
class ProjectEditResult:
    project: Project
    manifest_path: Path | None = None
    manifest_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project.to_dict(),
            "manifest_path": None if self.manifest_path is None else str(self.manifest_path),
            "manifest_error": self.manifest_error,
        }


def _try_rebuild(root: Path) -> tuple[Path | None, str | None]:
    from ..classification.dataset import DatasetError
    from .dataset import rebuild_dataset

    try:
        manifest_path, _ = rebuild_dataset(root)
    except DatasetError as error:
        return None, f"{error.code.value}: {error.message}"
    except ProjectError as error:
        return None, error.message
    return manifest_path, None


def rename_project(root: str | Path, *, name: str) -> ProjectEditResult:
    """修改项目显示名称（不影响类别、数据与模型引用）。"""
    root = Path(root)
    project = load_project(root / PROJECT_FILE)
    project.name = name
    project.updated_at = _utc_now()
    save_project(project, root / PROJECT_FILE)
    return ProjectEditResult(project)


def add_class(root: str | Path, *, name: str) -> ProjectEditResult:
    """在类别表末尾追加类别；已有数据清单会因新类无样本而暂不可重建。"""
    root = Path(root)
    project = load_project(root / PROJECT_FILE)
    if name in project.classes:
        raise ProjectError(Code.PROJECT_CLASS_INVALID, f"类别 {name!r} 已存在")
    project.classes = _checked_classes([*project.classes, name])
    project.updated_at = _utc_now()
    save_project(project, root / PROJECT_FILE)
    manifest_path, manifest_error = _try_rebuild(root)
    return ProjectEditResult(project, manifest_path, manifest_error)


def remove_class(
    root: str | Path, *, name: str, delete_data: bool = False
) -> ProjectEditResult:
    """删除类别；该类仍有数据时必须显式 ``delete_data=True``。"""
    root = Path(root)
    project = load_project(root / PROJECT_FILE)
    if name not in project.classes:
        raise ProjectError(Code.PROJECT_CLASS_INVALID, f"类别 {name!r} 不在项目中")
    if len(project.classes) <= 2:
        raise ProjectError(Code.PROJECT_CLASS_INVALID, "项目至少需要保留 2 个类别")

    data_dirs = [root / "data" / "images" / name, root / "data" / "test-images" / name]
    has_files = any(
        directory.is_dir() and any(path.is_file() for path in directory.rglob("*"))
        for directory in data_dirs
    )
    if has_files and not delete_data:
        raise ProjectError(
            Code.PROJECT_CLASS_INVALID,
            f"类别 {name!r} 仍有图片；如需连同数据删除请显式确认",
        )
    if delete_data:
        for directory in data_dirs:
            if directory.is_dir():
                shutil.rmtree(directory)

    project.classes = [item for item in project.classes if item != name]
    project.updated_at = _utc_now()
    save_project(project, root / PROJECT_FILE)
    manifest_path, manifest_error = _try_rebuild(root)
    return ProjectEditResult(project, manifest_path, manifest_error)


def verify_project(root: str | Path) -> Report:
    root = Path(root)
    report = Report()
    project_path = _project_path(root)
    if not project_path.is_file():
        report.add(
            Code.PROJECT_NOT_FOUND,
            Stage.SCHEMA,
            PROJECT_FILE,
            f"项目文件 {project_path} 不存在",
        )
        return report
    try:
        project = load_project(project_path)
    except ProjectError as error:
        report.add(error.code, Stage.SCHEMA, PROJECT_FILE, error.message)
        return report

    if project.dataset_manifest is not None:
        target = paths.resolve_in_package(root, project.dataset_manifest)
        if target is None or not target.is_file():
            report.add(
                Code.PROJECT_DATASET_MISMATCH,
                Stage.INTEGRITY,
                "dataset_manifest",
                f"数据清单 {project.dataset_manifest!r} 不存在或越出项目目录",
            )
        else:
            try:
                manifest = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                report.add(
                    Code.PROJECT_DATASET_MISMATCH,
                    Stage.INTEGRITY,
                    "dataset_manifest",
                    f"无法读取数据清单：{error}",
                )
            else:
                if list(manifest.get("classes", [])) != project.classes:
                    report.add(
                        Code.PROJECT_DATASET_MISMATCH,
                        Stage.SEMANTICS,
                        "classes",
                        "项目类别表与数据清单类别表不一致，类别 ID 会整体错位",
                    )

    for index, reference in enumerate(project.models):
        target = paths.resolve_in_package(root, reference.path)
        location = f"models[{index}]"
        if target is None or not target.is_file():
            report.add(
                Code.PROJECT_MODEL_INVALID,
                Stage.INTEGRITY,
                f"{location}.path",
                f"模型文件 {reference.path!r} 不存在或越出项目目录",
            )
            continue
        actual = integrity.sha256_file(target)
        if actual != reference.sha256:
            report.add(
                Code.PROJECT_MODEL_DIGEST_MISMATCH,
                Stage.INTEGRITY,
                f"{location}.sha256",
                f"模型文件 {reference.path!r} 实际摘要 {actual} 与记录不一致",
            )

    if project.current_model() is None and project.current_model_artifact_id is not None:
        report.add(
            Code.PROJECT_MODEL_INVALID,
            Stage.SEMANTICS,
            "current_model_artifact_id",
            f"当前模型 {project.current_model_artifact_id!r} 不存在",
        )
    return report
