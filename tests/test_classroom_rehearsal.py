"""课堂演练脚本的训练阶段判定与计时口径测试。

不运行真实训练：只构造 worker 协议信封与训练产物目录，验证
``scripts/classroom_rehearsal.py`` 的成功判定与 ``train_seconds`` 来源。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_rehearsal():
    spec = importlib.util.spec_from_file_location(
        "classroom_rehearsal", ROOT / "scripts/classroom_rehearsal.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def training_result_envelope() -> dict:
    """worker ``train`` 成功时的最后一条协议消息：没有顶层 ``ok``。"""
    return {
        "protocol_version": "1.0",
        "request_id": "req-rehearsal-train",
        "project_id": "proj-rehearsal",
        "task_id": "task-rehearsal-train",
        "message_type": "result",
        "sequence": 3,
        "artifact_id": "train-rehearsal-0001",
        "payload": {
            "operation": "train",
            "artifact": {
                "artifact_id": "train-rehearsal-0001",
                "manifest_path": "training-artifact.json",
                "manifest_sha256": "0" * 64,
            },
        },
    }


def training_error_envelope() -> dict:
    return {
        "protocol_version": "1.0",
        "request_id": "req-rehearsal-train",
        "project_id": "proj-rehearsal",
        "task_id": "task-rehearsal-train",
        "message_type": "error",
        "sequence": 1,
        "artifact_id": None,
        "payload": {
            "code": "training.data_rejected",
            "stage": "training",
            "message": "训练数据不足",
            "location": None,
            "retryable": False,
        },
    }


def write_metrics(run_dir: Path, timings: dict | None) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    payload: dict = {"run_id": "rehearsal-0001"}
    if timings is not None:
        payload["timings_seconds"] = timings
    (run_dir / "metrics.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def test_training_stage_ok_with_result_envelope(tmp_path: Path) -> None:
    module = load_rehearsal()
    envelope = training_result_envelope()
    assert "ok" not in envelope

    entry = module.training_stage(envelope, 0, 4.421, tmp_path / "run")

    assert entry["ok"] is True
    assert entry["name"] == "训练"
    assert entry["seconds"] == 4.421
    assert entry["epochs"] == module.EPOCHS
    assert entry["image_size"] == module.IMAGE_SIZE
    # 没有内层计时来源时不写虚假的 train_seconds: 0。
    assert "train_seconds" not in entry


def test_training_stage_seconds_from_metrics_timings(tmp_path: Path) -> None:
    module = load_rehearsal()
    run_dir = tmp_path / "run"
    write_metrics(
        run_dir,
        {"feature_extraction": 0.2725, "head_training": 0.0963, "total": 0.4339},
    )

    entry = module.training_stage(training_result_envelope(), 0, 4.421, run_dir)

    assert entry["ok"] is True
    assert entry["train_seconds"] == 0.434


def test_training_stage_rejects_error_envelope(tmp_path: Path) -> None:
    module = load_rehearsal()

    entry = module.training_stage(
        training_error_envelope(), 1, 1.2, tmp_path / "run"
    )

    assert entry["ok"] is False


def test_training_stage_rejects_nonzero_exit(tmp_path: Path) -> None:
    module = load_rehearsal()

    entry = module.training_stage(
        training_result_envelope(), 1, 4.421, tmp_path / "run"
    )

    assert entry["ok"] is False


def test_training_stage_rejects_non_result_envelope(tmp_path: Path) -> None:
    module = load_rehearsal()
    envelope = training_result_envelope()
    envelope["message_type"] = "progress"

    entry = module.training_stage(envelope, 0, 0.5, tmp_path / "run")

    assert entry["ok"] is False


def test_cli_stage_still_uses_ok_field(tmp_path: Path) -> None:
    """项目/发布等 CLI 阶段仍返回 {"ok": ...}，判定口径不变。"""
    module = load_rehearsal()

    assert module.stage("创建项目", {"ok": True}, 0.2)["ok"] is True
    assert module.stage("创建项目", {"ok": False}, 0.2)["ok"] is False
    assert module.stage("创建项目", {}, 0.2)["ok"] is False
