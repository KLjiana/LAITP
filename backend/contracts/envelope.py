"""进程消息信封校验（契约第 6 节）。

只校验单条消息的结构、版本和自洽性。跨消息的任务归属、序号递增、
迟到与重复消息由调用方的任务状态机处理，不能靠这里的校验代替。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import paths, schemas
from .errors import Code, Report, Stage
from .runtime_spec import VersionSyntaxError, parse_version

SUPPORTED_MESSAGE_TYPES = ("progress", "result", "error", "cancelled")


@dataclass(frozen=True)
class ProtocolPolicy:
    """接收方声明的协议支持范围。"""

    protocol_major: int = 1
    protocol_minor: int = 0
    supported_message_types: tuple[str, ...] = SUPPORTED_MESSAGE_TYPES


DEFAULT_PROTOCOL = ProtocolPolicy()


def validate_envelope(data: Any, *, policy: ProtocolPolicy = DEFAULT_PROTOCOL) -> Report:
    """校验一条已解析的 JSON 消息。"""
    report = Report()
    if not isinstance(data, dict):
        report.add(
            Code.ENVELOPE_SCHEMA_INVALID,
            Stage.SCHEMA,
            "$",
            "消息必须是 JSON 对象",
        )
        return report

    structure = schemas.schema_issues(
        schemas.ENVELOPE_SCHEMA,
        data,
        code=Code.ENVELOPE_SCHEMA_INVALID,
        stage=Stage.SCHEMA,
    )
    if structure:
        report.extend(structure)
        return report

    if not _check_version(report, data["protocol_version"], policy):
        return report

    message_type = data["message_type"]
    if message_type not in policy.supported_message_types:
        report.add(
            Code.ENVELOPE_MESSAGE_TYPE_UNSUPPORTED,
            Stage.SCHEMA,
            "message_type",
            f"消息类型 {message_type!r} 尚未由当前接收方支持"
            f"（支持：{', '.join(policy.supported_message_types)}）",
        )
        return report

    if message_type == "progress":
        _check_progress(report, data["payload"])
    elif message_type == "result":
        _check_result(report, data)
    return report


def _check_version(report: Report, version_text: str, policy: ProtocolPolicy) -> bool:
    try:
        major, minor, _ = parse_version(version_text)
    except VersionSyntaxError:
        report.add(
            Code.ENVELOPE_SCHEMA_INVALID,
            Stage.SCHEMA,
            "protocol_version",
            f"协议版本 {version_text!r} 不符合 major.minor 格式",
        )
        return False
    if major != policy.protocol_major:
        report.add(
            Code.ENVELOPE_VERSION_UNSUPPORTED_MAJOR,
            Stage.SCHEMA,
            "protocol_version",
            f"协议主版本 {major} 不受支持（当前仅支持 {policy.protocol_major}.x）",
        )
        return False
    if minor > policy.protocol_minor:
        report.add(
            Code.ENVELOPE_VERSION_UNSUPPORTED_MINOR,
            Stage.SCHEMA,
            "protocol_version",
            f"协议次版本 {version_text} 高于当前支持的 "
            f"{policy.protocol_major}.{policy.protocol_minor}",
        )
        return False
    return True


def _check_progress(report: Report, payload: dict[str, Any]) -> None:
    total = payload["total"]
    if total is not None and payload["completed"] > total:
        report.add(
            Code.ENVELOPE_PROGRESS_INVALID,
            Stage.SEMANTICS,
            "payload.completed",
            f"已完成数 {payload['completed']} 超过总数 {total}",
        )


def _check_result(report: Report, data: dict[str, Any]) -> None:
    artifact_id = data["artifact_id"]
    reference = data["payload"]["artifact"]
    if artifact_id is None:
        report.add(
            Code.ENVELOPE_ARTIFACT_MISMATCH,
            Stage.SEMANTICS,
            "artifact_id",
            "成功结果必须携带产物 ID，新模型也必须在整体发布后填写",
        )
    elif artifact_id != reference["artifact_id"]:
        report.add(
            Code.ENVELOPE_ARTIFACT_MISMATCH,
            Stage.SEMANTICS,
            "payload.artifact.artifact_id",
            f"信封产物 ID {artifact_id!r} 与结果引用的 {reference['artifact_id']!r} 不一致",
        )

    manifest_reason = paths.check_rel_path(reference["manifest_path"])
    if manifest_reason is not None:
        report.add(
            Code.ENVELOPE_ARTIFACT_MISMATCH,
            Stage.SEMANTICS,
            "payload.artifact.manifest_path",
            f"{reference['manifest_path']!r}：{manifest_reason}",
        )

    predictions = data["payload"].get("predictions") or []
    seen: set[int] = set()
    for index, prediction in enumerate(predictions):
        class_id = prediction["class_id"]
        if class_id in seen:
            report.add(
                Code.ENVELOPE_PREDICTION_INVALID,
                Stage.SEMANTICS,
                f"payload.predictions[{index}].class_id",
                f"类别 ID {class_id} 重复，预测结果必须按类别唯一",
            )
        seen.add(class_id)
