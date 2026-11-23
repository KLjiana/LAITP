"""对分类模型包 / ONNX 做静态图探测，为 K230 转换前置分析提供事实数据。

这不是转换验证：不运行 nncase、不量化、不部署到板端。仅报告图结构、算子分布、
输入输出与动态形状等可离线核对的客观信息，供与指定 nncase/K230 SDK 版本的
算子表逐项核对。

用法：
    python scripts/k230_model_probe.py --model artifacts/.../model-package --output artifacts/k230-probe.json
    python scripts/k230_model_probe.py --onnx path/to/model.onnx --output artifacts/k230-probe.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 已知在导出图中需要人工核对语义/参数的算子（不代表 nncase 一定不支持）。
_ATTENTION_OPS = {
    "NonMaxSuppression",
    "GridSample",
    "RoiAlign",
    "Resize",
    "Upsample",
    "TopK",
    "ScatterND",
    "GatherND",
    "Einsum",
    "LSTM",
    "GRU",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def display_path(path: Path) -> str:
    """仓库内路径用相对形式输出，便于随仓库分发；仓库外保留绝对路径。"""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def _tensor_brief(value_info) -> dict:
    tensor = value_info.type.tensor_type
    shape = []
    dynamic = False
    for dim in tensor.shape.dim:
        if dim.HasField("dim_value"):
            shape.append(int(dim.dim_value))
        else:
            shape.append(dim.dim_param or "?")
            dynamic = True
    return {
        "name": value_info.name,
        "dtype": tensor.elem_type,
        "shape": shape,
        "dynamic": dynamic,
    }


def probe_onnx(onnx_path: Path) -> dict:
    import onnx  # 局部导入：仅在探测时需要

    model = onnx.load(str(onnx_path))
    graph = model.graph
    op_counts: dict[str, int] = {}
    for node in graph.node:
        op_counts[node.op_type] = op_counts.get(node.op_type, 0) + 1
    inputs = [_tensor_brief(item) for item in graph.input]
    outputs = [_tensor_brief(item) for item in graph.output]
    parameter_count = 0
    for initializer in graph.initializer:
        count = 1
        for dim in initializer.dims:
            count *= int(dim)
        parameter_count += count
    warnings: list[str] = []
    dynamic_inputs = [item["name"] for item in inputs if item["dynamic"]]
    if dynamic_inputs:
        warnings.append(
            "输入含动态维度：" + "、".join(dynamic_inputs) + "；板端转换前应固定为具体分辨率"
        )
    attention = sorted(op for op in op_counts if op in _ATTENTION_OPS)
    if attention:
        warnings.append(
            "含需人工核对语义/参数的算子：" + "、".join(attention) + "（需按 nncase 目标版本算子表逐项确认）"
        )
    return {
        "onnx": display_path(onnx_path),
        "sha256": sha256_file(onnx_path),
        "bytes": onnx_path.stat().st_size,
        "ir_version": int(model.ir_version),
        "opset_imports": [
            {"domain": item.domain or "ai.onnx", "version": int(item.version)}
            for item in model.opset_import
        ],
        "inputs": inputs,
        "outputs": outputs,
        "op_counts": dict(sorted(op_counts.items())),
        "node_count": len(graph.node),
        "initializer_count": len(graph.initializer),
        "parameter_count": parameter_count,
        "warnings": warnings,
    }


def read_manifest(model_dir: Path) -> dict:
    manifest_path = model_dir / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"找不到模型包清单：{manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def resolve_onnx(model_dir: Path) -> Path:
    """按模型契约 1.0 的 files 列表（role=model）定位 ONNX；兼容简单 onnx 字段。"""
    manifest = read_manifest(model_dir)
    onnx_name = None
    for entry in manifest.get("files") or []:
        if entry.get("role") == "model" and str(entry.get("path", "")).endswith(".onnx"):
            onnx_name = entry["path"]
            break
    if not onnx_name:
        onnx = manifest.get("onnx")
        onnx_name = (onnx or {}).get("path") if isinstance(onnx, dict) else None
    onnx_name = onnx_name or manifest.get("onnx_path")
    if not onnx_name:
        raise SystemExit("manifest 中缺少 onnx 路径（files[role=model]）")
    onnx_path = (model_dir / onnx_name).resolve()
    if not onnx_path.is_file():
        raise SystemExit(f"找不到 ONNX 文件：{onnx_path}")
    return onnx_path


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    parser = argparse.ArgumentParser(description="分类模型 ONNX 静态图探测（K230 前置分析，不做转换）")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--model", type=Path, help="模型包目录（含 manifest.json）")
    group.add_argument("--onnx", type=Path, help="直接指定 ONNX 文件")
    parser.add_argument("--output", type=Path, help="结果 JSON 输出路径")
    args = parser.parse_args()

    onnx_path = args.model.resolve() if args.onnx is None else args.onnx.resolve()
    if args.model is not None:
        onnx_path = resolve_onnx(onnx_path)
    if not onnx_path.is_file():
        raise SystemExit(f"找不到 ONNX 文件：{onnx_path}")

    probe = probe_onnx(onnx_path)
    manifest = read_manifest(args.model.resolve()) if args.model is not None else None
    if manifest is not None:
        expected = None
        for entry in manifest.get("files") or []:
            if str(entry.get("path", "")).endswith(".onnx"):
                expected = entry.get("sha256")
                break
        probe["manifest_sha256_expected"] = expected
        probe["manifest_sha256_match"] = expected == probe["sha256"] if expected else None
        probe["artifact_id"] = manifest.get("artifact_id")
    report = {
        "format": "laitp-k230-static-probe-1.0",
        "note": "静态图探测，不是 nncase 转换或板端验证；不得据此声称 K230 可运行。",
        "probe": probe,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output = args.output if args.output.is_absolute() else (ROOT / args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
        print(f"已写入 {output}")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
