from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import onnx
from onnx import TensorProto, helper

ROOT = Path(__file__).resolve().parents[1]


def load_readiness():
    spec = importlib.util.spec_from_file_location(
        "k230_readiness", ROOT / "scripts/k230_readiness.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def write_static_model(model_dir: Path) -> None:
    model_dir.mkdir(parents=True, exist_ok=True)
    node = helper.make_node("Relu", ["input"], ["output"])
    graph = helper.make_graph(
        [node],
        "readiness_model",
        [helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, 224, 224])],
        [helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 3, 224, 224])],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    onnx.save(model, str(model_dir / "model.onnx"))
    (model_dir / "manifest.json").write_text(
        json.dumps({"files": [{"path": "model.onnx", "role": "model", "sha256": "x"}]}),
        encoding="utf-8",
    )


def test_readiness_blocks_without_toolchain_and_nncase(tmp_path: Path) -> None:
    readiness = load_readiness()
    model_dir = tmp_path / "model-package"
    write_static_model(model_dir)

    report = readiness.build_report(model_dir, tmp_path / "toolchain.json", None)

    assert report["overall"] == "blocked"
    ids = {item["id"]: item["status"] for item in report["checks"]}
    assert ids["toolchain-pinned"] == "blocked"
    assert ids["nncase-installed"] == "blocked"
    assert ids["calibration-data"] == "blocked"
    assert ids["model-static-input"] == "pass"


def test_readiness_passes_pinned_toolchain_config(tmp_path: Path) -> None:
    readiness = load_readiness()
    config = tmp_path / "k230-toolchain.json"
    config.write_text(
        json.dumps(
            {
                "nncase_version": "2.x-fixed",
                "sdk_version": "fixed-sdk",
                "board_model": "K230-fixed",
            }
        ),
        encoding="utf-8",
    )

    result = readiness.check_toolchain(config)

    assert result["status"] == "pass"
    assert "K230-fixed" in result["detail"]


def test_readiness_counts_calibration_images(tmp_path: Path) -> None:
    readiness = load_readiness()
    calibration = tmp_path / "calibration"
    calibration.mkdir()
    for index in range(3):
        (calibration / f"sample-{index}.jpg").write_bytes(b"jpg")
    (calibration / "notes.txt").write_text("not an image", encoding="utf-8")

    result = readiness.check_calibration(calibration, minimum=3)

    assert result["status"] == "pass"
    assert "3 张" in result["detail"]
