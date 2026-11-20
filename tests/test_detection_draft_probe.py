"""检测可行性探测工具的测试（草案，未激活）。

这些测试只验证 ``scripts/detection_draft_probe.py`` 的**纯逻辑与 CLI 元数据**：
小 ONNX 模型的拓扑统计（节点数/算子集合/NMS 与控制流判定）、输出 JSON 的
draft/activated/notes 字段与失败路径、``--help`` 与参数解析。测试**不加载
torchvision 检测模型、不做 ONNX 导出、不跑 onnxruntime 前向**，因此是秒级、
离线可复现的；重活由 ``monkeypatch`` 替换。

本工具与这些测试通过**不表示**检测标注、训练、导出产物、电脑测试、转换/量化
或板端能力已经实现、可用或验证通过；探测结果只是本机单次可行性证据。
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import onnx
import pytest
from onnx import TensorProto, helper

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "detection_draft_probe.py"
DEFAULT_OUTPUT = ROOT / "artifacts" / "detection-draft" / "probe.json"


def load_probe_module() -> Any:
    """按文件路径加载工具模块（与 tests/test_detection_draft_check.py 的做法一致）。"""
    name = "detection_draft_probe"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


def _value_info(name: str, shape: list[int] | None = None, dtype: int = TensorProto.FLOAT) -> Any:
    return helper.make_tensor_value_info(name, dtype, shape)


def _save_model(
    path: Path,
    nodes: list[Any],
    inputs: list[Any],
    outputs: list[Any],
    opsets: list[Any] | None = None,
) -> Path:
    graph = helper.make_graph(nodes, "probe-test", inputs, outputs)
    model = helper.make_model(
        graph, opset_imports=opsets or [helper.make_opsetid("", 17)]
    )
    onnx.save(model, str(path))
    return path


# --------------------------------------------------------------------------- #
# 1. 纯函数 analyze_onnx：节点数、算子集合、NMS 与控制流检测
# --------------------------------------------------------------------------- #


def test_analyze_onnx_detects_nodes_operators_nms_and_control_flow(
    tmp_path: Path,
) -> None:
    module = load_probe_module()

    # 普通算子 + If 控制流：不涉及 NMS / 自定义 domain。
    control_flow_model = _save_model(
        tmp_path / "control-flow.onnx",
        [
            helper.make_node("Add", ["x", "y"], ["z"]),
            helper.make_node("Relu", ["z"], ["w"]),
            helper.make_node("If", ["cond"], ["out"]),
        ],
        [
            _value_info("x", [1]),
            _value_info("y", [1]),
            _value_info("cond", [1], TensorProto.BOOL),
        ],
        [_value_info("w", [1]), _value_info("out", [1])],
    )
    analysis = module.analyze_onnx(control_flow_model)
    assert analysis["node_count"] == 3
    assert analysis["op_types"] == ["Add", "If", "Relu"]
    assert analysis["op_type_count"] == 3
    assert analysis["custom_domains"] == []
    assert analysis["nms"]["detected"] is False
    assert analysis["nms"]["non_max_suppression"] is False
    assert analysis["nms"]["operators"] == []
    assert analysis["control_flow"] == {
        "detected": True,
        "operators": ["If"],
        "if": True,
        "loop": False,
        "scan": False,
    }

    # 标准 NonMaxSuppression 节点必须被识别为 NMS。
    nms_model = _save_model(
        tmp_path / "nms.onnx",
        [
            helper.make_node(
                "NonMaxSuppression", ["boxes", "scores", "max_out"], ["keep"]
            )
        ],
        [
            _value_info("boxes", [1, 16, 4]),
            _value_info("scores", [1, 3, 16]),
            _value_info("max_out", [], TensorProto.INT64),
        ],
        [_value_info("keep", [None, 3], TensorProto.INT64)],
    )
    nms_analysis = module.analyze_onnx(nms_model)
    assert nms_analysis["node_count"] == 1
    assert nms_analysis["op_types"] == ["NonMaxSuppression"]
    assert nms_analysis["nms"]["detected"] is True
    assert nms_analysis["nms"]["non_max_suppression"] is True
    assert nms_analysis["nms"]["operators"] == [
        {"domain": "", "op_type": "NonMaxSuppression"}
    ]
    assert nms_analysis["control_flow"]["detected"] is False

    # 自定义算子 domain（torchvision::nms 一类）也必须触发 NMS 相关判定。
    custom_model = _save_model(
        tmp_path / "custom-nms.onnx",
        [helper.make_node("nms", ["boxes", "scores"], ["keep"], domain="torchvision")],
        [_value_info("boxes", [16, 4]), _value_info("scores", [16])],
        [_value_info("keep", [None], TensorProto.INT64)],
        opsets=[
            helper.make_opsetid("", 17),
            helper.make_opsetid("torchvision", 1),
        ],
    )
    custom_analysis = module.analyze_onnx(custom_model)
    assert custom_analysis["custom_domains"] == ["torchvision"]
    assert custom_analysis["nms"]["detected"] is True
    assert custom_analysis["nms"]["non_max_suppression"] is False
    assert custom_analysis["nms"]["operators"] == [
        {"domain": "torchvision", "op_type": "nms"}
    ]


# --------------------------------------------------------------------------- #
# 2. JSON 输出的 draft/activated/notes 字段、警告聚合与失败路径
# --------------------------------------------------------------------------- #


def test_payload_declares_draft_inactive_and_handles_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_probe_module()
    calls: dict[str, int] = {}

    def fake_environment() -> dict[str, Any]:
        return {"python": "3.12.1", "torch": "fake", "torchvision": "fake"}

    def fake_probe(name: str, opset: int) -> dict[str, Any]:
        calls[name] = opset
        return {
            "ok": True,
            "name": name,
            "model": f"fake-{name}",
            "input_shape": [1, 3, 320, 320],
            "parameters": {"total": 1, "trainable": 1},
            "timings": {},
            "onnx": {
                "node_count": 1,
                "op_types": ["Add"],
                "nms": {"detected": False},
                "control_flow": {"detected": False},
            },
            "onnxruntime": {"outputs": []},
            "warnings": ["示例模型警告"],
        }

    monkeypatch.setattr(module, "collect_environment", fake_environment)
    monkeypatch.setattr(module, "probe_model", fake_probe)

    output = tmp_path / "probe.json"
    exit_code = module.main(
        ["--output", str(output), "--model", "ssdlite", "--skip-fasterrcnn"]
    )
    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["draft"] is True
    assert payload["activated"] is False
    assert payload["error"] is None
    assert payload["tool"] == "detection_draft_probe"
    assert calls == {"ssdlite": 17}
    assert payload["results"]["ssdlite"]["ok"] is True

    notes = "\n".join(payload["notes"])
    for phrase in ("草案", "未激活", "检测未实现", "可行性探测", "不训练", "不接入"):
        assert phrase in notes, f"JSON notes 必须提示 {phrase!r}"

    # 未探测的 fasterrcnn 与模型自身警告都必须汇总到顶层 warnings。
    warnings_text = "\n".join(payload["warnings"])
    assert "fasterrcnn" in warnings_text
    assert "示例模型警告" in warnings_text
    assert "本机单次探测" in warnings_text

    # 工具级失败：ok:false + error + code + 退出码 1，且仍写出 JSON。
    def broken_environment() -> dict[str, Any]:
        raise module.ProbeError("DEPENDENCY_MISSING", "缺少探测依赖（测试注入）")

    monkeypatch.setattr(module, "collect_environment", broken_environment)
    failed_output = tmp_path / "probe-failed.json"
    failed_code = module.main(["--output", str(failed_output), "--model", "ssdlite"])
    assert failed_code == 1
    failed = json.loads(failed_output.read_text(encoding="utf-8"))
    assert failed["ok"] is False
    assert failed["draft"] is True
    assert failed["activated"] is False
    assert failed["code"] == "DEPENDENCY_MISSING"
    assert "缺少探测依赖" in failed["error"]
    assert failed["results"] == {}


# --------------------------------------------------------------------------- #
# 3. --help 与参数解析（不加载模型、不导出 ONNX）
# --------------------------------------------------------------------------- #


def test_help_and_argument_parsing_are_draft_marked(tmp_path: Path) -> None:
    module = load_probe_module()

    # 默认值：探测 ssdlite+fasterrcnn、opset 17、不跳过 fasterrcnn、输出到仓库 artifacts/ 固定路径。
    defaults = module._build_parser().parse_args([])
    assert defaults.model is None
    assert defaults.opset == 17
    assert defaults.skip_fasterrcnn is False
    assert defaults.output is None
    assert module.DEFAULT_OUTPUT == DEFAULT_OUTPUT
    assert set(module.MODEL_CHOICES) == {"ssdlite", "fasterrcnn"}

    parsed = module._build_parser().parse_args(
        ["--model", "ssdlite", "--opset", "18", "--skip-fasterrcnn"]
    )
    assert parsed.model == "ssdlite"
    assert parsed.opset == 18
    assert parsed.skip_fasterrcnn is True

    # 模型选择为空属于参数错误：不得开始任何重活，仍返回 draft JSON 与退出码 1。
    conflict_output = tmp_path / "selection-empty.json"
    conflict_code = module.main(
        [
            "--output",
            str(conflict_output),
            "--model",
            "fasterrcnn",
            "--skip-fasterrcnn",
        ]
    )
    assert conflict_code == 1
    conflict = json.loads(conflict_output.read_text(encoding="utf-8"))
    assert conflict["ok"] is False
    assert conflict["code"] == "MODEL_SELECTION_EMPTY"

    # 子进程 --help 必须快速返回且标注草案/未激活，并列出全部 CLI 选项。
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=ROOT,
        capture_output=True,
        env=env,
        timeout=60,
    )
    help_text = completed.stdout.decode("utf-8", "replace")
    assert completed.returncode == 0, help_text
    for phrase in (
        "草案",
        "未激活",
        "检测未实现",
        "--output",
        "--model",
        "--opset",
        "--skip-fasterrcnn",
    ):
        assert phrase in help_text, f"--help 必须包含 {phrase!r}"

    docstring = module.__doc__ or ""
    for phrase in ("草案", "未激活", "检测未实现", "不训练", "不发布"):
        assert phrase in docstring, f"模块 docstring 必须提示 {phrase!r}"

# --------------------------------------------------------------------------- #
# 4. 输出名推断：按模型返回字典键顺序，避免 SSDLite/FasterRCNN 错位
# --------------------------------------------------------------------------- #


def test_infer_output_names_follows_model_dictionary_order() -> None:
    module = load_probe_module()

    assert module.infer_output_names([{"boxes": 1, "scores": 2, "labels": 3}]) == [
        "boxes",
        "scores",
        "labels",
    ]
    assert module.infer_output_names([{"boxes": 1, "labels": 2, "scores": 3}]) == [
        "boxes",
        "labels",
        "scores",
    ]
    # 非字典输出时回退到 torchvision 检测模型的默认顺序。
    assert module.infer_output_names(None) == ["boxes", "scores", "labels"]
    assert module.infer_output_names([]) == ["boxes", "scores", "labels"]
