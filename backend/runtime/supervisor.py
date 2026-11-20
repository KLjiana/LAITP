"""最小父进程：启动子进程、读取协议消息、维护任务状态、处理取消。

不依赖 WPF，可作为集成测试与后续 C# 任务管理的参考实现：

- 只接受项目/请求/任务 ID 与当前任务一致、序号递增的消息；
- 终态一旦确定，迟到消息只记录为拒绝；
- 取消时终止子进程并把任务置为已取消，迟到的成功结果不会改变状态；
- 子进程未发送终态消息就退出时，任务标记为失败并附退出码与标准错误尾部。
"""

from __future__ import annotations

import queue
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..contracts.errors import Code
from .messages import Envelope, ProtocolError, parse_line
from .protocol import Rejection, TaskSession, TaskState, TERMINAL_STATES

STDERR_TAIL_BYTES = 4000
MAX_MESSAGE_BYTES = 1024 * 1024


@dataclass(frozen=True)
class TaskOutcome:
    task_id: str
    state: TaskState
    artifact_id: str | None
    result: dict[str, Any] | None
    error: dict[str, Any] | None
    progress: tuple[dict[str, Any], ...]
    rejections: tuple[Rejection, ...]
    accepted: int
    exit_code: int | None
    stderr_tail: str

    @property
    def ok(self) -> bool:
        return self.state is TaskState.SUCCEEDED

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "state": self.state.value,
            "artifact_id": self.artifact_id,
            "accepted": self.accepted,
            "progress": list(self.progress),
            "result": self.result,
            "error": self.error,
            "rejections": [item.to_dict() for item in self.rejections],
            "exit_code": self.exit_code,
            "stderr_tail": self.stderr_tail,
        }


class TaskSupervisor:
    def __init__(
        self,
        argv: Sequence[str],
        *,
        request_id: str,
        project_id: str,
        task_id: str,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._argv = list(argv)
        self._cwd = str(cwd) if cwd is not None else None
        self._env = dict(env) if env is not None else None
        self.session = TaskSession(
            request_id=request_id, project_id=project_id, task_id=task_id
        )
        self._queue: queue.Queue[Envelope | None] = queue.Queue()
        self._process: subprocess.Popen[bytes] | None = None
        self._reader: threading.Thread | None = None
        self._stderr_file: Any | None = None
        self._cancel_reason: str | None = None
        self._closed = False

    @property
    def state(self) -> TaskState:
        return self.session.state

    @property
    def process(self) -> subprocess.Popen[bytes] | None:
        return self._process

    def start(self) -> "TaskSupervisor":
        if self._process is not None:
            raise RuntimeError("任务已经启动")
        self._stderr_file = tempfile.TemporaryFile()
        self._process = subprocess.Popen(
            self._argv,
            stdout=subprocess.PIPE,
            stderr=self._stderr_file,
            cwd=self._cwd,
            env=self._env,
        )
        self._reader = threading.Thread(
            target=self._read_loop,
            name=f"task-reader-{self.session.task_id}",
            daemon=True,
        )
        self._reader.start()
        return self

    def next_message(self, timeout: float | None = None) -> Envelope | None:
        try:
            item = self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
        if item is None:
            self._queue.put(None)
            return None
        return item

    def cancel(self, reason: str = "user_cancelled", timeout: float = 5.0) -> bool:
        if self._process is None:
            raise RuntimeError("任务尚未启动")
        if self.session.state in TERMINAL_STATES:
            return False
        self._cancel_reason = reason
        self.session.mark_cancelling()
        self._process.terminate()
        try:
            self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=2.0)
        self.session.mark_cancelled(reason)
        return True

    def wait(self, timeout: float | None = None) -> TaskOutcome:
        if self._process is None:
            raise RuntimeError("任务尚未启动")
        exit_code = self._process.wait(timeout=timeout)
        if self._reader is not None:
            self._reader.join(timeout=5.0)
        self._drain()
        self._finalize(exit_code)
        tail = self._stderr_tail()
        outcome = TaskOutcome(
            task_id=self.session.task_id,
            state=self.session.state,
            artifact_id=(
                str(self.session.result.get("artifact", {}).get("artifact_id"))
                if self.session.result
                else None
            ),
            result=self.session.result,
            error=self.session.error,
            progress=tuple(self.session.progress),
            rejections=tuple(self.session.rejections),
            accepted=self.session.accepted,
            exit_code=exit_code,
            stderr_tail=tail,
        )
        self._close()
        return outcome

    # ------------------------------------------------------------------ #

    def _read_loop(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        stream = self._process.stdout
        try:
            while True:
                raw = stream.readline()
                if not raw:
                    break
                if len(raw) > MAX_MESSAGE_BYTES:
                    self.session.reject_line(
                        f"单条消息超过 {MAX_MESSAGE_BYTES} 字节限制"
                    )
                    continue
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    envelope = parse_line(line)
                except ProtocolError as error:
                    self.session.reject_line(str(error))
                    continue
                self.session.accept(envelope)
                self._queue.put(envelope)
        finally:
            self._queue.put(None)

    def _drain(self) -> None:
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                return
            if item is None:
                return

    def _finalize(self, exit_code: int | None) -> None:
        if self.session.state in TERMINAL_STATES:
            return
        if self._cancel_reason is not None:
            self.session.mark_cancelled(self._cancel_reason)
            return
        self.session.mark_failed(
            Code.TASK_CHILD_EXITED,
            f"子进程退出码 {exit_code} 且未发送终态消息",
        )

    def _stderr_tail(self) -> str:
        if self._stderr_file is None:
            return ""
        self._stderr_file.flush()
        self._stderr_file.seek(0)
        data = self._stderr_file.read()
        return data[-STDERR_TAIL_BYTES:].decode("utf-8", errors="replace")

    def _close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._process is not None and self._process.stdout is not None:
            self._process.stdout.close()
        if self._stderr_file is not None:
            self._stderr_file.close()
