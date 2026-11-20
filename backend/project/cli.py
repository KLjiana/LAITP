"""项目文件命令行（M1 基础）：创建、查看、校验模型引用。

标准输出为 UTF-8 JSON，退出码 0 表示成功、1 表示失败。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from ..classification.dataset import DatasetError
from ..console import emit_json
from ..contracts.errors import Code, Issue, Report, Stage
from .dataset import (
    check_dataset,
    delete_sample,
    import_images,
    import_tree,
    list_samples,
    rebuild_dataset,
    rename_class,
    rename_sample,
)
from .project import (
    PROJECT_FILE,
    ProjectEditResult,
    ProjectError,
    add_class,
    add_model,
    create_project,
    export_run,
    list_runs,
    load_project,
    publish_training,
    register_export,
    register_training_artifact,
    remove_class,
    rename_project,
    save_project,
    set_current_model,
    verify_project,
)

_INTEGRITY_CODES = {
    Code.PROJECT_MODEL_INVALID,
    Code.PROJECT_MODEL_DIGEST_MISMATCH,
    Code.PROJECT_DATASET_MISMATCH,
}

_STAGE_BY_CODE = {
    Code.PROJECT_JSON_INVALID: Stage.SCHEMA,
    Code.PROJECT_SCHEMA_INVALID: Stage.SCHEMA,
    Code.PROJECT_VERSION_UNSUPPORTED_MAJOR: Stage.SCHEMA,
    Code.PROJECT_VERSION_UNSUPPORTED_MINOR: Stage.SCHEMA,
    Code.PROJECT_ALREADY_EXISTS: Stage.SCHEMA,
    Code.PROJECT_NOT_FOUND: Stage.SCHEMA,
    Code.PROJECT_CLASS_INVALID: Stage.LABELS,
    Code.PROJECT_SAVE_FAILED: Stage.INTEGRITY,
}


def _stage_for(code: Code) -> Stage:
    if code in _INTEGRITY_CODES:
        return Stage.INTEGRITY
    return _STAGE_BY_CODE.get(code, Stage.SEMANTICS)


def _fail(error: ProjectError) -> int:
    report = Report(
        [Issue(error.code, _stage_for(error.code), "$", error.message)]
    )
    emit_json({"ok": False, **report.to_dict()})
    return 1


def _create(args: argparse.Namespace) -> int:
    project_id = args.project_id or (
        f"proj-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"
    )
    try:
        project = create_project(
            Path(args.root),
            project_id=project_id,
            name=args.name,
            classes=args.classes,
        )
    except ProjectError as error:
        return _fail(error)
    emit_json(
        {
            "ok": True,
            "project_path": str(Path(args.root) / PROJECT_FILE),
            "project": project.to_dict(),
        }
    )
    return 0


def _load(root: Path):
    return load_project(root / PROJECT_FILE)


def _inspect(args: argparse.Namespace) -> int:
    try:
        project = load_project(Path(args.project))
    except ProjectError as error:
        return _fail(error)
    emit_json(
        {
            "ok": True,
            "project": project.to_dict(),
            "summary": {
                "format": project.project_format,
                "classes": project.classes,
                "models": len(project.models),
                "current_model": project.current_model_artifact_id,
                "dataset_manifest": project.dataset_manifest,
            },
        }
    )
    return 0


def _verify(args: argparse.Namespace) -> int:
    report = verify_project(Path(args.root))
    emit_json({"ok": report.ok, "root": str(Path(args.root)), **report.to_dict()})
    return 0 if report.ok else 1


def _add_model(args: argparse.Namespace) -> int:
    root = Path(args.root)
    try:
        project = _load(root)
        reference = add_model(
            project,
            root=root,
            artifact_id=args.artifact_id,
            kind=args.kind,
            path=args.path,
            sha256=args.sha256,
        )
        save_project(project, root / PROJECT_FILE)
    except ProjectError as error:
        return _fail(error)
    emit_json({"ok": True, "model": reference.to_dict(), "project": project.to_dict()})
    return 0


def _set_current(args: argparse.Namespace) -> int:
    root = Path(args.root)
    try:
        project = _load(root)
        set_current_model(project, args.artifact_id)
        save_project(project, root / PROJECT_FILE)
    except ProjectError as error:
        return _fail(error)
    emit_json(
        {
            "ok": True,
            "current_model_artifact_id": project.current_model_artifact_id,
            "project": project.to_dict(),
        }
    )
    return 0


def _register_training(args: argparse.Namespace) -> int:
    try:
        reference = register_training_artifact(Path(args.root), run_dir=args.run)
    except ProjectError as error:
        return _fail(error)
    emit_json({"ok": True, "model": reference.to_dict()})
    return 0


def _register_export(args: argparse.Namespace) -> int:
    try:
        reference = register_export(
            Path(args.root),
            artifact_id=args.artifact_id,
            manifest_path=args.manifest,
        )
    except ProjectError as error:
        return _fail(error)
    emit_json({"ok": True, "model": reference.to_dict()})
    return 0


def _publish_training(args: argparse.Namespace) -> int:
    from ..classification.export import ExportError

    try:
        result = publish_training(
            Path(args.root),
            run_dir=args.run,
            artifact_id=args.artifact_id,
            platform=args.platform,
            data_root=Path(args.data_root) if args.data_root else None,
        )
    except ExportError as error:
        issues = [Issue(error.code, Stage.ARTIFACTS.value, "$", error.message)]
        issues.extend(error.issues)
        emit_json({"ok": False, **Report(issues).to_dict()})
        return 1
    except ProjectError as error:
        return _fail(error)
    emit_json({"ok": True, **result})
    return 0


def _import_images(args: argparse.Namespace) -> int:
    try:
        result = import_images(
            Path(args.root),
            class_name=args.class_name,
            source_dir=args.source,
            split=args.split,
            batch=args.batch,
        )
    except ProjectError as error:
        return _fail(error)
    emit_json({"ok": True, **result.to_dict()})
    return 0


def _import_tree(args: argparse.Namespace) -> int:
    try:
        result = import_tree(
            Path(args.root),
            source_dir=args.source,
            split=args.split,
            batch=args.batch,
        )
    except ProjectError as error:
        return _fail(error)
    emit_json({"ok": True, **result.to_dict()})
    return 0


def _rebuild_dataset(args: argparse.Namespace) -> int:
    try:
        manifest_path, manifest = rebuild_dataset(
            Path(args.root), dataset_id=args.dataset_id
        )
    except DatasetError as error:
        report = Report([Issue(error.code, Stage.SCHEMA, "$", error.message)])
        emit_json({"ok": False, **report.to_dict()})
        return 1
    except ProjectError as error:
        return _fail(error)
    from ..classification.dataset import summarize

    emit_json(
        {
            "ok": True,
            "manifest_path": str(manifest_path),
            "summary": summarize(manifest),
        }
    )
    return 0


def _list_samples(args: argparse.Namespace) -> int:
    try:
        payload = list_samples(Path(args.root))
    except ProjectError as error:
        return _fail(error)
    emit_json({"ok": True, **payload})
    return 0


def _delete_sample(args: argparse.Namespace) -> int:
    try:
        payload = delete_sample(Path(args.root), path=args.path)
    except ProjectError as error:
        return _fail(error)
    emit_json({"ok": True, **payload})
    return 0


def _emit_edit(result: ProjectEditResult) -> int:
    emit_json({"ok": True, **result.to_dict()})
    return 0


def _rename_project(args: argparse.Namespace) -> int:
    try:
        result = rename_project(Path(args.root), name=args.name)
    except ProjectError as error:
        return _fail(error)
    return _emit_edit(result)


def _add_class(args: argparse.Namespace) -> int:
    try:
        result = add_class(Path(args.root), name=args.name)
    except ProjectError as error:
        return _fail(error)
    return _emit_edit(result)


def _remove_class(args: argparse.Namespace) -> int:
    try:
        result = remove_class(
            Path(args.root), name=args.name, delete_data=args.with_data
        )
    except ProjectError as error:
        return _fail(error)
    return _emit_edit(result)


def _check_dataset(args: argparse.Namespace) -> int:
    try:
        payload = check_dataset(
            Path(args.root),
            require_test=args.require_test,
            min_train_per_class=args.min_train,
            min_val_per_class=args.min_val,
            min_test_per_class=args.min_test,
        )
    except ProjectError as error:
        return _fail(error)
    emit_json(payload)
    return 0 if payload["ok"] else 1


def _rename_class(args: argparse.Namespace) -> int:
    try:
        payload = rename_class(Path(args.root), old=args.old, new=args.new)
    except ProjectError as error:
        return _fail(error)
    emit_json({"ok": True, **payload})
    return 0


def _rename_sample(args: argparse.Namespace) -> int:
    try:
        payload = rename_sample(Path(args.root), path=args.path, name=args.name)
    except ProjectError as error:
        return _fail(error)
    emit_json({"ok": True, **payload})
    return 0


def _list_runs(args: argparse.Namespace) -> int:
    try:
        payload = list_runs(Path(args.root))
    except ProjectError as error:
        return _fail(error)
    emit_json({"ok": True, **payload})
    return 0


def _export_run(args: argparse.Namespace) -> int:
    from ..classification.export import ExportError

    try:
        result = export_run(
            Path(args.root),
            run_dir=args.run,
            artifact_id=args.artifact_id,
            platform=args.platform,
            data_root=Path(args.data_root) if args.data_root else None,
        )
    except ExportError as error:
        issues = [Issue(error.code, Stage.ARTIFACTS.value, "$", error.message)]
        issues.extend(error.issues)
        emit_json({"ok": False, **Report(issues).to_dict()})
        return 1
    except ProjectError as error:
        return _fail(error)
    emit_json({"ok": True, **result})
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backend.project",
        description="LAITP 学生项目文件（project.json）",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="创建新项目")
    create.add_argument("--root", required=True)
    create.add_argument(
        "--project-id",
        default=None,
        help="项目 ID；省略时按时间自动生成 proj-YYYYMMDD-HHMMSS",
    )
    create.add_argument("--name", required=True)
    create.add_argument("--classes", nargs="+", required=True)

    inspect = subparsers.add_parser("inspect", help="查看项目文件")
    inspect.add_argument("project", help="project.json 或项目目录")

    verify = subparsers.add_parser("verify", help="校验项目引用与文件摘要")
    verify.add_argument("--root", required=True)

    add = subparsers.add_parser("add-model", help="登记模型产物引用")
    add.add_argument("--root", required=True)
    add.add_argument("--artifact-id", required=True)
    add.add_argument("--kind", required=True, choices=["training", "export"])
    add.add_argument("--path", required=True)
    add.add_argument("--sha256", default=None)

    current = subparsers.add_parser("set-current", help="设置当前模型")
    current.add_argument("--root", required=True)
    current.add_argument("--artifact-id", required=True)

    training = subparsers.add_parser(
        "register-training", help="把训练运行登记到项目（不设为当前模型）"
    )
    training.add_argument("--root", required=True)
    training.add_argument("--run", required=True, help="训练运行目录")

    export = subparsers.add_parser(
        "register-export", help="登记 ONNX 模型包并设为当前模型"
    )
    export.add_argument("--root", required=True)
    export.add_argument("--artifact-id", required=True)
    export.add_argument("--manifest", required=True, help="模型包 manifest.json 相对路径")

    publish = subparsers.add_parser(
        "publish-training",
        help="登记训练产物、导出 ONNX 并设为当前模型（训练后一键发布）",
    )
    publish.add_argument("--root", required=True)
    publish.add_argument("--run", required=True, help="训练运行目录")
    publish.add_argument("--artifact-id", default=None, help="默认按训练运行名生成")
    publish.add_argument("--platform", default="windows-x64",
                         choices=["windows-x64", "linux-x64"])
    publish.add_argument("--data-root", default=None,
                         help="覆盖导出读取样本的数据根目录")

    importer = subparsers.add_parser("import", help="批量导入图片并重建数据清单")
    importer.add_argument("--root", required=True)
    importer.add_argument("--class", dest="class_name", required=True)
    importer.add_argument("--source", required=True, help="图片来源目录")
    importer.add_argument("--split", default="train", choices=["train", "test"])
    importer.add_argument("--batch", default=None, help="批次名；默认按日期生成")

    tree_importer = subparsers.add_parser(
        "import-tree", help="按 来源/类别/批次 目录结构批量导入图片"
    )
    tree_importer.add_argument("--root", required=True)
    tree_importer.add_argument("--source", required=True, help="来源根目录")
    tree_importer.add_argument(
        "--split", default="train", choices=["train", "test"]
    )
    tree_importer.add_argument(
        "--batch",
        default=None,
        help="统一批次名；省略则使用子目录名（无子目录时自动生成）",
    )

    rebuild = subparsers.add_parser(
        "rebuild-dataset", help="扫描项目数据目录并重建数据清单"
    )
    rebuild.add_argument("--root", required=True)
    rebuild.add_argument("--dataset-id", default=None)

    samples = subparsers.add_parser("samples", help="列出项目图片样本")
    samples.add_argument("--root", required=True)

    delete = subparsers.add_parser("delete-sample", help="删除单个样本并重建清单")
    delete.add_argument("--root", required=True)
    delete.add_argument("--path", required=True, help="样本相对 data/ 的路径")

    rename = subparsers.add_parser("rename", help="修改项目名称")
    rename.add_argument("--root", required=True)
    rename.add_argument("--name", required=True)

    add_class_parser = subparsers.add_parser("add-class", help="添加类别")
    add_class_parser.add_argument("--root", required=True)
    add_class_parser.add_argument("--name", required=True)

    remove = subparsers.add_parser("remove-class", help="删除类别")
    remove.add_argument("--root", required=True)
    remove.add_argument("--name", required=True)
    remove.add_argument(
        "--with-data",
        action="store_true",
        help="同时删除该类别的图片；未指定且该类有数据时拒绝",
    )

    check = subparsers.add_parser(
        "check-dataset", help="训练前校验数据清单（覆盖、批次、文件完整性）"
    )
    check.add_argument("--root", required=True)
    check.add_argument(
        "--require-test", action="store_true", help="要求独立测试集且每类至少 1 张"
    )
    check.add_argument("--min-train", type=int, default=1, help="每类训练样本下限")
    check.add_argument("--min-val", type=int, default=1, help="每类验证样本下限")
    check.add_argument(
        "--min-test",
        type=int,
        default=None,
        help="每类测试样本下限；默认要求测试集时为 1，否则 0",
    )

    rename_class_parser = subparsers.add_parser(
        "rename-class", help="重命名类别并同步移动数据目录"
    )
    rename_class_parser.add_argument("--root", required=True)
    rename_class_parser.add_argument("--old", required=True)
    rename_class_parser.add_argument("--new", required=True)

    rename_sample_parser = subparsers.add_parser(
        "rename-sample", help="重命名单个样本文件"
    )
    rename_sample_parser.add_argument("--root", required=True)
    rename_sample_parser.add_argument("--path", required=True, help="样本相对 data/ 的路径")
    rename_sample_parser.add_argument("--name", required=True, help="新文件名（可省略扩展名）")

    runs = subparsers.add_parser("runs", help="列出项目训练运行")
    runs.add_argument("--root", required=True)

    export_run_parser = subparsers.add_parser(
        "export-run", help="从已有训练运行导出模型包并设为当前模型"
    )
    export_run_parser.add_argument("--root", required=True)
    export_run_parser.add_argument("--run", required=True, help="训练运行 ID 或目录")
    export_run_parser.add_argument("--artifact-id", default=None)
    export_run_parser.add_argument(
        "--platform", default="windows-x64", choices=["windows-x64", "linux-x64"]
    )
    export_run_parser.add_argument("--data-root", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "create":
        return _create(args)
    if args.command == "inspect":
        return _inspect(args)
    if args.command == "verify":
        return _verify(args)
    if args.command == "add-model":
        return _add_model(args)
    if args.command == "set-current":
        return _set_current(args)
    if args.command == "register-training":
        return _register_training(args)
    if args.command == "publish-training":
        return _publish_training(args)
    if args.command == "import":
        return _import_images(args)
    if args.command == "import-tree":
        return _import_tree(args)
    if args.command == "rebuild-dataset":
        return _rebuild_dataset(args)
    if args.command == "samples":
        return _list_samples(args)
    if args.command == "delete-sample":
        return _delete_sample(args)
    if args.command == "rename":
        return _rename_project(args)
    if args.command == "add-class":
        return _add_class(args)
    if args.command == "remove-class":
        return _remove_class(args)
    if args.command == "check-dataset":
        return _check_dataset(args)
    if args.command == "rename-class":
        return _rename_class(args)
    if args.command == "rename-sample":
        return _rename_sample(args)
    if args.command == "runs":
        return _list_runs(args)
    if args.command == "export-run":
        return _export_run(args)
    return _register_export(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
