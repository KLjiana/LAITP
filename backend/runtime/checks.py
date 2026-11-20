"""固定样本校验：用部署端运行时重新推理并与包内参考结果比较。

这是契约第 5 节“电脑加载”要求的一部分：首次在某个运行环境加载模型时，
必须执行固定样本验证，不能只检查文件摘要。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from ..contracts import integrity, paths
from ..contracts.errors import Code, Report, Stage
from .inference import ModelPackageRuntime, RuntimeInferenceError

DEFAULT_ABS_TOLERANCE = 1e-3


@dataclass(frozen=True)
class FixedSampleCheck:
    name: str
    sample: str
    reference: str
    max_abs_diff: float
    expected_class_id: int
    actual_class_id: int
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "sample": self.sample,
            "reference": self.reference,
            "max_abs_diff": self.max_abs_diff,
            "expected_class_id": self.expected_class_id,
            "actual_class_id": self.actual_class_id,
            "passed": self.passed,
        }


def load_thresholds(package_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    thresholds = manifest.get("validation", {}).get("thresholds")
    if not thresholds:
        return {"logit_abs_tolerance": DEFAULT_ABS_TOLERANCE}
    relative = thresholds["path"]
    resolved = paths.resolve_in_package(package_dir, relative)
    if resolved is None or not resolved.is_file():
        return {"logit_abs_tolerance": DEFAULT_ABS_TOLERANCE}
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"logit_abs_tolerance": DEFAULT_ABS_TOLERANCE}
    return data


def check_fixed_samples(
    runtime: ModelPackageRuntime, report: Report
) -> dict[str, Any]:
    """对包内全部固定样本执行推理并与参考结果比较。

    发现的问题追加到 ``report``；返回可直接放入命令行输出的摘要。
    """
    package_dir = runtime.package_dir
    manifest = runtime.manifest
    thresholds = load_thresholds(package_dir, manifest)
    abs_tolerance = float(thresholds.get("logit_abs_tolerance", DEFAULT_ABS_TOLERANCE))

    samples: Sequence[dict[str, Any]] = manifest["validation"]["samples"]
    results: list[FixedSampleCheck] = []
    max_abs_diff = 0.0
    agreements = 0

    for index, sample in enumerate(samples):
        location = f"validation.samples[{index}]"
        reference_path = paths.resolve_in_package(package_dir, sample["reference_output"])
        if reference_path is None or not reference_path.is_file():
            report.add(
                Code.RUNTIME_FIXED_SAMPLE_MISMATCH,
                Stage.RUNTIME,
                location,
                f"参考结果 {sample['reference_output']!r} 不存在",
            )
            continue
        try:
            expected = json.loads(reference_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            report.add(
                Code.RUNTIME_FIXED_SAMPLE_MISMATCH,
                Stage.RUNTIME,
                location,
                f"无法读取参考结果：{error}",
            )
            continue

        try:
            tensor = runtime.preprocess_file(package_dir / sample["path"])
            result = runtime.predict_file(package_dir / sample["path"])
        except RuntimeInferenceError as error:
            report.add(error.code, Stage.RUNTIME, location, error.message)
            continue

        expected_digest = expected.get("input", {}).get("tensor_sha256")
        actual_digest = integrity.sha256_bytes(tensor.tobytes())
        if expected_digest and actual_digest != expected_digest:
            report.add(
                Code.RUNTIME_INPUT_MISMATCH,
                Stage.RUNTIME,
                f"{location}.input",
                f"预处理后输入张量摘要 {actual_digest} 与参考结果 {expected_digest} 不一致，"
                "说明两端预处理实现存在差异",
            )

        expected_raw = np.asarray(expected.get("raw_output", []), dtype=np.float32).reshape(-1)
        actual_raw = np.asarray(result.raw_output, dtype=np.float32)
        if expected_raw.shape != actual_raw.shape:
            report.add(
                Code.RUNTIME_OUTPUT_INVALID,
                Stage.RUNTIME,
                location,
                f"参考输出长度 {expected_raw.size} 与实际 {actual_raw.size} 不一致",
            )
            continue
        difference = float(np.max(np.abs(actual_raw - expected_raw)))
        max_abs_diff = max(max_abs_diff, difference)
        expected_class = int(expected.get("prediction", {}).get("class_id", -1))
        actual_class = result.predictions[0].class_id
        passed = difference <= abs_tolerance and expected_class == actual_class
        if difference > abs_tolerance:
            report.add(
                Code.RUNTIME_FIXED_SAMPLE_MISMATCH,
                Stage.RUNTIME,
                location,
                f"原始输出最大差异 {difference:.6g} 超过阈值 {abs_tolerance}",
            )
        if expected_class != actual_class:
            report.add(
                Code.RUNTIME_FIXED_SAMPLE_MISMATCH,
                Stage.RUNTIME,
                location,
                f"预测类别 {actual_class} 与参考结果 {expected_class} 不一致",
            )
        if actual_class == expected_class:
            agreements += 1
        results.append(
            FixedSampleCheck(
                name=str(sample.get("name", f"sample-{index}")),
                sample=sample["path"],
                reference=sample["reference_output"],
                max_abs_diff=difference,
                expected_class_id=expected_class,
                actual_class_id=actual_class,
                passed=passed,
            )
        )

    return {
        "count": len(results),
        "max_abs_diff": max_abs_diff,
        "prediction_agreement": (agreements / len(results)) if results else 0.0,
        "abs_tolerance": abs_tolerance,
        "samples": [item.to_dict() for item in results],
        "passed": all(item.passed for item in results) and len(results) > 0,
    }
