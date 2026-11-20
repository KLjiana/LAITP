"""学生项目文件（M1）。

提供 ``project.json`` 的创建、读取、保存与校验；界面与后续采集/训练流程复用。
"""

from .project import (
    PROJECT_FILE,
    ModelReference,
    Project,
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

__all__ = [
    "PROJECT_FILE",
    "ModelReference",
    "Project",
    "ProjectEditResult",
    "ProjectError",
    "add_class",
    "add_model",
    "create_project",
    "export_run",
    "list_runs",
    "load_project",
    "publish_training",
    "register_export",
    "register_training_artifact",
    "remove_class",
    "rename_project",
    "save_project",
    "set_current_model",
    "verify_project",
]
