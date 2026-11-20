"""读取模型文件的真实张量签名。

清单里的 ``inputs`` / ``outputs`` 只是声明，发布和加载前必须与模型文件实际张量
比对。ONNX 通过官方 ``onnx`` 包读取；其他格式或缺少依赖时必须显式失败，
不能跳过检查或按文件名推断。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .tensors import TensorSignature


class IntrospectionError(Exception):
    """无法读取模型签名。``reason`` 是面向用户的中文说明。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ModelSignature:
    """模型文件的实际输入输出与格式信息。"""

    inputs: tuple[TensorSignature, ...]
    outputs: tuple[TensorSignature, ...]
    opset: int | None
    ir_version: int | None
    tool: str


@runtime_checkable
class TensorIntrospector(Protocol):
    """模型签名读取接口。测试可注入假实现，生产路径使用真实模型库。"""

    name: str

    def inspect(self, model_path: Path) -> ModelSignature: ...


class OnnxIntrospector:
    """基于 ``onnx`` 官方包的签名读取器。"""

    name = "onnx"

    def __init__(self) -> None:
        try:
            import onnx  # noqa: F401  # 仅探测依赖是否可用
        except ImportError as error:  # pragma: no cover - 依赖缺失路径
            raise IntrospectionError("未安装 onnx，无法读取模型真实张量") from error
        import onnx

        self._onnx = onnx

    def inspect(self, model_path: Path) -> ModelSignature:
        onnx = self._onnx
        try:
            model = onnx.load(str(model_path), load_external_data=False)
        except Exception as error:  # onnx 的解析异常类型不固定
            raise IntrospectionError(f"无法解析 ONNX 模型：{error}") from error

        graph = model.graph
        try:
            inputs = tuple(_tensor_of(onnx, value) for value in graph.input)
            outputs = tuple(_tensor_of(onnx, value) for value in graph.output)
        except TypeError as error:
            raise IntrospectionError(str(error)) from error

        opset = _opset_of(model)
        return ModelSignature(
            inputs=inputs,
            outputs=outputs,
            opset=opset,
            ir_version=int(model.ir_version) or None,
            tool=f"onnx {getattr(onnx, '__version__', 'unknown')}",
        )


_ONNX_DTYPES: dict[int, str] = {
    1: "float32",
    2: "uint8",
    3: "int8",
    4: "uint16",
    5: "int16",
    6: "int32",
    7: "int64",
    9: "bool",
    10: "float16",
    11: "float64",
    12: "string",
}


def _tensor_of(onnx: Any, value_info: Any) -> TensorSignature:
    tensor_type = value_info.type.tensor_type
    elem_type = int(tensor_type.elem_type)
    dtype = _ONNX_DTYPES.get(elem_type)
    if dtype is None:
        raise TypeError(f"张量 {value_info.name!r} 的数据类型 {elem_type} 不在支持的清单范围内")
    shape: list[int | None] = []
    for dim in tensor_type.shape.dim:
        if dim.HasField("dim_value") and dim.dim_value > 0:
            shape.append(int(dim.dim_value))
        else:
            shape.append(None)
    if not shape:
        raise TypeError(f"张量 {value_info.name!r} 未声明维度，无法校验")
    return TensorSignature(name=value_info.name, shape=tuple(shape), dtype=dtype)


def _opset_of(model: Any) -> int | None:
    for entry in model.opset_import:
        if entry.domain in ("", "ai.onnx"):
            return int(entry.version)
    if model.opset_import:
        return int(model.opset_import[0].version)
    return None


def default_introspector() -> TensorIntrospector | None:
    """返回可用的真实模型读取器；依赖缺失时返回 ``None`` 由调用方报告。"""
    try:
        return OnnxIntrospector()
    except IntrospectionError:
        return None
