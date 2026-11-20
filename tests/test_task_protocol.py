"""任务协议与父进程控制测试（T07）。"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from backend.classification.dataset import build_dataset_manifest
from backend.classification.export import ExportConfig, export_model
from backend.classification.preprocess import PreprocessSpec
from backend.classification.training import TrainingConfig, train
from backend.contracts.errors import Code
from backend.runtime.messages import (
    Envelope,
    MessageWriter,
    ProtocolError,
    parse_line,
)
from backend.runtime.protocol import TaskSession, TaskState
from backend.runtime.supervisor import TaskSupervisor
from tests.support.images import build_dataset_tree

CLASSES = ("水杯", "书本", "笔袋")
FIXED_TIME = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)
EXPORTED_AT = datetime(2026, 11, 17, 11, 0, tzinfo=timezone.utc)
REPO_ROOT = Path(__file__).resolve().parents[1]
WORKERS = REPO_ROOT / "tests" / "fixtures" / "workers"


@pytest.fixture(scope="module")
def package(tmp_path_factory: pytest.TempPathFactory):
    base = tmp_path_factory.mktemp("tasks")
    root = build_dataset_tree(
        base / "data", classes=CLASSES, train_batches=3, images_per_batch=2
    )
    manifest = build_dataset_manifest(
        root, classes=CLASSES, dataset_id="ds-20261117-0400", created_at=FIXED_TIME
    )
    manifest_path = root / "dataset-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    training = train(
        TrainingConfig(
            run_id="run-task-0001",
            dataset_manifest=manifest_path,
            dataset_root=root,
            output_root=base / "runs",
            weights_config=None,
            epochs=1,
            batch_size=8,
            threads=1,
            preprocess=PreprocessSpec(width=32, height=32),
        )
    )
    export = export_model(
        ExportConfig(
            run_dir=training.run_dir,
            output_root=base / "exports",
            artifact_id="art-task-0001",
            project_id="proj-test",
            data_root=root,
            created_at=EXPORTED_AT,
        )
    )
    return export.package_dir, manifest, root, manifest_path


def environment() -> dict[str, str]:
    values = os.environ.copy()
    values["PYTHONPATH"] = str(REPO_ROOT)
    values["PYTHONIOENCODING"] = "utf-8"
    return values


def fake_worker(
    script: str,
    *,
    request_id: str = "req-1",
    project_id: str = "proj-1",
    task_id: str = "task-1",
) -> TaskSupervisor:
    return TaskSupervisor(
        [sys.executable, str(WORKERS / script), request_id, project_id, task_id],
        request_id=request_id,
        project_id=project_id,
        task_id=task_id,
        env=environment(),
    ).start()


def real_worker(*args: str, request_id: str, project_id: str, task_id: str) -> TaskSupervisor:
    return TaskSupervisor(
        [
            sys.executable,
            "-m",
            "backend.runtime.worker",
            *args,
            "--request-id",
            request_id,
            "--project-id",
            project_id,
            "--task-id",
            task_id,
        ],
        request_id=request_id,
        project_id=project_id,
        task_id=task_id,
        env=environment(),
    ).start()


def drain(supervisor: TaskSupervisor, timeout: float = 60.0) -> list[Envelope]:
    messages: list[Envelope] = []
    while True:
        envelope = supervisor.next_message(timeout=timeout)
        if envelope is None:
            return messages
        messages.append(envelope)


# --------------------------------------------------------------------------- #
# 消息构造与状态机
# --------------------------------------------------------------------------- #


def test_writer_produces_increasing_sequences() -> None:
    lines: list[str] = []
    writer = MessageWriter(
        request_id="req-1", project_id="proj-1", task_id="task-1", sink=lines.append
    )
    writer.progress("load", 0, 2)
    writer.progress("load", 1, 2)
    envelopes = [parse_line(line) for line in lines]
    assert [item.sequence for item in envelopes] == [0, 1]
    assert all(item.message_type == "progress" for item in envelopes)


def test_writer_rejects_invalid_message() -> None:
    writer = MessageWriter(
        request_id="req-1", project_id="proj-1", task_id="task-1", sink=lambda _: None
    )
    reference = {
        "artifact_id": "art-1",
        "manifest_path": "manifest.json",
        "manifest_sha256": "a" * 64,
    }
    with pytest.raises(ProtocolError):
        writer.result("predict", reference)  # predict 结果必须带 predictions


def test_session_accepts_progress_and_result() -> None:
    lines: list[str] = []
    writer = MessageWriter(
        request_id="req-1", project_id="proj-1", task_id="task-1", sink=lines.append
    )
    writer.progress("load", 0, 2)
    writer.result(
        "validate",
        {
            "artifact_id": "art-1",
            "manifest_path": "manifest.json",
            "manifest_sha256": "a" * 64,
        },
    )
    session = TaskSession(request_id="req-1", project_id="proj-1", task_id="task-1")
    for line in lines:
        assert session.accept(parse_line(line)) is True
    assert session.state is TaskState.SUCCEEDED
    assert session.result is not None
    assert session.result["artifact"]["artifact_id"] == "art-1"
    assert len(session.progress) == 1
    assert session.accepted == 2


def test_session_rejects_identity_mismatch() -> None:
    lines: list[str] = []
    writer = MessageWriter(
        request_id="req-1", project_id="other-project", task_id="task-1", sink=lines.append
    )
    writer.progress("load", 0, 1)
    session = TaskSession(request_id="req-1", project_id="proj-1", task_id="task-1")
    assert session.accept(parse_line(lines[0])) is False
    assert session.state is TaskState.RUNNING
    assert session.rejections[0].code is Code.TASK_IDENTITY_MISMATCH


def test_session_rejects_stale_sequence() -> None:
    lines: list[str] = []
    writer = MessageWriter(
        request_id="req-1", project_id="proj-1", task_id="task-1", sink=lines.append
    )
    writer.progress("load", 0, 2)
    writer.progress("load", 1, 2)
    session = TaskSession(request_id="req-1", project_id="proj-1", task_id="task-1")
    assert session.accept(parse_line(lines[1])) is True
    assert session.accept(parse_line(lines[0])) is False
    assert session.rejections[0].code is Code.TASK_SEQUENCE_INVALID


def test_session_ignores_messages_after_terminal() -> None:
    lines: list[str] = []
    writer = MessageWriter(
        request_id="req-1", project_id="proj-1", task_id="task-1", sink=lines.append
    )
    reference = {
        "artifact_id": "art-1",
        "manifest_path": "manifest.json",
        "manifest_sha256": "a" * 64,
    }
    writer.result("validate", reference)
    writer.progress("late", 0, 1)
    session = TaskSession(request_id="req-1", project_id="proj-1", task_id="task-1")
    assert session.accept(parse_line(lines[0])) is True
    assert session.accept(parse_line(lines[1])) is False
    assert session.state is TaskState.SUCCEEDED
    assert session.rejections[0].code is Code.TASK_LATE_MESSAGE


def test_cancelled_task_ignores_late_success() -> None:
    lines: list[str] = []
    writer = MessageWriter(
        request_id="req-1", project_id="proj-1", task_id="task-1", sink=lines.append
    )
    writer.result(
        "validate",
        {
            "artifact_id": "art-late",
            "manifest_path": "manifest.json",
            "manifest_sha256": "a" * 64,
        },
    )
    session = TaskSession(request_id="req-1", project_id="proj-1", task_id="task-1")
    session.mark_cancelled("user_cancelled")
    assert session.accept(parse_line(lines[0])) is False
    assert session.state is TaskState.CANCELLED
    assert session.result is None
    assert session.rejections[0].code is Code.TASK_LATE_MESSAGE


def test_session_rejects_invalid_envelope() -> None:
    lines: list[str] = []
    writer = MessageWriter(
        request_id="req-1", project_id="proj-1", task_id="task-1", sink=lines.append
    )
    writer.progress("load", 0, 1)
    envelope = parse_line(lines[0])
    broken = replace(envelope, payload={"stage": "load", "completed": 0})
    session = TaskSession(request_id="req-1", project_id="proj-1", task_id="task-1")
    assert session.accept(broken) is False
    assert session.rejections[0].code is Code.TASK_ENVELOPE_INVALID


# --------------------------------------------------------------------------- #
# 父进程与实际工作进程
# --------------------------------------------------------------------------- #


def test_supervisor_runs_real_worker(package) -> None:
    package_dir, _, root, _ = package
    manifest = json.loads((root / "dataset-manifest.json").read_text(encoding="utf-8"))
    image = root / next(
        item["path"] for item in manifest["samples"] if item["split"] == "val"
    )
    supervisor = real_worker(
        "predict",
        "--package",
        str(package_dir),
        "--image",
        str(image),
        request_id="req-real",
        project_id="proj-real",
        task_id="task-real",
    )
    messages = drain(supervisor)
    outcome = supervisor.wait(timeout=60)

    assert outcome.ok is True
    assert outcome.state is TaskState.SUCCEEDED
    assert outcome.artifact_id == "art-task-0001"
    assert [item.sequence for item in messages] == list(range(len(messages)))
    assert messages[-1].message_type == "result"
    assert outcome.rejections == ()
    assert outcome.exit_code == 0


def test_supervisor_reports_worker_error() -> None:
    supervisor = real_worker(
        "validate",
        "--package",
        "does-not-exist",
        request_id="req-bad",
        project_id="proj-bad",
        task_id="task-bad",
    )
    drain(supervisor)
    outcome = supervisor.wait(timeout=60)
    assert outcome.state is TaskState.FAILED
    assert outcome.error is not None
    assert outcome.error["code"] == Code.PACKAGE_NOT_FOUND.value
    assert outcome.exit_code == 1


def test_supervisor_cancel_terminates_worker() -> None:
    supervisor = fake_worker("slow_worker.py")
    first = supervisor.next_message(timeout=30)
    assert first is not None and first.message_type == "progress"
    assert supervisor.cancel() is True
    outcome = supervisor.wait(timeout=15)
    assert outcome.state is TaskState.CANCELLED
    assert outcome.result is None
    assert supervisor.process is not None and supervisor.process.poll() is not None
    assert supervisor.cancel() is False


def test_supervisor_ignores_late_result_after_terminal() -> None:
    supervisor = fake_worker("double_result_worker.py")
    messages = drain(supervisor)
    outcome = supervisor.wait(timeout=15)
    assert outcome.ok is True
    assert outcome.artifact_id == "art-first"
    assert len(messages) == 2
    assert any(
        rejection.code is Code.TASK_LATE_MESSAGE for rejection in outcome.rejections
    )


def test_child_exit_without_terminal_message() -> None:
    supervisor = fake_worker("exit_without_message.py")
    drain(supervisor)
    outcome = supervisor.wait(timeout=15)
    assert outcome.state is TaskState.FAILED
    assert outcome.error is not None
    assert outcome.error["code"] == Code.TASK_CHILD_EXITED.value
    assert outcome.exit_code == 3


def test_invalid_protocol_line_is_recorded() -> None:
    supervisor = fake_worker("garbage_worker.py")
    drain(supervisor)
    outcome = supervisor.wait(timeout=15)
    assert outcome.state is TaskState.FAILED
    assert any(
        rejection.reason == "invalid_line" for rejection in outcome.rejections
    )


def test_cancelled_training_does_not_publish_artifact(package, tmp_path: Path) -> None:
    _, manifest, root, manifest_path = package
    run_id = "run-cancelled-0001"
    output = tmp_path / "runs"
    supervisor = real_worker(
        "train",
        "--dataset",
        str(manifest_path),
        "--data-root",
        str(root),
        "--output",
        str(output),
        "--run-id",
        run_id,
        "--epochs",
        "1",
        "--batch-size",
        "8",
        "--threads",
        "1",
        "--image-size",
        "32",
        request_id="req-train",
        project_id="proj-train",
        task_id="task-train",
    )
    first = supervisor.next_message(timeout=60)
    assert first is not None and first.message_type == "progress"
    assert first.payload["stage"] == "accepted"
    assert supervisor.cancel() is True
    outcome = supervisor.wait(timeout=30)
    assert outcome.state is TaskState.CANCELLED
    assert not (output / run_id).exists()
