"""检测可行性探测工具（草案，未激活，不接入生产）。

用法：
    .venv\\Scripts\\python.exe scripts\\detection_draft_probe.py
    .venv\\Scripts\\python.exe scripts\\detection_draft_probe.py --model ssdlite
    .venv\\Scripts\\python.exe scripts\\detection_draft_probe.py --output artifacts\\detection-draft\\probe-ssdlite.json --model ssdlite
    .venv\\Scripts\\python.exe scripts\\detection_draft_probe.py --skip-fasterrcnn

本工具对应 P3/P6 的前置可行性证据收集（检测未实现/未激活）：只做
torchvision 内置检测模型的 CPU 实例化、随机输入前向、ONNX 导出、ONNX 拓扑
统计（节点数/算子集合/NMS 相关算子/控制流算子）与 onnxruntime 前向输出形状
探测；**不训练、不评估精度、不发布产物包、不接入校验/界面/课程**。模型使用
``weights=None``、``weights_backbone=None`` 随机初始化，只验证结构与导出
可行性；导出的 ONNX 只写入临时目录，分析后立即删除，不构成模型产物包，也不
分配 ``artifact_id``。

默认输出为 ``artifacts/detection-draft/probe.json``（相对仓库根目录，``artifacts/``
已在 ``.gitignore`` 中，可保留供人工查看但不提交）；可用 ``--output`` 改为任意
JSON 路径，相对路径按当前工作目录解析。默认探测 ``ssdlite`` 与 ``fasterrcnn``
两个模型，``--skip-fasterrcnn`` 可跳过较慢的 fasterrcnn，``--model`` 可只探测
其中一个。

输出 JSON 顶层固定包含 ``ok``、``tool``、``draft: true``、``activated: false``、
``notes``、``results``、``warnings`` 和 ``error``；每个模型一节记录版本、参数
数量、耗时、ONNX 体积/节点/算子、NMS 与控制流判定、onnxruntime 输出形状与
警告。任一被探测模型失败或工具异常时 ``ok`` 为 false、写入 ``error`` 并以退出
码 1 结束（仍尽力写出 JSON）。

边界：本工具通过**不表示**检测标注、训练、导出产物、电脑测试、转换/量化或板端
能力已经实现、可用或验证通过；结果只是本机单次探测，不能替代目标机验收、P3
训练实测、P6 转换工具链门槛或实物 K230 验证，也不改变检测契约草案与 Q1–Q8
待决问题的状态。
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile
import time
import warnings as warnings_module
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]

TOOL_NAME = "detection_draft_probe"
DEFAULT_OUTPUT = ROOT / "artifacts" / "detection-draft" / "probe.json"
DEFAULT_OPSET = 17
NUM_CLASSES = 3
SEED = 0
MODEL_CHOICES = ("ssdlite", "fasterrcnn")
FORWARD_WARMUP_RUNS = 1
FORWARD_TIMED_RUNS = 3
ORT_WARMUP_RUNS = 1
ORT_TIMED_RUNS = 2
MAX_CAPTURED_WARNINGS = 10

CONTROL_FLOW_OPS = ("If", "Loop", "Scan")
# 仅用于“转换风险”提示，不表示 nncase/K230 对下列算子的实际支持情况（未验证）。
CONVERSION_RISK_OPS = (
    "If",
    "Loop",
    "Scan",
    "NonZero",
    "TopK",
    "NonMaxSuppression",
    "RoiAlign",
    "GridSample",
    "ScatterND",
)
STANDARD_DOMAINS = frozenset(
    {"", "ai.onnx", "ai.onnx.ml", "ai.onnx.training", "ai.onnx.preview.training"}
)

MODEL_SPECS: dict[str, dict[str, Any]] = {
    "ssdlite": {
        "factory": "torchvision.models.detection.ssdlite320_mobilenet_v3_large",
        "display": "SSDLite320-MobileNetV3-Large",
        "input_shape": (1, 3, 320, 320),
    },
    "fasterrcnn": {
        "factory": "torchvision.models.detection.fasterrcnn_mobilenet_v3_large_320_fpn",
        "display": "FasterRCNN-MobileNetV3-Large-320-FPN",
        "input_shape": (1, 3, 320, 320),
    },
}

DRAFT_NOTES = (
    "草案探测工具，检测未实现/未激活；仅可行性探测，不训练、不发布、不接入校验/界面/课程："
    "本工具只做 torchvision 内置检测模型的 CPU 实例化、前向、ONNX 导出与拓扑/输出形状探测。",
    "结果只代表本机单次探测：不表示检测任务已实现、已激活或通过验收，也不代表 K230/K210 "
    "转换或板端可运行（本机未安装/未验证任何转换工具链与板卡）。",
    "模型使用 weights=None、weights_backbone=None 随机初始化，只验证结构与导出可行性；"
    "精度、训练耗时/收敛、许可证结论均不在本工具范围，随机权重输出不代表训练后效果。",
    "导出的 ONNX 只写入临时目录，分析后立即删除；JSON 只保留体积、SHA-256 与拓扑统计，"
    "不构成模型产物包、不分配 artifact_id，也不进入项目 data/ 或 exports/。",
    "NMS/控制流判定只用于 P3/P6 风险筛查，不改变检测契约草案，也不构成 Q3/Q5 等"
    "待决问题的决定；任何转换、量化与板端结论仍须按可行性规划第 5～6 节另行验证。",
)


class ProbeError(Exception):
    """工具无法完成探测（依赖缺失、模型选择非法等）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# --------------------------------------------------------------------------- #
