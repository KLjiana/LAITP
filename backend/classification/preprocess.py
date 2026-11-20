"""图像预处理定义。

训练与推理必须使用同一套解码、缩放和归一化语义，参数直接对应模型清单的
``preprocessing`` 字段。这里用显式的 numpy 运算实现契约公式
``(pixel * scale - mean) / std``，避免训练框架与运行时各自实现导致末位差异；
运行时会按清单步骤重新执行同一公式并比对输入张量摘要。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image

_INTERPOLATION = {
    "nearest": Image.NEAREST,
    "bilinear": Image.BILINEAR,
    "bicubic": Image.BICUBIC,
    "area": Image.BOX,
}
SCALE = 1.0 / 255.0


@dataclass(frozen=True)
class PreprocessSpec:
    """与模型契约一致的预处理声明。"""

    width: int = 224
    height: int = 224
    interpolation: str = "bilinear"
    mean: tuple[float, float, float] = (0.485, 0.456, 0.406)
    std: tuple[float, float, float] = (0.229, 0.224, 0.225)
    color_space: str = "RGB"

    def __post_init__(self) -> None:
        if self.width < 1 or self.height < 1:
            raise ValueError("输入尺寸必须为正数")
        if self.interpolation not in _INTERPOLATION:
            raise ValueError(f"不支持的插值方式 {self.interpolation!r}")
        if len(self.mean) != 3 or len(self.std) != 3:
            raise ValueError("mean/std 必须各含 3 个通道参数")
        if any(value <= 0 for value in self.std):
            raise ValueError("std 必须为正数")
        if self.color_space != "RGB":
            raise ValueError("T04 训练实现仅支持 RGB 输入；BGR 需在后续任务中实现并验证")

    def to_array(self, image: Image.Image) -> np.ndarray:
        """返回 CHW float32 数组，运算顺序与契约公式一致。"""
        if image.mode != "RGB":
            image = image.convert("RGB")
        resized = image.resize(
            (self.width, self.height), _INTERPOLATION[self.interpolation]
        )
        array = np.asarray(resized, dtype=np.float32)
        mean = np.asarray(self.mean, dtype=np.float32)
        std = np.asarray(self.std, dtype=np.float32)
        normalized = (array * SCALE - mean) / std
        return np.ascontiguousarray(np.transpose(normalized, (2, 0, 1)), dtype=np.float32)

    def transform(self) -> "_TensorTransform":
        return _TensorTransform(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "interpolation": self.interpolation,
            "mean": list(self.mean),
            "std": list(self.std),
            "color_space": self.color_space,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PreprocessSpec":
        return cls(
            width=int(data["width"]),
            height=int(data["height"]),
            interpolation=str(data["interpolation"]),
            mean=tuple(float(value) for value in data["mean"]),  # type: ignore[arg-type]
            std=tuple(float(value) for value in data["std"]),  # type: ignore[arg-type]
            color_space=str(data["color_space"]),
        )

    def manifest_fields(self) -> dict[str, Any]:
        """生成模型清单的 ``preprocessing`` 段（契约 1.0）。"""
        return {
            "executor": "host",
            "source_pixel_range": [0, 255],
            "steps": [
                {
                    "op": "resize",
                    "width": self.width,
                    "height": self.height,
                    "mode": "stretch",
                    "interpolation": self.interpolation,
                },
                {
                    "op": "normalize",
                    "formula": "(pixel * scale - mean) / std",
                    "scale": SCALE,
                    "mean": list(self.mean),
                    "std": list(self.std),
                    "channel_order": self.color_space,
                },
                {"op": "transpose", "from": "HWC", "to": "CHW"},
                {"op": "add_batch_dimension", "axis": 0},
            ],
        }


class _TensorTransform:
    """把 PIL 图片转换为 CHW 张量，供训练与导出复用。"""

    def __init__(self, spec: PreprocessSpec) -> None:
        self._spec = spec

    def __call__(self, image: Image.Image) -> torch.Tensor:
        return torch.from_numpy(self._spec.to_array(image))


def load_image(path: str | Path) -> Image.Image:
    """以 RGB 解码图片；损坏或不支持的格式会抛出异常。"""
    with Image.open(path) as image:
        image.load()
        return image.convert("RGB")
