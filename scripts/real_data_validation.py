"""真实公开数据集验证（开发期可复现脚本，不随产品分发数据）。

默认使用 Fashion-MNIST（MIT 许可）抽取 3 类小样本，走完整链路：
导入 → 数据检查 → 训练 → 发布（导出 ONNX）→ 报告 → 预测 → 项目校验。

用法：
    .venv\\Scripts\\python.exe scripts\\real_data_validation.py
产物写入 artifacts/real-data/（已忽略，不提交）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from torchvision.datasets import FashionMNIST

from backend.classification.report import load_training_report
from backend.project.dataset import check_dataset, import_images, rebuild_dataset
from backend.project.project import (
    PROJECT_FILE,
    create_project,
    load_project,
    publish_training,
    verify_project,
)

CLASSES = (("T恤", 0), ("裤子", 1), ("外套", 2))
TRAIN_PER_CLASS = 40
TEST_PER_CLASS = 10


def _sources(dataset_root: Path, source_root: Path) -> dict[str, dict[str, int]]:
    train = FashionMNIST(root=str(dataset_root), train=True, download=True)
    test = FashionMNIST(root=str(dataset_root), train=False, download=True)
    saved = {name: {"train": 0, "test": 0} for name, _ in CLASSES}
    for image, label in train:
        for name, index in CLASSES:
            if label == index and saved[name]["train"] < TRAIN_PER_CLASS:
                position = saved[name]["train"]
                batch = "batch-a" if position < TRAIN_PER_CLASS // 2 else "batch-b"
                target = source_root / name / batch / f"train-{position:03d}.png"
                target.parent.mkdir(parents=True, exist_ok=True)
                image.save(target)
                saved[name]["train"] += 1
        if all(value["train"] >= TRAIN_PER_CLASS for value in saved.values()):
            break
    for image, label in test:
        for name, index in CLASSES:
            if label == index and saved[name]["test"] < TEST_PER_CLASS:
                position = saved[name]["test"]
                target = source_root / name / "batch-test" / f"test-{position:03d}.png"
                target.parent.mkdir(parents=True, exist_ok=True)
                image.save(target)
                saved[name]["test"] += 1
        if all(value["test"] >= TEST_PER_CLASS for value in saved.values()):
            break
    return saved


def _run_worker(arguments: list[str]) -> tuple[int, list[dict], str]:
    completed = subprocess.run(
        [sys.executable, "-m", "backend.runtime.worker", *arguments],
        capture_output=True,
    )
    messages = [
        json.loads(line)
        for line in completed.stdout.decode("utf-8").splitlines()
        if line.strip()
    ]
    return completed.returncode, messages, completed.stderr.decode("utf-8", "replace")


def _provenance(dataset_root: Path) -> dict:
    raw = dataset_root / "FashionMNIST" / "raw"
    files = {}
    if raw.is_dir():
        for path in sorted(raw.iterdir()):
            if path.is_file() and not path.name.endswith(".gz"):
                files[path.name] = {
                    "size": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
    return {
        "dataset": "Fashion-MNIST",
        "source_url": "https://github.com/zalandoresearch/fashion-mnist",
        "license": "MIT",
        "license_url": "https://github.com/zalandoresearch/fashion-mnist/blob/master/LICENSE",
        "train_size": 60000,
        "test_size": 10000,
        "raw_files": files,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="公开数据集真实链路验证")
    parser.add_argument("--dataset-root", default="artifacts/datasets")
    parser.add_argument("--project-root", default="artifacts/real-data/fashion-project")
    parser.add_argument("--source-root", default="artifacts/real-data/sources")
    parser.add_argument("--output", default="artifacts/real-data/result.json")
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--image-size", type=int, default=96)
    parser.add_argument("--weights-config", default="configs/weights.v1.json")
    args = parser.parse_args(argv)

    dataset_root = Path(args.dataset_root)
    project_root = Path(args.project_root)
    source_root = Path(args.source_root)
    output = Path(args.output)

    for folder in (project_root, source_root):
        shutil.rmtree(folder, ignore_errors=True)

    names = [name for name, _ in CLASSES]
    create_project(
        project_root,
        project_id="proj-real-0001",
        name="真实数据验证（Fashion-MNIST 子集）",
        classes=names,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    saved = _sources(dataset_root, source_root)

    imports = {}
    for name in names:
        for batch in ("batch-a", "batch-b"):
            result = import_images(
                project_root,
                class_name=name,
                source_dir=source_root / name / batch,
                batch=batch,
            )
            imports[f"{name}/{batch}"] = {
                "imported": result.imported,
                "manifest_ok": result.manifest_path is not None,
            }
        test_result = import_images(
            project_root,
            class_name=name,
            source_dir=source_root / name / "batch-test",
            split="test",
            batch="batch-test",
        )
        imports[f"{name}/test"] = {
            "imported": test_result.imported,
            "manifest_ok": test_result.manifest_path is not None,
        }
    rebuild_dataset(project_root)

    check = check_dataset(project_root)
    run_id = "run-real-0001"
    data_root = project_root / "data"
    manifest_path = data_root / "dataset-manifest.json"
    train_args = [
        "train",
        "--dataset", str(manifest_path),
        "--data-root", str(data_root),
        "--output", str(project_root / "runs"),
        "--run-id", run_id,
        "--weights-config", args.weights_config,
        "--epochs", str(args.epochs),
        "--batch-size", "16",
        "--image-size", str(args.image_size),
        "--request-id", "req-real-train",
        "--project-id", "proj-real-0001",
        "--task-id", "task-real-train",
    ]
    train_exit, train_messages, train_stderr = _run_worker(train_args)
    progress = [
        (message["payload"].get("stage"), message["payload"].get("completed"),
         message["payload"].get("total"))
        for message in train_messages
        if message["message_type"] == "progress"
    ]
    train_result = next(
        (message for message in train_messages if message["message_type"] == "result"),
        None,
    )

    run_dir = project_root / "runs" / run_id
    report = load_training_report(run_dir) if run_dir.is_dir() else None
    published = publish_training(project_root, run_dir=run_dir, platform="windows-x64")

    test_image = source_root / names[0] / "batch-test" / "test-000.png"
    predict_exit, predict_messages, _ = _run_worker(
        [
            "predict",
            "--package", published["package_dir"],
            "--image", str(test_image),
            "--request-id", "req-real-predict",
            "--project-id", "proj-real-0001",
            "--task-id", "task-real-predict",
        ]
    )
    predict_result = next(
        (message for message in predict_messages if message["message_type"] == "result"),
        None,
    )
    project = load_project(project_root / PROJECT_FILE)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provenance": _provenance(dataset_root),
        "subset": {
            "classes": names,
            "fashion_mnist_indices": [index for _, index in CLASSES],
            "saved": saved,
            "images_per_class_train": TRAIN_PER_CLASS,
            "images_per_class_test": TEST_PER_CLASS,
        },
        "imports": imports,
        "dataset_check": {
            "ok": check["ok"],
            "counts": check["counts"],
            "issues": check["issues"],
        },
        "training": {
            "exit": train_exit,
            "stderr_tail": train_stderr[-500:],
            "progress_stages": progress,
            "artifact": train_result["payload"]["artifact"]["artifact_id"]
            if train_result else None,
            "elo": train_result["payload"]["artifact"]["manifest_sha256"]
            if train_result else None,
        },
        "report": None if report is None else {
            "accuracy": report["accuracy"],
            "loss": report["loss"],
            "per_class_recall": report["per_class_recall"],
            "confusion_matrix": report["confusion_matrix"],
            "best_epoch": report["best_epoch"],
            "epochs": report["epochs"],
            "validation_samples": report["validation_samples"],
            "timings_seconds": report["timings_seconds"],
        },
        "published": published,
        "predict": {
            "exit": predict_exit,
            "predictions": predict_result["payload"].get("predictions")
            if predict_result else None,
        },
        "project": {
            "current_model_artifact_id": project.current_model_artifact_id,
            "models": [
                {"artifact_id": model.artifact_id, "kind": model.kind}
                for model in project.models
            ],
            "verify_ok": verify_project(project_root).ok,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "check_ok": payload["dataset_check"]["ok"],
        "train_exit": train_exit,
        "accuracy": payload["report"]["accuracy"] if payload["report"] else None,
        "published": published["artifact_id"],
        "predict_exit": predict_exit,
        "verify_ok": payload["project"]["verify_ok"],
        "counts": payload["dataset_check"]["counts"].get("splits"),
    }, ensure_ascii=False))
    return 0 if (
        payload["dataset_check"]["ok"]
        and train_exit == 0
        and predict_exit == 0
        and payload["project"]["verify_ok"]
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
