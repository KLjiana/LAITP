"""图像分类后端。

M0-01 当前包含数据清单构建与校验（T03）、CPU 训练线性分类头（T04）；
导出与独立推理在后续任务实现。

训练相关模块依赖 torch/torchvision，未在此处导入，以免数据清单命令也
强制加载深度学习框架。需要训练时显式导入
``backend.classification.training`` 与 ``backend.classification.model``。
"""

from .dataset import (
    DEFAULT_DATASET_POLICY,
    DatasetPolicy,
    build_dataset_manifest,
    summarize,
    validate_dataset_manifest,
)

__all__ = [
    "DEFAULT_DATASET_POLICY",
    "DatasetPolicy",
    "build_dataset_manifest",
    "summarize",
    "validate_dataset_manifest",
]
