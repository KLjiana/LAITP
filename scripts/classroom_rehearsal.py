"""课堂演练：用真实公开数据走一遍“建项目 → 批量导入 → 检查 → 训练 → 发布 → 预测”，
记录各阶段耗时与准确率，作为课堂时间预算（验收清单 A14）的单机参考。

数据来自 artifacts/real-data/sources（Fashion-MNIST 3 类子集，每类 20+20 训练批次、
10 张测试图）。结果写入 artifacts/classroom-rehearsal/result.json。

用法：
    .venv\\Scripts\\python.exe scripts/classroom_rehearsal.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
OUTPUT_ROOT = ROOT / "artifacts/classroom-rehearsal"
SOURCE_ROOT = ROOT / "artifacts/real-data/sources"
WEIGHTS = ROOT / "configs/weights.v1.json"
CLASSES = ("T恤", "裤子", "外套")
EPOCHS = 20
IMAGE_SIZE = 96
RUN_ID = "rehearsal-0001"


def run(arguments: list[str], cwd: Path = ROOT) -> tuple[int, str, str, float]:
    start = time.perf_counter()
    completed = subprocess.run(
        [PYTHON, "-m", *arguments], cwd=cwd, capture_output=True
    )
    duration = time.perf_counter() - start
    return (
        completed.returncode,
        completed.stdout.decode("utf-8", "replace"),
        completed.stderr.decode("utf-8", "replace"),
        duration,
    )


def parse_last_json(text: str) -> dict:
    stripped = text.strip()
    if stripped:
        try:
            value = json.loads(stripped)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    return value
            except json.JSONDecodeError:
                continue
    return {}


def result_envelope_ok(exit_code: int, envelope: dict) -> bool:
    """判定 worker 任务是否成功。

    任务 worker 的结果信封（``message_type: "result"``）没有顶层 ``ok`` 字段，
    成功与否应看进程退出码与消息类型，任务结果在 ``payload`` 中；不能用
    ``envelope["ok"]`` 判定，否则成功的训练会被记成 ``ok: false``。
    """
    if exit_code != 0:
        return False
    if envelope.get("message_type") != "result":
        return False
    payload = envelope.get("payload")
    return isinstance(payload, dict) and bool(payload)


def read_training_seconds(run_dir: Path) -> float | None:
    """读取训练进程内部计时（``metrics.json`` 的 ``timings_seconds.total``）。

    这是训练代码自己计时的特征提取与分类头训练耗时；阶段 ``seconds`` 是整段
    子进程墙钟（含启动、权重加载、产物写出）。没有可靠来源时返回 ``None``，
    不写虚假的 0。
    """
    try:
        text = (Path(run_dir) / "metrics.json").read_text(encoding="utf-8")
        metrics = json.loads(text)
    except (OSError, ValueError):
        return None
    if not isinstance(metrics, dict):
        return None
    timings = metrics.get("timings_seconds")
    if not isinstance(timings, dict):
        return None
    seconds = timings.get("total")
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        return None
    if seconds <= 0:
        return None
    return round(float(seconds), 3)


def training_stage(
    envelope: dict, exit_code: int, duration: float, run_dir: Path
) -> dict:
    extra: dict = {"epochs": EPOCHS, "image_size": IMAGE_SIZE}
    train_seconds = read_training_seconds(run_dir)
    if train_seconds is not None:
        extra["train_seconds"] = train_seconds
    return stage(
        "训练",
        envelope,
        duration,
        extra,
        ok=result_envelope_ok(exit_code, envelope),
    )


def stage(
    name: str,
    result: dict,
    duration: float,
    extra: dict | None = None,
    *,
    ok: bool | None = None,
) -> dict:
    entry = {
        "name": name,
        "seconds": round(duration, 3),
        "ok": result.get("ok") is True if ok is None else bool(ok),
    }
    if extra:
        entry.update(extra)
    return entry


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    if OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT)
    OUTPUT_ROOT.mkdir(parents=True)

    train_tree = OUTPUT_ROOT / "导入/训练"
    test_tree = OUTPUT_ROOT / "导入/测试"
    for name in CLASSES:
        for batch in ("batch-a", "batch-b"):
            shutil.copytree(
                SOURCE_ROOT / name / batch, train_tree / name / batch
            )
        shutil.copytree(SOURCE_ROOT / name / "batch-test", test_tree / name / "batch-test")

    project_root = OUTPUT_ROOT / "项目"
    stages: list[dict] = []
    failures: list[str] = []

    exit_code, stdout, stderr, duration = run(
        [
            "backend.project", "create",
            "--root", str(project_root),
            "--name", "课堂演练",
            "--classes", *CLASSES,
        ]
    )
    created = parse_last_json(stdout)
    stages.append(stage("创建项目", created, duration))
    if exit_code != 0 or created.get("ok") is not True:
        failures.append("创建项目失败：" + (stderr or stdout)[-300:])

    if not failures:
        exit_code, stdout, stderr, duration = run(
            [
                "backend.project", "import-tree",
                "--root", str(project_root),
                "--source", str(train_tree),
            ]
        )
        imported = parse_last_json(stdout)
        stages.append(
            stage(
                "批量导入（训练）",
                imported,
                duration,
                {"imported": imported.get("imported"), "batches": imported.get("batches")},
            )
        )
        if exit_code != 0 or imported.get("ok") is not True:
            failures.append("训练集导入失败：" + (stderr or stdout)[-300:])

        exit_code, stdout, stderr, duration = run(
            [
                "backend.project", "import-tree",
                "--root", str(project_root),
                "--source", str(test_tree),
                "--split", "test",
            ]
        )
        test_imported = parse_last_json(stdout)
        stages.append(
            stage(
                "批量导入（测试）",
                test_imported,
                duration,
                {"imported": test_imported.get("imported")},
            )
        )
        if exit_code != 0 or test_imported.get("ok") is not True:
            failures.append("测试集导入失败：" + (stderr or stdout)[-300:])

    if not failures:
        exit_code, stdout, stderr, duration = run(
            ["backend.project", "check-dataset", "--root", str(project_root)]
        )
        check = parse_last_json(stdout)
        stages.append(
            stage("数据检查", check, duration, {"policy": check.get("policy")})
        )
        if check.get("ok") is not True:
            failures.append("数据检查未通过：" + (stderr or stdout)[-300:])

    run_result: dict = {}
    report: dict = {}
    if not failures:
        dataset_manifest = project_root / "data" / "dataset-manifest.json"
        run_dir = project_root / "runs" / RUN_ID
        exit_code, stdout, stderr, duration = run(
            [
                "backend.runtime.worker", "train",
                "--dataset", str(dataset_manifest),
                "--data-root", str(project_root / "data"),
                "--output", str(project_root / "runs"),
                "--run-id", RUN_ID,
                "--weights-config", str(WEIGHTS),
                "--epochs", str(EPOCHS),
                "--batch-size", "16",
                "--image-size", str(IMAGE_SIZE),
                "--request-id", "req-rehearsal-train",
                "--project-id", "proj-rehearsal",
                "--task-id", "task-rehearsal-train",
            ]
        )
        run_result = parse_last_json(stdout)
        train_stage = training_stage(run_result, exit_code, duration, run_dir)
        stages.append(train_stage)
        if not train_stage["ok"]:
            failures.append("训练失败：" + (stderr or stdout)[-300:])

    if not failures:
        exit_code, stdout, stderr, duration = run(
            [
                "backend.project", "publish-training",
                "--root", str(project_root),
                "--run", "runs/rehearsal-0001",
            ]
        )
        published = parse_last_json(stdout)
        stages.append(
            stage(
                "发布（导出 ONNX）",
                published,
                duration,
                {"artifact_id": published.get("artifact_id")},
            )
        )
        if exit_code != 0 or published.get("ok") is not True:
            failures.append("发布失败：" + (stderr or stdout)[-300:])

        exit_code, stdout, stderr, duration = run(
            ["backend.classification", "report", "--run", str(project_root / "runs/rehearsal-0001")]
        )
        report_payload = parse_last_json(stdout)
        report = report_payload.get("report", {})
        stages.append(
            stage(
                "训练报告",
                report_payload,
                duration,
                {
                    "accuracy": report.get("accuracy"),
                    "loss": report.get("loss"),
                    "best_epoch": report.get("best_epoch"),
                },
            )
        )
        if exit_code != 0 or report_payload.get("ok") is not True:
            failures.append("训练报告失败：" + (stderr or stdout)[-300:])

    predict_samples: list[dict] = []
    artifact_id = ""
    for entry in stages:
        if entry.get("artifact_id"):
            artifact_id = entry["artifact_id"]
    package = project_root / "exports" / artifact_id / "model-package" if artifact_id else None
    if not failures and package is not None and package.is_dir():
        images = sorted((project_root / "data/test-images").rglob("*.png"))
        for index, image in enumerate(images):
            exit_code, stdout, stderr, duration = run(
                [
                    "backend.runtime.worker", "predict",
                    "--package", str(package),
                    "--image", str(image),
                    "--request-id", f"req-rehearsal-predict-{index}",
                    "--project-id", "proj-rehearsal",
                    "--task-id", f"task-rehearsal-predict-{index}",
                ]
            )
            payload = parse_last_json(stdout)
            prediction = (
                payload.get("payload", {}).get("predictions", [{}])[0]
                if payload.get("message_type") == "result"
                else {}
            )
            predict_samples.append(
                {
                    "image": str(image.relative_to(project_root / "data")),
                    "seconds": round(duration, 3),
                    "label": prediction.get("label"),
                    "confidence": prediction.get("confidence"),
                }
            )
        latencies = sorted(item["seconds"] for item in predict_samples)
        stages.append(
            {
                "name": "预测（逐张）",
                "count": len(predict_samples),
                "seconds_total": round(sum(latencies), 3),
                "seconds_median": latencies[len(latencies) // 2] if latencies else 0,
                "ok": len(predict_samples) > 0,
            }
        )

    required = {"create_seconds": 0}
    summary = {
        "ok": not failures,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "dataset": "Fashion-MNIST 3 类子集（每类 40 训练 + 10 测试）",
        "epochs": EPOCHS,
        "image_size": IMAGE_SIZE,
        "stages": stages,
        "stage_seconds_total": round(sum(item.get("seconds", 0) for item in stages), 3),
        "report": {
            "accuracy": report.get("accuracy"),
            "loss": report.get("loss"),
            "macro_recall": report.get("macro_recall"),
            "confusion": report.get("confusion"),
        },
        "predictions": predict_samples,
        "failures": failures,
    }
    del required
    (OUTPUT_ROOT / "result.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"ok": summary["ok"], "output": str(OUTPUT_ROOT / "result.json")}, ensure_ascii=False))
    for item in stages:
        print(f"- {item['name']}: {item.get('seconds', item.get('seconds_total'))}s")
    print("accuracy:", summary["report"]["accuracy"])
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
