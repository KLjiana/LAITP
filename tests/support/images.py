"""生成测试用图片与数据目录。

图片只用于验证数据清单、划分和完整性规则，不代表真实课堂数据。
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from PIL import Image


def make_image(path: Path, color: tuple[int, int, int], size: tuple[int, int] = (8, 8)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, format="PNG")
    return path


def build_dataset_tree(
    root: Path,
    *,
    classes: Sequence[str],
    train_batches: int = 3,
    images_per_batch: int = 2,
    test_batches: int = 1,
    test_images_per_batch: int = 1,
) -> Path:
    """按 ``images/<类别>/<批次>/<图片>`` 生成训练/验证与测试目录。"""
    for class_id, name in enumerate(classes):
        for batch in range(train_batches):
            for index in range(images_per_batch):
                color = (
                    (class_id * 40 + 7) % 256,
                    (batch * 50 + 11) % 256,
                    (index * 60 + 13) % 256,
                )
                make_image(
                    root / "images" / name / f"batch-{batch + 1}" / f"{index + 1:03d}.png",
                    color,
                )
        for batch in range(test_batches):
            for index in range(test_images_per_batch):
                color = (
                    (class_id * 40 + 23) % 256,
                    (batch * 50 + 31) % 256,
                    (index * 60 + 41) % 256,
                )
                make_image(
                    root
                    / "test-images"
                    / name
                    / f"test-batch-{batch + 1}"
                    / f"{index + 1:03d}.png",
                    color,
                )
    return root
