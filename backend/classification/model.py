"""MobileNetV3-Small 构建、预训练权重校验与特征提取。

权重文件必须存在于本地且摘要与 ``configs/weights.v1.json`` 一致；
缺失或摘要不符时立即失败，不自动下载。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
from torch import nn
from torchvision.models import mobilenet_v3_small

from ..contracts.errors import Code
from ..contracts.integrity import sha256_file

ARCHITECTURE = "mobilenet_v3_small"
DEFAULT_WEIGHTS_ID = "mobilenet_v3_small-imagenet"


class TrainingError(Exception):
    """训练链路中的显式错误。``code`` 是稳定错误码。"""

    def __init__(self, code: Code, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class WeightReference:
    id: str
    sha256: str
    path: Path
    size_bytes: int
    license: str
    source: str


def load_weight_reference(
    config_path: str | Path, *, weights_id: str = DEFAULT_WEIGHTS_ID
) -> WeightReference:
    """读取权重配置并校验本地文件摘要。

    配置中的相对 ``local_path`` 以仓库根目录（配置文件上两级）为基准。
    """
    path = Path(config_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise TrainingError(
            Code.TRAINING_CONFIG_INVALID,
            f"无法读取权重配置 {path}：{error.strerror or error}",
        ) from error
    except json.JSONDecodeError as error:
        raise TrainingError(
            Code.TRAINING_CONFIG_INVALID, f"权重配置不是有效 JSON：{error}"
        ) from error

    entries = data.get("entries", [])
    entry = next((item for item in entries if item.get("id") == weights_id), None)
    if entry is None:
        raise TrainingError(
            Code.TRAINING_CONFIG_INVALID,
            f"权重配置中没有 id={weights_id!r} 的条目",
        )

    local_path = Path(str(entry["local_path"]))
    if not local_path.is_absolute():
        local_path = path.resolve().parent.parent / local_path
    if not local_path.is_file():
        raise TrainingError(
            Code.TRAINING_WEIGHTS_MISSING,
            f"缺少预训练权重 {local_path}；获取方式见 docs/data-and-runtime-baseline.md，"
            "不得自动下载",
        )

    actual = sha256_file(local_path)
    expected = str(entry["sha256"]).lower()
    if actual != expected:
        raise TrainingError(
            Code.TRAINING_WEIGHTS_DIGEST_MISMATCH,
            f"权重文件摘要 {actual} 与配置 {expected} 不一致，拒绝加载",
        )
    return WeightReference(
        id=weights_id,
        sha256=actual,
        path=local_path,
        size_bytes=int(entry.get("size_bytes", local_path.stat().st_size)),
        license=str(entry.get("license", "")),
        source=str(entry.get("url", "")),
    )


def _load_state_dict(path: Path) -> dict[str, Any]:
    state = torch.load(str(path), map_location="cpu", weights_only=True)
    if isinstance(state, dict) and isinstance(state.get("state_dict"), dict):
        return state["state_dict"]
    if not isinstance(state, dict):
        raise TrainingError(
            Code.TRAINING_ARTIFACT_INVALID, f"权重文件 {path} 不是 state_dict"
        )
    return state


def build_feature_extractor(weights_path: Path | None) -> nn.Module:
    """构建冻结的 MobileNetV3-Small 特征提取器（含 avgpool，不含分类头）。"""
    model = mobilenet_v3_small(weights=None)
    if weights_path is not None:
        model.load_state_dict(_load_state_dict(weights_path), strict=True)
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    model.eval()
    return model


def feature_dim(model: nn.Module) -> int:
    return int(model.classifier[0].in_features)


def extract_features(model: nn.Module, images: torch.Tensor) -> torch.Tensor:
    """对已预处理的 NCHW 张量提取 576 维特征。"""
    with torch.no_grad():
        features = model.features(images)
        pooled = model.avgpool(features)
        return torch.flatten(pooled, 1)


def build_classifier(in_features: int, num_classes: int) -> nn.Linear:
    return nn.Linear(in_features, num_classes)


def build_inference_model(weights_path: Path | None, num_classes: int) -> nn.Module:
    """构建可加载训练产物的完整模型。

    训练时分类头直接作用于 576 维池化特征，因此这里用单个 ``Linear`` 替换
    torchvision 原有的 ``classifier`` 序列，保证训练端与推理端结构一致。
    """
    model = mobilenet_v3_small(weights=None)
    if weights_path is not None:
        model.load_state_dict(_load_state_dict(weights_path), strict=True)
    in_features = int(model.classifier[0].in_features)
    model.classifier = build_classifier(in_features, num_classes)
    return model