# 基础 I/O 与格式化
# --------------------------------------------------------------------------- #


def _now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _emit_json(payload: Any) -> None:
    """以 UTF-8 JSON 写标准输出（Windows 控制台代码页可能是 GBK）。"""
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write(text.encode("utf-8"))
        buffer.flush()
    else:  # pragma: no cover - 只有标准输出被替换成文本流时使用
        sys.stdout.write(text)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: Any) -> None:
    """先写临时文件再整体替换，避免留下半写 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    temp_path = path.with_name(path.name + ".tmp")
    try:
        temp_path.write_text(text, encoding="utf-8")
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _display_path(path: Path) -> str:
    """仓库内路径用相对路径展示，仓库外（如 %TEMP%）保留绝对路径。"""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except (OSError, ValueError):
        return str(path.resolve())


def _round_seconds(value: float, digits: int = 4) -> float:
    return round(float(value), digits)


def _timing_stats(samples: Sequence[float], warmup_runs: int) -> dict[str, Any]:
    return {
        "warmup_runs": warmup_runs,
        "runs": len(samples),
        "mean_seconds": _round_seconds(sum(samples) / len(samples)) if samples else None,
        "min_seconds": _round_seconds(min(samples)) if samples else None,
        "max_seconds": _round_seconds(max(samples)) if samples else None,
    }


# --------------------------------------------------------------------------- #
# 纯函数：ONNX 拓扑分析（测试直接使用，不加载 torchvision 模型）
# --------------------------------------------------------------------------- #


def infer_output_names(reference: Any) -> list[str]:
    """按检测模型返回的字典键顺序推断 ONNX 输出名。"""
    if (
        isinstance(reference, (list, tuple))
        and reference
        and isinstance(reference[0], dict)
    ):
        return list(reference[0].keys())
    return ["boxes", "scores", "labels"]


def analyze_onnx(path: str | Path) -> dict[str, Any]:
    """读取 ONNX 模型并返回节点数、算子集合、NMS 与控制流判定。

    只做结构统计，不执行推理、不要求模型可转换；``nms.detected`` 为真表示图中
    出现 ``NonMaxSuppression``、名称含 ``nms`` 的算子或非标准 ONNX domain
    （自定义算子域），不区分该图是否真的做了后处理筛选。
    """
    import onnx

    model = onnx.load(str(path), load_external_data=False)
    graph = model.graph
    nodes = list(graph.node)

    op_types = sorted({node.op_type for node in nodes})
    opset_imports = [
        {"domain": item.domain, "version": int(item.version)}
        for item in model.opset_import
    ]
    node_domains = {node.domain for node in nodes if node.domain}
    custom_domains = sorted(
        {
            item["domain"]
            for item in opset_imports
            if item["domain"] not in STANDARD_DOMAINS
        }
        | {domain for domain in node_domains if domain not in STANDARD_DOMAINS}
    )

    nms_pairs = sorted(
        {
            (node.domain or "", node.op_type)
            for node in nodes
            if node.op_type == "NonMaxSuppression" or "nms" in node.op_type.lower()
        }
    )
    nms_operators = [
        {"domain": domain, "op_type": op_type} for domain, op_type in nms_pairs
    ]
    has_non_max_suppression = any(
        item["op_type"] == "NonMaxSuppression" for item in nms_operators
    )
    control_flow_operators = [op for op in CONTROL_FLOW_OPS if op in op_types]

    return {
        "node_count": len(nodes),
        "op_types": op_types,
        "op_type_count": len(op_types),
        "opset_imports": opset_imports,
        "custom_domains": custom_domains,
        "nms": {
            "detected": bool(nms_operators or custom_domains),
            "non_max_suppression": has_non_max_suppression,
            "operators": nms_operators,
            "custom_domains": custom_domains,
        },
        "control_flow": {
            "detected": bool(control_flow_operators),
            "operators": control_flow_operators,
            "if": "If" in op_types,
            "loop": "Loop" in op_types,
            "scan": "Scan" in op_types,
        },
        "conversion_risk_operators": [
            op for op in CONVERSION_RISK_OPS if op in op_types
        ],
    }


# --------------------------------------------------------------------------- #
# 环境与模型探测（重活：只由 CLI 成功路径调用，测试使用 monkeypatch 避开）
# --------------------------------------------------------------------------- #


def collect_environment() -> dict[str, Any]:
    """读取 Python/torch/torchvision/onnx/onnxruntime 版本与 CPU 线程数。"""
    try:
        import numpy
        import onnx
        import onnxruntime
        import torch
        import torchvision
    except ImportError as error:  # pragma: no cover - 依赖由 requirements 提供
        raise ProbeError(
            "DEPENDENCY_MISSING",
            f"探测依赖缺失（torch/torchvision/onnx/onnxruntime/numpy）：{error}",
        ) from error
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "torch": torch.__version__,
        "torchvision": torchvision.__version__,
        "onnx": onnx.__version__,
        "onnxruntime": onnxruntime.__version__,
        "numpy": numpy.__version__,
        "torch_num_threads": torch.get_num_threads(),
    }


def _build_model(name: str) -> Any:
    """按名称构建 torchvision 检测模型；不下载权重（离线可运行）。"""
    import torchvision

    if name == "ssdlite":
        return torchvision.models.detection.ssdlite320_mobilenet_v3_large(
            weights=None, weights_backbone=None, num_classes=NUM_CLASSES
        )
    if name == "fasterrcnn":
        return torchvision.models.detection.fasterrcnn_mobilenet_v3_large_320_fpn(
            weights=None, weights_backbone=None, num_classes=NUM_CLASSES
        )
    raise ProbeError("MODEL_UNKNOWN", f"未知模型：{name}")


def _summarize_output(meta: Any, values: Any) -> dict[str, Any]:
    """把 onnxruntime 输出数组压缩成可写 JSON 的形状/范围摘要。"""
    import numpy

    item: dict[str, Any] = {
        "name": meta.name,
        "shape": [int(size) for size in values.shape],
        "dtype": str(values.dtype),
        "onnx_type": str(meta.type),
    }
    if values.size and values.dtype.kind in "fiu":
        minimum = values.min()
        maximum = values.max()
        if values.dtype.kind == "f":
            item["min"] = round(float(minimum), 4)
            item["max"] = round(float(maximum), 4)
        else:
            item["min"] = int(minimum)
            item["max"] = int(maximum)
    if meta.name == "boxes" and values.dtype.kind == "f" and values.size:
        item["within_unit_square"] = bool(
            numpy.all(values >= 0.0) and numpy.all(values <= 1.0)
        )
    return item


def _model_warnings(
    name: str,
    spec: dict[str, Any],
    analysis: dict[str, Any],
    ort_outputs: Sequence[dict[str, Any]],
) -> list[str]:
    """根据 ONNX 拓扑与 onnxruntime 输出生成风险提示（不构成能力结论）。"""
    warnings: list[str] = []
    nms = analysis["nms"]
    control_flow = analysis["control_flow"]
    if nms["detected"]:
        warnings.append(
            "ONNX 图检测到 NMS 相关算子/自定义 domain（"
            + json.dumps(
                {"operators": nms["operators"], "custom_domains": nms["custom_domains"]},
                ensure_ascii=False,
            )
            + "）：与草案“首版模型图不含 NMS”的建议不一致，后处理归属与转换风险需重新评估。"
        )
    else:
        warnings.append(
            "ONNX 图不含 NonMaxSuppression、也无自定义 domain：导出图未包含 NMS/最终筛选，"
            "NMS 必须在模型外执行；onnxruntime 输出是原始检测头，不是最终检测结果。"
        )
    if control_flow["detected"]:
        warnings.append(
            "ONNX 图包含控制流算子 "
            + "、".join(control_flow["operators"])
            + "：nncase/K230 等转换器是否支持未验证（P6 风险），本机未做任何转换或板端验证。"
        )
    extra_risks = [
        op
        for op in analysis["conversion_risk_operators"]
        if op not in control_flow["operators"]
    ]
    if extra_risks:
        warnings.append(
            "ONNX 图包含其它待核对算子："
            + "、".join(extra_risks)
            + "；转换器支持情况未验证。"
        )
    boxes = next((item for item in ort_outputs if item["name"] == "boxes"), None)
    side = spec["input_shape"][-1]
    if boxes is not None and "within_unit_square" in boxes:
        if boxes["within_unit_square"]:
            warnings.append(
                f"boxes 输出数值在 [0,1] 内（{boxes['min']}～{boxes['max']}），可能接近归一化坐标；"
                "仍须在清单中显式声明坐标空间，不能直接当作原图像素。"
            )
        else:
            warnings.append(
                f"boxes 输出数值范围 {boxes['min']}～{boxes['max']} 超出 [0,1]；"
                f"按输入 {side}×{side} 推断接近模型输入像素坐标（推断，随机初始化权重下不代表训练后效果）。"
                "写入清单时必须显式声明 coordinate_space，并在模型外映射/裁剪回原图；映射与反算本机未验证。"
            )
    if any(item["name"] == "boxes" and len(item["shape"]) == 2 for item in ort_outputs):
        warnings.append(
            "onnxruntime 的 boxes/scores/labels 为固定行数（候选上限）原始输出，"
            "未执行分数阈值、NMS 或最终筛选；最终检测数需由模型外后处理决定。"
        )
    labels = next((item for item in ort_outputs if item["name"] == "labels"), None)
    if labels is not None and isinstance(labels.get("min"), int) and labels["min"] >= 1:
        warnings.append(
            f"labels 输出范围 {labels['min']}～{labels['max']}：torchvision 检测模型把 "
            f"num_classes 的 0 类当作背景、输出标签从 1 开始，本工具未建立 labels.json 映射；"
            "背景/忽略类不得混入标签表（草案规则），类别映射与 labels.json 长度需在 P2/P4 另行核对。"
        )
    if name == "fasterrcnn":
        warnings.append(
            "fasterrcnn 导出图与后处理可能含 NMS/RoiAlign 等算子，转换风险高于 ssdlite；"
            "本次未执行转换，不能据此判断可转换性。"
        )
    return warnings


def probe_model(name: str, opset: int) -> dict[str, Any]:
    """探测单个模型：实例化、前向、导出 ONNX、拓扑分析、onnxruntime 前向。"""
    import onnxruntime
    import torch

    spec = MODEL_SPECS[name]
    stage = "import"
    started = time.perf_counter()
    result: dict[str, Any] = {
        "ok": False,
        "name": name,
        "model": spec["factory"],
        "display_name": spec["display"],
        "num_classes": NUM_CLASSES,
        "weights": "none (random init)",
        "weights_backbone": "none (random init)",
        "device": "cpu",
        "seed": SEED,
        "input_shape": list(spec["input_shape"]),
        "warnings": [],
    }
    timings: dict[str, Any] = {}
    result["timings"] = timings
    tmp_dir: Path | None = None
    try:
        stage = "instantiate"
        torch.manual_seed(SEED)
        target = torch.device("cpu")
        instantiate_start = time.perf_counter()
        with warnings_module.catch_warnings(record=True) as caught:
            warnings_module.simplefilter("always")
            model = _build_model(name).to(target).eval()
        timings["instantiate_seconds"] = _round_seconds(
            time.perf_counter() - instantiate_start
        )
        result["parameters"] = {
            "total": sum(parameter.numel() for parameter in model.parameters()),
            "trainable": sum(
                parameter.numel()
                for parameter in model.parameters()
                if parameter.requires_grad
            ),
        }
        python_warnings = [
            str(item.message) for item in caught[:MAX_CAPTURED_WARNINGS]
        ]

        stage = "forward"
        dummy = torch.randn(*spec["input_shape"], device=target)
        with torch.inference_mode():
            for _ in range(FORWARD_WARMUP_RUNS):
                model(dummy)
            forward_samples: list[float] = []
            for _ in range(FORWARD_TIMED_RUNS):
                forward_start = time.perf_counter()
                model(dummy)
                forward_samples.append(time.perf_counter() - forward_start)
        timings["forward_seconds"] = _timing_stats(
            forward_samples, FORWARD_WARMUP_RUNS
        )

        # 按模型实际返回的字典键顺序声明 ONNX 输出名，避免不同模型
        # （SSDLite: boxes/scores/labels；FasterRCNN: boxes/labels/scores）错位。
        with torch.inference_mode():
            reference = model(dummy)
        output_names = infer_output_names(reference)
        result["output_names"] = output_names

        stage = "export"
        tmp_dir = Path(
            tempfile.mkdtemp(prefix="laitp-detection-draft-probe-")
        )
        onnx_path = tmp_dir / f"{name}.onnx"
        with warnings_module.catch_warnings(record=True) as export_caught:
            warnings_module.simplefilter("always")
            export_start = time.perf_counter()
            torch.onnx.export(
                model,
                (dummy,),
                str(onnx_path),
                input_names=["images"],
                output_names=output_names,
                opset_version=opset,
                do_constant_folding=True,
                dynamo=False,
                training=torch.onnx.TrainingMode.EVAL,
                verbose=False,
            )
            timings["export_seconds"] = _round_seconds(
                time.perf_counter() - export_start
            )
        python_warnings.extend(
            str(item.message) for item in export_caught[:MAX_CAPTURED_WARNINGS]
        )
        result["python_warnings"] = python_warnings[:MAX_CAPTURED_WARNINGS]

        stage = "analyze"
        analysis = analyze_onnx(onnx_path)
        size_bytes = onnx_path.stat().st_size
        result["onnx"] = {
            "size_bytes": size_bytes,
            "size_mb": round(size_bytes / 1_000_000, 2),
            "size_mib": round(size_bytes / (1024 * 1024), 2),
            "sha256": _sha256_file(onnx_path),
            **analysis,
        }

        stage = "onnxruntime"
        ort_target = str(onnx_path)
        load_start = time.perf_counter()
        session = onnxruntime.InferenceSession(
            ort_target, providers=["CPUExecutionProvider"]
        )
        timings["onnxruntime_load_seconds"] = _round_seconds(
            time.perf_counter() - load_start
        )
        input_meta = session.get_inputs()
        feed = {input_meta[0].name: dummy.detach().cpu().numpy()}
        try:
            for _ in range(ORT_WARMUP_RUNS):
                session.run(None, feed)
            ort_samples: list[float] = []
            ort_arrays: list[Any] = []
            for _ in range(ORT_TIMED_RUNS):
                ort_start = time.perf_counter()
                ort_arrays = session.run(None, feed)
                ort_samples.append(time.perf_counter() - ort_start)
            timings["onnxruntime_forward_seconds"] = _timing_stats(
                ort_samples, ORT_WARMUP_RUNS
            )
            ort_outputs = [
                _summarize_output(meta, values)
                for meta, values in zip(session.get_outputs(), ort_arrays)
            ]
            result["onnxruntime"] = {
                "version": onnxruntime.__version__,
                "providers": list(session.get_providers()),
                "input_names": [item.name for item in input_meta],
                "outputs": ort_outputs,
            }
        finally:
            del session
            gc.collect()

        stage = "report"
        result["warnings"].extend(
            _model_warnings(name, spec, analysis, ort_outputs)
        )
        result["ok"] = True
        timings["total_seconds"] = _round_seconds(time.perf_counter() - started)
    except Exception as error:  # 单模型失败不抛出：保留已收集证据并标记失败阶段
        result["ok"] = False
        result["stage"] = stage
        result["error"] = f"探测失败（{type(error).__name__}）：{error}"
        timings["total_seconds"] = _round_seconds(time.perf_counter() - started)
        result["warnings"].append(
            f"模型 {name} 在阶段 {stage} 失败，结果不完整；不能据此判断可转换性。"
        )
    finally:
        if tmp_dir is not None:
            gc.collect()
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)
        result["temp_onnx_deleted"] = tmp_dir is None or not tmp_dir.exists()
        if not result["temp_onnx_deleted"]:  # pragma: no cover - Windows 文件占用兜底
            result["warnings"].append(
                "临时 ONNX 未能删除（可能被进程占用），请手工清理临时目录中的 laitp-detection-draft-probe-*。"
            )
    return result


# --------------------------------------------------------------------------- #
# 参数解析与 JSON 组装
# --------------------------------------------------------------------------- #


def resolve_output(raw: str | None) -> Path:
    """解析输出 JSON 路径：默认仓库 artifacts/ 下，显式相对路径按当前目录解析。"""
    if raw is None:
        return DEFAULT_OUTPUT
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def resolve_models(model: str | None, skip_fasterrcnn: bool) -> list[str]:
    """把 --model/--skip-fasterrcnn 解析为实际要探测的模型列表。"""
    models = ["ssdlite", "fasterrcnn"] if model is None else [model]
    if skip_fasterrcnn:
        models = [name for name in models if name != "fasterrcnn"]
    if not models:
        raise ProbeError(
            "MODEL_SELECTION_EMPTY",
            "--skip-fasterrcnn 与 --model fasterrcnn 同时使用会跳过全部模型；请改用 --model ssdlite。",
        )
    return models


def build_payload(
    results: dict[str, dict[str, Any]],
    models: Sequence[str],
    opset: int,
    output_path: Path,
    environment: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """组装输出 JSON（纯函数；draft/activated/notes 字段始终存在）。"""
    model_errors = [
        f"{name}: {item.get('error') or 'unknown'}"
        for name, item in results.items()
        if not item.get("ok")
    ]
    combined_error = error
    if combined_error is None and model_errors:
        combined_error = "模型探测失败：" + "；".join(model_errors)
    if combined_error is None and not results:
        combined_error = "没有执行任何模型探测"
    warnings: list[str] = []
    if "fasterrcnn" not in models:
        warnings.append(
            "本次未探测 fasterrcnn：其 CPU 实例化/前向/ONNX 导出可行性仍未验证，不能由 ssdlite 结果外推。"
        )
    for name in models:
        item = results.get(name)
        if item is None:
            continue
        for warning in item.get("warnings", []):
            warnings.append(f"[{name}] {warning}")
    warnings.append(
        "结果为本机单次探测（未训练、未生成产物包、未执行转换/量化），不代表目标机性能、"
        "课堂效果或 K230/K210 板端能力；精度与训练耗时仍是 P3 未完成项。"
    )
    return {
        "ok": combined_error is None and bool(results),
        "tool": TOOL_NAME,
        "draft": True,
        "activated": False,
        "notes": list(DRAFT_NOTES),
        "generated_at": _now_text(),
        "environment": environment or {},
        "options": {
            "models": list(models),
            "opset": opset,
            "num_classes": NUM_CLASSES,
            "seed": SEED,
            "forward_runs": FORWARD_TIMED_RUNS,
            "output": _display_path(output_path),
        },
        "results": results,
        "warnings": warnings,
        "error": combined_error,
    }


def run_probe(
    models: Sequence[str],
    opset: int,
    output_path: Path,
) -> dict[str, Any]:
    """执行探测、写 JSON 文件并返回 payload；工具级失败抛 ProbeError。"""
    environment = collect_environment()
    results: dict[str, dict[str, Any]] = {}
    for name in models:
        try:
            results[name] = probe_model(name, opset)
        except ProbeError as error:  # pragma: no cover - 未知模型已在参数层拦截
            results[name] = {
                "ok": False,
                "name": name,
                "error": error.message,
                "code": error.code,
                "warnings": [],
            }
        except Exception as error:  # pragma: no cover - 防御未捕获异常
            results[name] = {
                "ok": False,
                "name": name,
                "error": f"{type(error).__name__}: {error}",
                "warnings": [],
            }
    payload = build_payload(results, models, opset, output_path, environment)
    _write_json_atomic(output_path, payload)
    return payload


def _failure_payload(
    code: str, message: str, output_path: Path | None, options: dict[str, Any]
) -> dict[str, Any]:
    """工具级失败 JSON：保留 draft/activated/notes 字段，不伪造任何探测结果。"""
    return {
        "ok": False,
        "tool": TOOL_NAME,
        "draft": True,
        "activated": False,
        "notes": list(DRAFT_NOTES),
        "generated_at": _now_text(),
        "environment": {},
        "options": dict(
            options,
            output=_display_path(output_path) if output_path is not None else None,
        ),
        "results": {},
        "warnings": [
            "探测未完成：以下 error 只表示工具/环境失败，不构成检测能力或板端结论。"
        ],
        "code": code,
        "error": message,
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python scripts/detection_draft_probe.py",
        description=(
            "检测可行性探测工具（草案，未激活，不接入生产）：对 torchvision 内置检测模型做"
            " CPU 实例化、随机输入前向、ONNX 导出、算子/NMS/控制流统计与 onnxruntime 输出"
            "形状探测；不训练、不发布、不接入校验/界面/课程。检测未实现，结果只是本机单次"
            "可行性证据，不代表板端可运行。"
        ),
    )
    parser.add_argument(
        "--output",
        default=None,
        help=(
            f"输出 JSON 路径；默认 {DEFAULT_OUTPUT.as_posix()}（相对仓库根目录，artifacts/ 不提交）"
        ),
    )
    parser.add_argument(
        "--model",
        choices=MODEL_CHOICES,
        default=None,
        help=(
            "只探测指定模型；省略时探测 ssdlite+fasterrcnn 两个模型"
            "（可用 --skip-fasterrcnn 跳过较慢的 fasterrcnn）"
        ),
    )
    parser.add_argument(
        "--opset",
        type=int,
        default=DEFAULT_OPSET,
        metavar="N",
        help=f"ONNX opset 版本（默认 {DEFAULT_OPSET}）",
    )
    parser.add_argument(
        "--skip-fasterrcnn",
        action="store_true",
        help="默认 all 时跳过较慢的 fasterrcnn（ssdlite 仍会探测）",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    output_path: Path | None = None
    options = {
        "models": None,
        "model": args.model,
        "opset": args.opset,
        "skip_fasterrcnn": args.skip_fasterrcnn,
        "output": args.output,
    }
    try:
        output_path = resolve_output(args.output)
        models = resolve_models(args.model, args.skip_fasterrcnn)
        options["models"] = models
        payload = run_probe(models, args.opset, output_path)
    except ProbeError as error:
        payload = _failure_payload(error.code, error.message, output_path, options)
        _try_write_failure(payload, output_path)
        _emit_json(payload)
        return 1
    except Exception as error:  # 不把异常堆栈当正常输出；保持稳定 JSON + 退出码 1
        payload = _failure_payload(
            "DETECTION_DRAFT_PROBE_FAILED",
            f"探测过程异常（{type(error).__name__}）：{error}",
            output_path,
            options,
        )
        _try_write_failure(payload, output_path)
        _emit_json(payload)
        return 1

    _emit_json(payload)
    return 0 if payload["ok"] else 1


def _try_write_failure(payload: dict[str, Any], output_path: Path | None) -> None:
    """失败时也尽力写出 JSON（写不出不影响退出码与标准输出）。"""
    if output_path is None:
        return
    try:
        _write_json_atomic(output_path, payload)
    except OSError:  # pragma: no cover - 输出路径不可写时只保留标准输出
        pass


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
