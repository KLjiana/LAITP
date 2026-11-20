"""任务状态机：校验消息归属、序号与终态，拒绝迟到消息。

终态（成功/失败/已取消）一旦确定就不能被后续消息覆盖；取消后到达的成功
消息只记录为拒绝，不改变任务状态，也不切换当前模型。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..contracts.errors import Code
from .messages import Envelope, envelope_issues


class TaskState(str, Enum):
    RUNNING = "running"
    CANCELLING = "cancelling"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATES = frozenset(
    {TaskState.SUCCEEDED, TaskState.FAILED, TaskState.CANCELLED}
)


@dataclass(frozen=True)
class Rejection:
    code: Code
    reason: str
    detail: str
    envelope: Envelope | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "reason": self.reason,
            "detail": self.detail,
        }


@dataclass
class TaskSession:
    """一次任务的协议状态。消息由父进程或测试直接投递。"""

    request_id: str
    project_id: str
    task_id: str
    state: TaskState = TaskState.RUNNING
    last_sequence: int | None = None
    accepted: int = 0
    progress: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    cancel_reason: str | None = None
    rejections: list[Rejection] = field(default_factory=list)

    def accept(self, envelope: Envelope) -> bool:
        issues = envelope_issues(envelope)
        if issues:
            return self._reject(
                Code.TASK_ENVELOPE_INVALID,
                "invalid_envelope",
                f"{issues[0].location}: {issues[0].message}",
                envelope,
            )
        if (
            envelope.request_id != self.request_id
            or envelope.project_id != self.project_id
            or envelope.task_id != self.task_id
        ):
            return self._reject(
                Code.TASK_IDENTITY_MISMATCH,
                "identity_mismatch",
                f"消息归属 {envelope.project_id}/{envelope.request_id}/{envelope.task_id} "
                f"与当前任务 {self.project_id}/{self.request_id}/{self.task_id} 不一致",
                envelope,
            )
        if self.state in TERMINAL_STATES:
            return self._reject(
                Code.TASK_LATE_MESSAGE,
                "after_terminal",
                f"任务已处于 {self.state.value}，忽略 {envelope.message_type} 消息",
                envelope,
            )
        if self.last_sequence is not None and envelope.sequence <= self.last_sequence:
            return self._reject(
                Code.TASK_SEQUENCE_INVALID,
                "stale_sequence",
                f"序号 {envelope.sequence} 未大于已接收的 {self.last_sequence}",
                envelope,
            )

        self.last_sequence = envelope.sequence
        self.accepted += 1
        if envelope.message_type == "progress":
            self.progress.append(envelope.payload)
        elif envelope.message_type == "result":
            self.result = envelope.payload
            self.state = TaskState.SUCCEEDED
        elif envelope.message_type == "error":
            self.error = envelope.payload
            self.state = TaskState.FAILED
        elif envelope.message_type == "cancelled":
            self.cancel_reason = str(envelope.payload.get("reason", "user_cancelled"))
            self.state = TaskState.CANCELLED
        return True

    def mark_cancelling(self) -> None:
        if self.state is TaskState.RUNNING:
            self.state = TaskState.CANCELLING

    def mark_cancelled(self, reason: str = "user_cancelled") -> None:
        if self.state in TERMINAL_STATES:
            return
        self.cancel_reason = reason
        self.state = TaskState.CANCELLED

    def mark_failed(self, code: Code, message: str) -> None:
        if self.state in TERMINAL_STATES:
            return
        self.error = {"code": code.value, "stage": "runtime", "message": message}
        self.state = TaskState.FAILED

    def reject_line(self, detail: str) -> None:
        self._reject(Code.TASK_ENVELOPE_INVALID, "invalid_line", detail, None)

    def _reject(
        self, code: Code, reason: str, detail: str, envelope: Envelope | None
    ) -> bool:
        self.rejections.append(Rejection(code, reason, detail, envelope))
        return False
