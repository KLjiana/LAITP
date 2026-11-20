"""测试用产物包构造器。

真实产物包的摘要必须与文件内容一致，因此测试包在 ``tmp_path`` 中生成，
而不是把摘要写死在仓库里。生成的最小 ONNX 模型只用于校验张量签名，
不代表真实分类效果。
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Sequence

from onnx import TensorProto, checker, helper, save

from backend.contracts.runtime_spec import RuntimeProfile

TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
DEFAULT_LABELS: tuple[str, ...] = ("水杯", "书本", "笔袋")
DATASET_DIGEST = hashlib.sha256(b"laitp-test-dataset-v1").hexdigest()
PLACEHOLDER_DIGEST = "0" * 64


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def make_onnx_model(
    path: Path,
    *,
    opset: int = 17,
    input_shape: Sequence[int] = (1, 3, 224, 224),
    output_shape: Sequence[int] = (1, 3),
) -> Path:
    """生成只含 ReduceMean 的最小分类模型，输出形状与类别数对应。"""
    input_info = helper.make_tensor_value_info(
        "images", TensorProto.FLOAT, list(input_shape)
    )
    output_info = helper.make_tensor_value_info(
        "logits", TensorProto.FLOAT, list(output_shape)
    )
    node = helper.make_node(
        "ReduceMean", inputs=["images"], outputs=["logits"], axes=[2, 3], keepdims=0
    )
    graph = helper.make_graph([node], "laitp-test-classifier", [input_info], [output_info])
    model = helper.make_model(
        graph,
        producer_name="laitp-tests",
        opset_imports=[helper.make_opsetid("", opset)],
    )
    checker.check_model(model)
    save(model, str(path))
    return path


def default_manifest(labels: Sequence[str] = DEFAULT_LABELS) -> dict[str, Any]:
    """返回一个结构完整的分类产物清单，摘要留待 ``refresh_digests`` 填写。"""
    return {
        "contract_version": "1.0",
        "artifact_id": "art-20261117-0001",
        "task": "image_classification",
        "provenance": {
            "project_id": "proj-classification-demo",
            "run_id": "run-20261117-0001",
            "dataset_manifest_sha256": DATASET_DIGEST,
            "created_at": "2026-11-17T09:30:00+08:00",
        },
        "files": [
            {"path": "model.onnx", "role": "model", "sha256": "", "size_bytes": 0},
            {"path": "labels.json", "role": "labels", "sha256": "", "size_bytes": 0},
            {
                "path": "validation/sample.png",
                "role": "validation_sample",
                "sha256": "",
                "size_bytes": 0,
            },
            {
                "path": "validation/expected.json",
                "role": "reference_output",
                "sha256": "",
                "size_bytes": 0,
            },
        ],
        "model": {
            "path": "model.onnx",
            "format": "onnx",
            "opset": 17,
            "external_data": [],
        },
        "inputs": [
            {
                "name": "images",
                "shape": [1, 3, 224, 224],
                "dtype": "float32",
                "layout": "NCHW",
                "color_space": "RGB",
            }
        ],
        "outputs": [
            {
                "name": "logits",
                "shape": [1, len(labels)],
                "dtype": "float32",
                "meaning": "class_logits",
                "class_axis": 1,
            }
        ],
        "preprocessing": {
            "executor": "host",
            "source_pixel_range": [0, 255],
            "steps": [
                {
                    "op": "resize",
                    "width": 224,
                    "height": 224,
                    "mode": "stretch",
                    "interpolation": "bilinear",
                },
                {
                    "op": "normalize",
                    "formula": "(pixel * scale - mean) / std",
                    "scale": 1.0 / 255.0,
                    "mean": [0.485, 0.456, 0.406],
                    "std": [0.229, 0.224, 0.225],
                    "channel_order": "RGB",
                },
                {"op": "transpose", "from": "HWC", "to": "CHW"},
                {"op": "add_batch_dimension", "axis": 0},
            ],
        },
        "postprocessing": {
            "executor": "host",
            "steps": [{"op": "softmax", "axis": 1}],
        },
        "labels": {"path": "labels.json", "count": len(labels)},
        "runtime": {
            "runtime": "onnxruntime",
            "version_range": ">=1.18.0,<2.0.0",
            "platform": "windows-x64",
            "device": "cpu",
            "required_capabilities": ["onnxruntime-cpu"],
        },
        "validation": {
            "samples": [
                {
                    "name": "sample-1",
                    "path": "validation/sample.png",
                    "reference_output": "validation/expected.json",
                }
            ]
        },
    }


def refresh_digests(manifest: dict[str, Any], root: Path) -> None:
    """按磁盘文件回填 ``files`` 中的摘要与大小；文件缺失时保留原值。"""
    for entry in manifest["files"]:
        target = Path(root) / entry["path"]
        if not target.is_file():
            continue
        data = target.read_bytes()
        entry["sha256"] = sha256_bytes(data)
        entry["size_bytes"] = len(data)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def write_package_files(root: Path, *, labels: Sequence[str] = DEFAULT_LABELS) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "validation").mkdir(exist_ok=True)
    make_onnx_model(root / "model.onnx", output_shape=(1, len(labels)))
    write_json(root / "labels.json", list(labels))
    (root / "validation" / "sample.png").write_bytes(TINY_PNG)
    write_json(
        root / "validation" / "expected.json",
        {
            "artifact_id": "art-20261117-0001",
            "prediction": {"class_id": 0, "label": labels[0], "probability": 0.91},
            "raw_output": [[0.12, 0.03, -0.07]],
        },
    )


def build_package(
    root: Path,
    *,
    labels: Sequence[str] = DEFAULT_LABELS,
    patch: Callable[[dict[str, Any]], None] | None = None,
) -> Path:
    """在 ``root`` 生成一个自洽的产物包，返回包目录。"""
    root = Path(root)
    write_package_files(root, labels=labels)
    manifest = default_manifest(labels)
    if patch is not None:
        patch(manifest)
    refresh_digests(manifest, root)
    write_json(root / "manifest.json", manifest)
    return root


def reopen_manifest(root: Path) -> dict[str, Any]:
    return json.loads((Path(root) / "manifest.json").read_text(encoding="utf-8"))


def save_manifest(root: Path, manifest: dict[str, Any], *, refresh: bool = False) -> None:
    if refresh:
        refresh_digests(manifest, Path(root))
    write_json(Path(root) / "manifest.json", manifest)


def copy_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(manifest)


def runtime_profile(
    *,
    platform: str = "windows-x64",
    version: str = "1.19.2",
    capabilities: Sequence[str] = ("onnxruntime-cpu",),
    runtime: str = "onnxruntime",
) -> RuntimeProfile:
    return RuntimeProfile(
        runtime=runtime,
        version=version,
        platform=platform,
        capabilities=frozenset(capabilities),
    )
