"""M0 本机性能与离线链路基准（T08）。

在单个进程内完成：生成构造数据 → 建数据清单 → 训练 → 导出 → 契约校验 →
加载运行时 → 预热与延迟测量，并记录 RSS 峰值、包大小与冷启动时间。
测量结果写入 ``--output``（默认 ``artifacts/benchmark-m0``）下的 JSON 文件。

构造数据只用于测量耗时与流程，不代表真实分类效果；目标 Windows 机器的
验收仍需在目标机上重复本脚本并保留原始 JSON。
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil
from PIL import Image

from backend.classification.dataset import build_dataset_manifest
from backend.classification.export import ExportConfig, export_model
from backend.classification.preprocess import PreprocessSpec
from backend.classification.training import TrainingConfig, train
from backend.contracts.manifest import validate_model_package
from backend.runtime.inference import ModelPackageRuntime
from backend.runtime.loading import runtime_profile

REPO_ROOT = Path(__file__).resolve().parents[1]


class _RssSampler:
    def __init__(self, interval: float = 0.05) -> None:
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._process = psutil.Process()
        self.peak = 0
        self._running = False

    def start(self) -> None:
        self._running = True
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.peak = max(self.peak, self._process.memory_info().rss)
            except psutil.Error:
                break
            self._stop.wait(self._interval)

    def stop(self) -> int:
        if not self._running:
            return self.peak
        self._stop.set()
        self._thread.join(timeout=2.0)
        return self.peak


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _write_noise_image(path: Path, size: int, rng: random.Random) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = rng.randbytes(size * size * 3)
    Image.frombytes("RGB", (size, size), data).save(path, format="PNG")


def _build_synthetic_dataset(
    root: Path,
    *,
    classes: list[str],
    batches: int,
    per_batch: int,
    test_per_class: int,
    size: int,
    seed: int,
) -> None:
    rng = random.Random(seed)
    for name in classes:
        for batch in range(1, batches + 1):
            for index in range(1, per_batch + 1):
                _write_noise_image(
                    root / "images" / name / f"batch-{batch}" / f"{index:03d}.png",
                    size,
                    rng,
                )
        for index in range(1, test_per_class + 1):
            _write_noise_image(
                root / "test-images" / name / "bench-batch" / f"{index:03d}.png",
                size,
                rng,
            )


def _dir_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def _environment() -> dict[str, Any]:
    import jsonschema
    import onnx
    import onnxruntime
    import PIL
    import torch
    import torchvision

    memory = psutil.virtual_memory()
    return {
        "os": platform.platform(),
        "cpu": platform.processor() or platform.machine(),
        "physical_cores": psutil.cpu_count(logical=False),
        "logical_cores": psutil.cpu_count(logical=True),
        "ram_gb": round(memory.total / (1024**3), 1),
        "python": platform.python_version(),
        "torch": torch.__version__,
        "torchvision": torchvision.__version__,
        "onnxruntime": onnxruntime.__version__,
        "onnx": onnx.__version__,
        "pillow": PIL.__version__,
        "jsonschema": jsonschema.__version__,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    dataset_root = output / f"data-{stamp}"
    runs_root = output / f"runs-{stamp}"
    exports_root = output / f"exports-{stamp}"

    classes = args.classes
    scan_started = time.perf_counter()
    _build_synthetic_dataset(
        dataset_root,
        classes=classes,
        batches=args.train_batches,
        per_batch=args.images_per_batch,
        test_per_class=args.test_per_class,
        size=args.image_size,
        seed=args.seed,
    )
    dataset_build_seconds = time.perf_counter() - scan_started

    manifest = build_dataset_manifest(
        dataset_root,
        classes=classes,
        dataset_id=f"ds-bench-{stamp}",
        created_at=datetime.now(timezone.utc),
    )
    manifest_path = dataset_root / "dataset-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    splits = {
        split: sum(1 for sample in manifest["samples"] if sample["split"] == split)
        for split in ("train", "val", "test")
    }

    sampler = _RssSampler()
    sampler.start()
    training_started = time.perf_counter()
    training = train(
        TrainingConfig(
            run_id=f"run-bench-{stamp}",
            dataset_manifest=manifest_path,
            dataset_root=dataset_root,
            output_root=runs_root,
            weights_config=Path(args.weights_config),
            epochs=args.epochs,
            batch_size=args.batch_size,
            threads=args.threads,
            preprocess=PreprocessSpec(
                width=args.image_size, height=args.image_size
            ),
        )
    )
    training_seconds = time.perf_counter() - training_started

    export_started = time.perf_counter()
    export = export_model(
        ExportConfig(
            run_dir=training.run_dir,
            output_root=exports_root,
            artifact_id=f"art-bench-{stamp}",
            project_id="proj-benchmark",
            weights_config=Path(args.weights_config),
            data_root=dataset_root,
            created_at=datetime.now(timezone.utc),
        )
    )
    export_seconds = time.perf_counter() - export_started
    training_peak = sampler.stop()

    validation_started = time.perf_counter()
    report = validate_model_package(
        export.package_dir, runtime_profile=runtime_profile("windows-x64")
    )
    validation_seconds = time.perf_counter() - validation_started
    if not report.ok:
        raise SystemExit(
            "产物包未通过校验：" + json.dumps(report.to_dict(), ensure_ascii=False)
        )

    load_started = time.perf_counter()
    runtime = ModelPackageRuntime.load(export.package_dir)
    load_seconds = time.perf_counter() - load_started
    package_manifest = json.loads(
        (export.package_dir / "manifest.json").read_text(encoding="utf-8")
    )
    image_rel = package_manifest["validation"]["samples"][0]["path"]
    image_path = export.package_dir / image_rel

    warm_samples = []
    for index in range(args.predict_runs + 3):
        started = time.perf_counter()
        runtime.predict_file(image_path)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if index >= 3:
            warm_samples.append(elapsed_ms)

    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPO_ROOT)
    cold_started = time.perf_counter()
    cold = subprocess.run(
        [
            sys.executable,
            "-m",
            "backend.runtime",
            "predict",
            "--package",
            str(export.package_dir),
            "--image",
            str(image_path),
        ],
        capture_output=True,
        env=environment,
    )
    cold_seconds = time.perf_counter() - cold_started
    if cold.returncode != 0:
        raise SystemExit(cold.stderr.decode("utf-8", "replace"))

    evaluate_started = time.perf_counter()
    evaluated = subprocess.run(
        [
            sys.executable,
            "-m",
            "backend.runtime",
            "evaluate",
            "--package",
            str(export.package_dir),
            "--manifest",
            str(manifest_path),
            "--data-root",
            str(dataset_root),
            "--split",
            "test",
        ],
        capture_output=True,
        env=environment,
    )
    evaluate_seconds = time.perf_counter() - evaluate_started
    if evaluated.returncode != 0:
        raise SystemExit(evaluated.stderr.decode("utf-8", "replace"))

    metrics = json.loads(
        (training.run_dir / "metrics.json").read_text(encoding="utf-8")
    )
    conversion = json.loads(
        export.conversion_record_path.read_text(encoding="utf-8")
    )
    return {
        "created_at": _utc_now(),
        "environment": _environment(),
        "parameters": {
            "classes": classes,
            "image_size": args.image_size,
            "train_batches": args.train_batches,
            "images_per_batch": args.images_per_batch,
            "test_per_class": args.test_per_class,
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "threads": args.threads,
            "predict_runs": args.predict_runs,
            "synthetic_data": True,
        },
        "dataset": {
            "splits": splits,
            "images_bytes": _dir_bytes(dataset_root / "images")
            + _dir_bytes(dataset_root / "test-images"),
            "build_seconds": dataset_build_seconds,
        },
        "timings_seconds": {
            "training_total": training_seconds,
            "feature_extraction": metrics["timings_seconds"]["feature_extraction"],
            "head_training": metrics["timings_seconds"]["head_training"],
            "export": export_seconds,
            "validate": validation_seconds,
            "runtime_load": load_seconds,
            "cold_predict": cold_seconds,
            "evaluate_cold": evaluate_seconds,
        },
        "training": {
            "epochs": args.epochs,
            "best_epoch": metrics["training"]["best_epoch"],
            "val_accuracy": metrics["evaluation"]["accuracy"],
            "per_class_recall": metrics["evaluation"]["per_class_recall"],
        },
        "latency_ms": {
            "warm_runs": len(warm_samples),
            "min": min(warm_samples),
            "median": statistics.median(warm_samples),
            "p95": _percentile(warm_samples, 0.95),
            "max": max(warm_samples),
        },
        "memory_mb": {
            "training_peak_rss": training_peak / (1024**2),
            "package_bytes": _dir_bytes(export.package_dir),
            "onnx_bytes": (export.package_dir / "model.onnx").stat().st_size,
            "dataset_bytes": _dir_bytes(dataset_root),
        },
        "encodings": {
            "artifact_id": export.artifact_id,
            "fixed_samples": package_manifest["validation"]["samples"].__len__(),
            "max_abs_diff": export.checks["fixed_samples"]["max_abs_diff"],
            "conversion_status": conversion["status"],
        },
        "notes": [
            "构造数据用于测量流程耗时，不代表真实分类效果。",
            "本机为开发环境；目标 Windows 机器与课堂时间预算未确定，不据此判定课堂性能。",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M0 本机性能与离线链路基准（T08）")
    parser.add_argument(
        "--classes",
        nargs="+",
        default=["水杯", "书本", "笔袋"],
        help="类别名（顺序即类别 ID）",
    )
    parser.add_argument("--image-size", type=int, default=224)
    parser.add_argument("--train-batches", type=int, default=3)
    parser.add_argument("--images-per-batch", type=int, default=10)
    parser.add_argument("--test-per-class", type=int, default=5)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--threads", type=int, default=min(8, os.cpu_count() or 1))
    parser.add_argument("--predict-runs", type=int, default=30)
    parser.add_argument("--seed", type=int, default=20261117)
    parser.add_argument(
        "--weights-config", default=str(REPO_ROOT / "configs" / "weights.v1.json")
    )
    parser.add_argument(
        "--output", default=str(REPO_ROOT / "artifacts" / "benchmark-m0")
    )
    args = parser.parse_args(argv)

    result = run(args)
    output = Path(args.output)
    result_path = output / "m0-benchmark.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    summary = {
        "result_path": str(result_path),
        "environment": result["environment"],
        "splits": result["dataset"]["splits"],
        "timings_seconds": result["timings_seconds"],
        "latency_ms": result["latency_ms"],
        "memory_mb": result["memory_mb"],
        "val_accuracy": result["training"]["val_accuracy"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
