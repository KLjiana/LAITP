from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import onnx
from onnx import helper, TensorProto

ROOT = Path(__file__).resolve().parents[1]


def load_probe():
    spec = importlib.util.spec_from_file_location("k230_model_probe", ROOT / "scripts/k230_model_probe.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def build_static_model(path: Path) -> None:
    weight = helper.make_tensor("w", TensorProto.FLOAT, [1, 1, 1, 1], [1.0])
    conv = helper.make_node("Conv", ["input", "w"], ["conv"], kernel_shape=[1, 1])
    relu = helper.make_node("Relu", ["conv"], ["output"])
    graph = helper.make_graph(
        [conv, relu],
        "probe_static",
        [helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, 224, 224])],
        [helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 1, 224, 224])],
        [weight],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    onnx.save(model, str(path))


def test_probe_static_model_reports_ops_and_shapes(tmp_path: Path) -> None:
    probe = load_probe()
    onnx_path = tmp_path / "model.onnx"
    build_static_model(onnx_path)

    report = probe.probe_onnx(onnx_path)

    assert report["op_counts"] == {"Conv": 1, "Relu": 1}
    assert report["inputs"][0]["shape"] == [1, 3, 224, 224]
    assert report["inputs"][0]["dynamic"] is False
    assert report["parameter_count"] == 1
    assert report["warnings"] == []


def test_probe_dynamic_input_adds_warning(tmp_path: Path) -> None:
    probe = load_probe()
    node = helper.make_node("Relu", ["input"], ["output"])
    graph = helper.make_graph(
        [node],
        "probe_dynamic",
        [helper.make_tensor_value_info("input", TensorProto.FLOAT, ["batch", 3, 224, 224])],
        [helper.make_tensor_value_info("output", TensorProto.FLOAT, ["batch", 3, 224, 224])],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    onnx_path = tmp_path / "dynamic.onnx"
    onnx.save(model, str(onnx_path))

    report = probe.probe_onnx(onnx_path)

    assert report["inputs"][0]["dynamic"] is True
    assert any("动态维度" in warning for warning in report["warnings"])


def test_resolve_onnx_from_model_package(tmp_path: Path) -> None:
    probe = load_probe()
    model_dir = tmp_path / "model-package"
    model_dir.mkdir()
    build_static_model(model_dir / "model.onnx")
    (model_dir / "manifest.json").write_text(
        json.dumps({"files": [{"path": "model.onnx", "role": "model", "sha256": "x"}]}),
        encoding="utf-8",
    )

    assert probe.resolve_onnx(model_dir) == (model_dir / "model.onnx").resolve()

def test_display_path_uses_relative_for_repo_files(tmp_path: Path) -> None:
    probe = load_probe()

    assert probe.display_path(ROOT / "scripts" / "k230_model_probe.py") == "scripts/k230_model_probe.py"
    outside = tmp_path / "model.onnx"
    assert probe.display_path(outside) == str(outside.resolve())
