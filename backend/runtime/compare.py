"""模型对比：一次加载两个模型包，对同一批图片分别预测并比较准确率与分歧样本。

用法：
    python -m backend.runtime.compare ^
        --packages <包A> <包B> --images <图片目录> [--output result.json] [--csv result.csv]

目录约定与批量预测（``backend.runtime.batch``）一致：图片按
``类别/批次/*.png`` 组织时，最上层目录名作为真实类别；直接放在根目录的
图片不做准确率统计（仍会预测）。

输出 JSON 中 ``packages`` 按命令行顺序排列，每张图片明细里的 ``packages``
子数组与之一一对应。``agreement`` 只统计两个包都预测成功的图片；任一包在
某张图片上失败时，该图片记入 ``errors`` 并跳过，不影响其余图片继续对比。
全部图片处理完后，若存在 ``errors`` 或没有可对比图片，则 ``ok`` 为 false、
退出码为 1（与批量预测一致）。

加载完成后先比较两个包各自的标签列表（``runtime.labels``，即清单声明的标签
文件内容与顺序）：完全一致时顶层 ``labels_match`` 为 true；不一致时
``labels_match`` 为 false，并在顶层输出 ``labels_a``、``labels_b``（两包标签
列表），同时向 ``warnings`` 追加提示。标签不一致只是提示，仍照常预测并统计，
``ok`` 与退出码语义不变；但预测标签按各自包的类别索引映射，按标签字符串
比较的 ``accuracy`` 与 ``agreement`` 可能不可比。

传入 ``--csv`` 时额外写出逐图对比 CSV（UTF-8 BOM、``newline=""``，与批量
预测一致，Excel 可直接打开）：无标签平铺目录下真实类别与是否正确留空；JSON
结果中增加 ``csv`` 字段记录导出路径。CSV 写入失败时输出错误 JSON 并返回
退出码 1。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

from .batch import discover_images, true_label_for
from .inference import ModelPackageRuntime, RuntimeInferenceError

CSV_HEADER = [
    "图片",
    "真实类别",
    "A 预测",
    "A 置信度",
    "A 是否正确",
    "B 预测",
    "B 置信度",
    "B 是否正确",
    "是否一致",
]


def _error_output(message: str, **extra: Any) -> dict[str, Any]:
    """构造命令失败时的 JSON；``extra`` 用于补充出错包等定位信息。"""
    return {"ok": False, "error": message, **extra}


def _correct_cell(correct: bool | None) -> str | int:
    """无标签时留空；有标签时写 1/0（与批量预测 CSV 一致）。"""
    return "" if correct is None else int(correct)


def _write_comparison_csv(path: Path, images: list[dict[str, Any]]) -> None:
    """写出逐图对比 CSV；UTF-8 BOM 与 ``newline=""`` 保证 Excel 正确打开。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADER)
        for item in images:
            entry_a, entry_b = item["packages"]
            writer.writerow(
                [
                    item["image"],
                    item["true_label"] or "",
                    entry_a["predicted_label"],
                    entry_a["confidence"],
                    _correct_cell(entry_a["correct"]),
                    entry_b["predicted_label"],
                    entry_b["confidence"],
                    _correct_cell(entry_b["correct"]),
                    int(item["agree"]),
                ]
            )


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    parser = argparse.ArgumentParser(description="LAITP 模型对比")
    parser.add_argument(
        "--packages",
        nargs=2,
        required=True,
        metavar=("PACKAGE_A", "PACKAGE_B"),
        help=(
            "依次指定两个模型产物包；加载后比较标签顺序与内容，不一致时输出 "
            "labels_match/labels_a/labels_b 与 warnings 提示（不影响 ok）"
        ),
    )
    parser.add_argument("--images", required=True, help="测试图片目录")
    parser.add_argument("--output", default=None, help="把对比结果 JSON 写入文件")
    parser.add_argument(
        "--csv", default=None, help="导出逐图对比结果 CSV（Excel 可直接打开）"
    )
    args = parser.parse_args(argv)

    packages = [Path(path) for path in args.packages]
    image_root = Path(args.images)

    for index, package in enumerate(packages):
        if not package.is_dir():
            _print_json(
                _error_output(
                    f"模型包不存在：{package}",
                    package=str(package),
                    package_index=index,
                )
            )
            return 1
    if not image_root.is_dir():
        _print_json(_error_output(f"图片目录不存在：{image_root}"))
        return 1

    runtimes: list[ModelPackageRuntime] = []
    for index, package in enumerate(packages):
        try:
            runtimes.append(ModelPackageRuntime.load(package))
        except RuntimeInferenceError as error:
            _print_json(
                _error_output(
                    str(error),
                    code=error.code,
                    package=str(package),
                    package_index=index,
                )
            )
            return 1

    # 两个包的标签顺序与内容必须一致，准确率/一致率才按同一语义比较；
    # 不一致时仍照常预测统计，只提示不可比，不改变 ok 与退出码。
    labels_a = list(runtimes[0].labels)
    labels_b = list(runtimes[1].labels)
    labels_match = labels_a == labels_b
    warnings: list[str] = []
    if not labels_match:
        warnings.append("两个模型包的标签集/顺序不一致，准确率与一致率可能不可比")

    images = discover_images(image_root)
    image_results: list[dict[str, Any]] = []
    disagreements: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    labeled = 0
    agreement_count = 0
    correct_counts = [0, 0]
    per_class_total = [Counter(), Counter()]
    per_class_correct = [Counter(), Counter()]
    package_seconds: list[list[float]] = [[], []]

    for image in images:
        relative = str(image.relative_to(image_root))
        true_label = true_label_for(image, image_root)
        predicted_labels: list[str] = []
        confidences: list[float] = []
        timings: list[float] = []
        failed_index: int | None = None
        failed_error: Exception | None = None
        for index, runtime in enumerate(runtimes):
            started = time.perf_counter()
            try:
                prediction = runtime.predict_file(image)
            except Exception as error:  # 单张失败不影响其余图片
                failed_index = index
                failed_error = error
                break
            timings.append(time.perf_counter() - started)
            top = prediction.predictions[0]
            predicted_labels.append(top.label)
            confidences.append(top.probability)
        if failed_index is not None:
            errors.append(
                {
                    "image": relative,
                    "package": str(packages[failed_index]),
                    "package_index": failed_index,
                    "error": str(failed_error),
                }
            )
            continue

        is_correct = [
            bool(true_label) and label == true_label for label in predicted_labels
        ]
        if true_label:
            labeled += 1
        for index in range(len(runtimes)):
            package_seconds[index].append(timings[index])
            if true_label:
                per_class_total[index][true_label] += 1
                if is_correct[index]:
                    correct_counts[index] += 1
                    per_class_correct[index][true_label] += 1

        agree = predicted_labels[0] == predicted_labels[1]
        if agree:
            agreement_count += 1
        image_results.append(
            {
                "image": relative,
                "true_label": true_label or None,
                "agree": agree,
                "packages": [
                    {
                        "package": str(packages[index]),
                        "artifact_id": runtimes[index].artifact_id,
                        "predicted_label": predicted_labels[index],
                        "confidence": round(confidences[index], 6),
                        "correct": is_correct[index] if true_label else None,
                        "seconds": round(timings[index], 4),
                    }
                    for index in range(len(runtimes))
                ],
            }
        )
        if not agree:
            disagreements.append(
                {
                    "image": relative,
                    "true_label": true_label or None,
                    "pred_a": predicted_labels[0],
                    "pred_b": predicted_labels[1],
                    "confidence_a": round(confidences[0], 6),
                    "confidence_b": round(confidences[1], 6),
                    "correct_a": is_correct[0] if true_label else None,
                    "correct_b": is_correct[1] if true_label else None,
                }
            )

    compared = len(image_results)
    package_reports: list[dict[str, Any]] = []
    for index, runtime in enumerate(runtimes):
        per_class = {
            label: {
                "count": per_class_total[index][label],
                "correct": per_class_correct[index][label],
                "accuracy": round(
                    per_class_correct[index][label] / per_class_total[index][label], 6
                ),
            }
            for label in sorted(per_class_total[index])
        }
        mean_seconds = (
            round(sum(package_seconds[index]) / len(package_seconds[index]), 4)
            if package_seconds[index]
            else None
        )
        package_reports.append(
            {
                "package": str(packages[index]),
                "artifact_id": runtime.artifact_id,
                "labels": list(runtime.labels),
                "accuracy": (
                    round(correct_counts[index] / labeled, 6) if labeled else None
                ),
                "per_class": per_class,
                "mean_seconds": mean_seconds,
            }
        )

    payload = {
        "ok": bool(compared) and not errors,
        "count": compared,
        "labeled": labeled,
        "labels_match": labels_match,
        "labels_a": labels_a,
        "labels_b": labels_b,
        "warnings": warnings,
        "packages": package_reports,
        "agreement": {
            "count": agreement_count,
            "total": compared,
            "ratio": round(agreement_count / compared, 6) if compared else None,
        },
        "disagreements": disagreements,
        "errors": errors,
        "images": image_results,
    }
    if args.csv:
        csv_path = Path(args.csv)
        try:
            _write_comparison_csv(csv_path, image_results)
        except (OSError, csv.Error) as error:
            _print_json(
                _error_output(
                    f"CSV 写入失败：{error}",
                    csv=str(csv_path),
                )
            )
            return 1
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
