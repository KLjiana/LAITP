"""共享的模型包加载：契约校验 + 运行时加载。"""

from __future__ import annotations

from pathlib import Path

import onnxruntime as ort

from ..contracts.errors import Issue, Report, Stage
from ..contracts.manifest import validate_model_package
from ..contracts.runtime_spec import RuntimeProfile
from .inference import ModelPackageRuntime, RuntimeInferenceError


def runtime_profile(platform: str = "windows-x64") -> RuntimeProfile:
    return RuntimeProfile(
        runtime="onnxruntime",
        version=ort.__version__,
        platform=platform,
        capabilities=frozenset({"onnxruntime-cpu"}),
    )


def load_runtime(
    package: str | Path, *, platform: str = "windows-x64"
) -> tuple[ModelPackageRuntime | None, Report]:
    report = Report()
    validation = validate_model_package(Path(package), runtime_profile=runtime_profile(platform))
    report.extend(validation.issues)
    if not validation.ok:
        return None, report
    try:
        return ModelPackageRuntime.load(package), report
    except RuntimeInferenceError as error:
        report.add(error.code, Stage.RUNTIME, "model.path", error.message)
        return None, report


def report_failure(report: Report, *, default_code: str) -> tuple[str, str, str, str]:
    """取第一条错误用于消息信封：``(code, stage, message, location)``。"""
    if not report.issues:
        return default_code, Stage.RUNTIME.value, "任务失败且没有可用诊断信息", "$"
    issue: Issue = report.issues[0]
    return issue.code.value, issue.stage.value, issue.message, issue.location
