"""批量预测：一次加载模型包，对目录内图片逐张预测并汇总准确率。

用法：
    python -m backend.runtime.batch predict ^
        --package <model-package> --images <图片目录> [--output result.json]

目录约定：图片按 ``类别/批次/*.png`` 组织时，上一级目录名作为真实类别，
类别目录下的一级目录名作为批次；直接放在根目录的图片不做准确率统计（仍会预测），
直接放在类别目录下的图片计入 ``per_class`` 但不计入 ``per_batch``。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter
from pathlib import Path

from .inference import ModelPackageRuntime, RuntimeInferenceError

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


def discover_images(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )


def true_label_for(image: Path, root: Path) -> str:
    relative = image.relative_to(root)
    # 目录约定为 ``类别/批次/*.png``（或 ``类别/*.png``），取最上层目录作为类别。
    if len(relative.parts) <= 1:
        return ""
    return relative.parts[0]


def batch_for(image: Path, root: Path) -> str:
    # 批次为类别目录之下的一级目录名；图片直接位于类别目录下时没有批次。
    relative = image.relative_to(root)
    if len(relative.parts) <= 2:
        return ""
    return relative.parts[1]


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    parser = argparse.ArgumentParser(description="LAITP 批量预测")
    parser.add_argument("--package", required=True)
    parser.add_argument("--images", required=True)
    parser.add_argument("--output", default=None)
    parser.add_argument("--csv", default=None, help="导出逐张结果 CSV（Excel 可直接打开）")
    args = parser.parse_args(argv)

    package = Path(args.package)
    image_root = Path(args.images)
    if not package.is_dir():
        print(
            json.dumps(
                {"ok": False, "error": f"模型包不存在：{package}"}, ensure_ascii=False
            )
        )
        return 1
    if not image_root.is_dir():
        print(
            json.dumps(
                {"ok": False, "error": f"图片目录不存在：{image_root}"},
                ensure_ascii=False,
            )
        )
        return 1

    try:
        runtime = ModelPackageRuntime.load(package)
    except RuntimeInferenceError as error:
        print(
            json.dumps(
                {"ok": False, "error": str(error), "code": error.code},
                ensure_ascii=False,
            )
        )
        return 1

    images = discover_images(image_root)
    results: list[dict] = []
    errors: list[dict] = []
    correct = 0
    labeled = 0
    confusion: Counter[str] = Counter()
    per_class_total: Counter[str] = Counter()
    per_class_correct: Counter[str] = Counter()
    per_batch_total: Counter[str] = Counter()
    per_batch_correct: Counter[str] = Counter()
    for image in images:
        true_label = true_label_for(image, image_root)
        batch = batch_for(image, image_root)
        started = time.perf_counter()
        try:
            prediction = runtime.predict_file(image)
        except Exception as error:  # 单张失败不影响其余图片
            errors.append(
                {"image": str(image.relative_to(image_root)), "error": str(error)}
            )
            continue
        elapsed = time.perf_counter() - started
        top = prediction.predictions[0]
        is_correct = bool(true_label) and top.label == true_label
        if true_label:
            labeled += 1
            per_class_total[true_label] += 1
            if is_correct:
                correct += 1
                per_class_correct[true_label] += 1
            if batch:
                per_batch_total[batch] += 1
                if is_correct:
                    per_batch_correct[batch] += 1
            confusion[f"{true_label} -> {top.label}"] += 1
        results.append(
            {
                "image": str(image.relative_to(image_root)),
                "true_label": true_label or None,
                "predicted_label": top.label,
                "confidence": round(top.probability, 6),
                "correct": is_correct if true_label else None,
                "seconds": round(elapsed, 4),
            }
        )

    accuracy = round(correct / labeled, 6) if labeled else None
    per_class = {
        label: {
            "count": per_class_total[label],
            "correct": per_class_correct[label],
            "accuracy": round(
                per_class_correct[label] / per_class_total[label], 6
            ),
        }
        for label in sorted(per_class_total)
    }
    per_batch = {
        batch: {
            "count": per_batch_total[batch],
            "correct": per_batch_correct[batch],
            "accuracy": round(
                per_batch_correct[batch] / per_batch_total[batch], 6
            ),
        }
        for batch in sorted(per_batch_total)
    }
    payload = {
        "ok": bool(results) and not errors,
        "artifact_id": runtime.artifact_id,
        "count": len(results),
        "labeled": labeled,
        "accuracy": accuracy,
        "per_class": per_class,
        "per_batch": per_batch,
        "mean_seconds": round(
            sum(item["seconds"] for item in results) / len(results), 4
        )
        if results
        else None,
        "confusion": dict(confusion),
        "images": results,
        "errors": errors,
    }
    if args.csv:
        csv_path = Path(args.csv)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "图片",
                    "真实类别",
                    "预测类别",
                    "置信度",
                    "是否正确",
                    "耗时秒",
                ]
            )
            for item in results:
                writer.writerow(
                    [
                        item["image"],
                        item["true_label"] or "",
                        item["predicted_label"],
                        item["confidence"],
                        "" if item["correct"] is None else int(item["correct"]),
                        item["seconds"],
                    ]
                )
        payload["csv"] = str(csv_path)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
