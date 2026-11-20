"""生成演示用图片数据集（离线环境，使用包内 Pillow）。

用法：
    python scripts/make_demo_dataset.py --root <目录> [--test]

生成 <目录>/苹果/{batch-1,batch-2}/*.png 与 <目录>/香蕉/{batch-1,batch-2}/*.png；
--test 时额外在 <目录>-test 下生成测试集（batch-test）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw

CLASSES = {"苹果": (200, 40, 40), "香蕉": (230, 200, 40)}


def make_images(root: Path, per_batch: int = 3) -> int:
    count = 0
    for label, color in CLASSES.items():
        for batch_index, batch in enumerate(("batch-1", "batch-2")):
            directory = root / label / batch
            directory.mkdir(parents=True, exist_ok=True)
            for index in range(per_batch):
                image = Image.new(
                    "RGB", (64, 64), (245 - batch_index * 15, 245, 235)
                )
                draw = ImageDraw.Draw(image)
                offset = batch_index * 8 + index * 4
                draw.ellipse(
                    (6 + offset, 14 + offset, 46 + offset, 54 + offset), fill=color
                )
                image.save(directory / f"{label}-{index}.png")
                count += 1
    return count


def make_test_images(root: Path, per_batch: int = 2) -> int:
    count = 0
    for label, color in CLASSES.items():
        directory = root / label / "batch-test"
        directory.mkdir(parents=True, exist_ok=True)
        for index in range(per_batch):
            image = Image.new("RGB", (64, 64), (235, 245 - index * 10, 245))
            draw = ImageDraw.Draw(image)
            draw.ellipse((12 + index * 6, 20, 52, 60), fill=color)
            draw.line((4, 60 - index * 8, 60, 60 - index * 8), width=2)
            image.save(directory / f"{label}-test-{index}.png")
            count += 1
    return count


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    parser = argparse.ArgumentParser(description="生成演示图片数据集")
    parser.add_argument("--root", required=True)
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args(argv)

    root = Path(args.root)
    train_count = make_images(root)
    test_count = make_test_images(Path(str(root) + "-test")) if args.test else 0
    print(
        f'{{"ok": true, "root": "{root}", "train": {train_count}, '
        f'"test": {test_count}}}'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
