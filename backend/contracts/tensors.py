"""张量声明的语义工具：布局、维度、类别轴和量化元数据。

这里不读取模型文件，只处理清单中的声明；与真实模型的比对在
``onnx_signature`` 和 ``manifest`` 中完成。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

IMAGE_LAYOUTS: dict[str, tuple[str, ...]] = {
    "NCHW": ("N", "C", "H", "W"),
    "NHWC": ("N", "H", "W", "C"),
    "CHW": ("C", "H", "W"),
    "HWC": ("H", "W", "C"),
}
QUANTIZED_DTYPES = frozenset({"int8", "uint8"})
CLASS_MEANINGS = frozenset({"class_logits", "class_probabilities"})

DynamicDim = dict[str, Any]


@dataclass(frozen=True)
class TensorSignature:
    """模型实际输入或输出的张量签名。动态维度记为 ``None``。"""

    name: str
    shape: tuple[int | None, ...]
    dtype: str


def layout_rank(layout: str) -> int:
    return len(IMAGE_LAYOUTS[layout])


def dim_index(layout: str, letter: str) -> int:
    """布局中某个轴的序号，例如 NCHW 的 ``C`` 是 1。"""
    return IMAGE_LAYOUTS[layout].index(letter)


def declared_dim(dim: int | DynamicDim) -> tuple[int | None, int | None, int | None]:
    """把声明维度转换为 ``(固定值, 最小值, 最大值)``。"""
    if isinstance(dim, int):
        return dim, dim, dim
    minimum = dim.get("min")
    maximum = dim.get("max")
    return None, minimum, maximum


def normalize_axis(axis: int, rank: int) -> int | None:
    """把可能为负的轴序号转为非负序号，越界返回 ``None``。"""
    resolved = axis + rank if axis < 0 else axis
    if 0 <= resolved < rank:
        return resolved
    return None


def class_dim_of(output: dict[str, Any]) -> tuple[int | None, int | None, int | None] | None:
    """返回输出张量类别轴的 ``(固定值, 最小, 最大)``；无法定位时返回 ``None``。"""
    meaning = output.get("meaning")
    if meaning not in CLASS_MEANINGS:
        return None
    shape = output.get("shape") or []
    axis = normalize_axis(int(output.get("class_axis", -1)), len(shape))
    if axis is None:
        return None
    return declared_dim(shape[axis])
