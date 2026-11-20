"""按行 JSON 消息信封的构造、解析与写出（协议 1.0）。

标准输出只承载协议消息，每条一行 UTF-8 JSON；日志写入标准错误。
写出前用契约 Schema 校验，避免工作进程发出自身不合规的消息。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any, Callable

from ..contracts import schemas
from ..contracts.errors import Code, Issue, Stage

PROTOCOL_VERSION = "1.0"
_UNSET = object()


class ProtocolError(Exception):
    """消息无法构造或解析。"""


@dataclass(frozen=True)
class Envelope:
    protocol_version: str
    request_id: str
    project_id: str
    task_id: str
    message_type: str
    sequence: int
    artifact_id: str | None
    payload: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Envelope":
        if not isinstance(data, dict):
            raise ProtocolError("消息必须是 JSON 对象")
        required = (
            "protocol_version",
            "request_id",
            "project_id",
            "task_id",
            "message_type",
            "sequence",
            "artifact_id",
            "payload",
        )
        missing = [name for name in required if name not in data]
        if missing:
            raise ProtocolError(f"消息缺少字段：{', '.join(missing)}")
        return cls(
            protocol_version=str(data["protocol_version"]),
            request_id=str(data["request_id"]),
            project_id=str(data["project_id"]),
            task_id=str(data["task_id"]),
            message_type=str(data["message_type"]),
            sequence=int(data["sequence"]),
            artifact_id=data["artifact_id"],
            payload=dict(data["payload"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "request_id": self.request_id,
            "project_id": self.project_id,
            "task_id": self.task_id,
            "message_type": self.message_type,
            "sequence": self.sequence,
            "artifact_id": self.artifact_id,
            "payload": self.payload,
        }

    def to_line(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))


def parse_line(line: str) -> Envelope:
    try:
        data = json.loads(line)
    except json.JSONDecodeError as error:
        raise ProtocolError(f"不是有效 JSON：{error}") from error
    return Envelope.from_dict(data)


def envelope_issues(envelope: Envelope) -> list[Issue]:
    return schemas.schema_issues(
        schemas.ENVELOPE_SCHEMA,
        envelope.to_dict(),
        code=Code.TASK_ENVELOPE_INVALID,
    )


class MessageWriter:
    """任务工作进程的消息写出器。序号从 0 开始，同一任务内递增。"""

    def __init__(
        self,
        *,
        request_id: str,
        project_id: str,
        task_id: str,
        artifact_id: str | None = None,
        protocol_version: str = PROTOCOL_VERSION,
        sink: Callable[[str], None] | None = None,
    ) -> None:
        self.request_id = request_id
        self.project_id = project_id
        self.task_id = task_id
        self.artifact_id = artifact_id
        self.protocol_version = protocol_version
        self._sequence = 0
        self._sink = sink or _stdout_sink

    def emit(
        self,
        message_type: str,
        payload: dict[str, Any],
        *,
        artifact_id: Any = _UNSET,
    ) -> Envelope:
        envelope = Envelope(
            protocol_version=self.protocol_version,
            request_id=self.request_id,
            project_id=self.project_id,
            task_id=self.task_id,
            message_type=message_type,
            sequence=self._sequence,
            artifact_id=self.artifact_id if artifact_id is _UNSET else artifact_id,
            payload=payload,
        )
        issues = envelope_issues(envelope)
        if issues:
            raise ProtocolError(
                "构造的消息不符合协议："
                + "；".join(f"{issue.location}: {issue.message}" for issue in issues)
            )
        self._sequence += 1
        self._sink(envelope.to_line())
        return envelope

    def progress(
        self,
        stage: str,
        completed: int,
        total: int | None = None,
        message: str | None = None,
    ) -> Envelope:
        payload: dict[str, Any] = {
            "stage": stage,
            "completed": completed,
            "total": total,
        }
        if message is not None:
            payload["message"] = message
        return self.emit("progress", payload)

    def result(
        self,
        operation: str,
        artifact: dict[str, Any],
        *,
        predictions: list[dict[str, Any]] | None = None,
    ) -> Envelope:
        payload: dict[str, Any] = {"operation": operation, "artifact": artifact}
        if predictions is not None:
            payload["predictions"] = predictions
        return self.emit("result", payload, artifact_id=artifact["artifact_id"])

    def error(
        self,
        code: str,
        stage: str,
        message: str,
        *,
        location: str | None = None,
        retryable: bool = False,
    ) -> Envelope:
        return self.emit(
            "error",
            {
                "code": code,
                "stage": stage,
                "message": message,
                "location": location,
                "retryable": retryable,
            },
        )

    def cancelled(self, reason: str = "user_cancelled", message: str | None = None) -> Envelope:
        payload: dict[str, Any] = {"reason": reason}
        if message is not None:
            payload["message"] = message
        return self.emit("cancelled", payload)


def _stdout_sink(line: str) -> None:
    data = (line + "\n").encode("utf-8")
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write(data)
        buffer.flush()
    else:  # pragma: no cover
        sys.stdout.write(line + "\n")


def validate_messages(lines: list[str]) -> list[Issue]:
    """校验一组消息行，用于测试与诊断。"""
    issues: list[Issue] = []
    for index, line in enumerate(lines):
        try:
            envelope = parse_line(line)
        except ProtocolError as error:
            issues.append(
                Issue(
                    Code.TASK_ENVELOPE_INVALID,
                    stage=Stage.RUNTIME,
                    location=f"line[{index}]",
                    message=str(error),
                )
            )
            continue
        issues.extend(envelope_issues(envelope))
    return issues
