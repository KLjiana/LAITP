"""批量预测命令测试。"""

from __future__ import annotations

import json
from pathlib import Path

import onnx
from PIL import Image

from backend.runtime.batch import main
from tests.support.packages import (
    build_package,
    refresh_digests,
    reopen_manifest,
    save_manifest,
)


def build_loadable_package(root: Path) -> Path:
    """把最小模型降到当前 onnxruntime 支持的 IR 版本并刷新清单摘要。"""
    package = build_package(root)
    model_path = package / "model.onnx"
    model = onnx.load(str(model_path))
    model.ir_version = 10
    onnx.save(model, str(model_path))
    manifest = reopen_manifest(package)
    refresh_digests(manifest, package)
    save_manifest(package, manifest)
    return package


def make_image(path: Path, color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32), color).save(path)


def test_batch_predict_labeled(tmp_path: Path) -> None:
    package = build_loadable_package(tmp_path / "pkg")
    images = tmp_path / "images"
    make_image(images / "水杯" / "batch-a" / "a.png", (200, 10, 10))
    make_image(images / "书本" / "batch-a" / "b.png", (10, 200, 10))
    output = tmp_path / "result.json"
    csv_output = tmp_path / "result.csv"
    exit_code = main(
        ["--package", str(package), "--images", str(images),
         "--output", str(output), "--csv", str(csv_output)]
    )
    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["count"] == 2
    assert payload["labeled"] == 2
    assert payload["accuracy"] is not None
    assert len(payload["images"]) == 2
    assert all(item["predicted_label"] for item in payload["images"])
    assert payload["artifact_id"] == "art-20261117-0001"
    assert payload["csv"] == str(csv_output)
    assert set(payload["per_class"]) == {"水杯", "书本"}
    for stats in payload["per_class"].values():
        assert stats["count"] == 1
        assert stats["accuracy"] in (0.0, 1.0)
    assert set(payload["per_batch"]) == {"batch-a"}
    batch_stats = payload["per_batch"]["batch-a"]
    assert batch_stats["count"] == 2
    assert batch_stats["accuracy"] == round(
        batch_stats["correct"] / batch_stats["count"], 6
    )
    assert batch_stats["accuracy"] in (0.0, 0.5, 1.0)
    csv_text = csv_output.read_text(encoding="utf-8-sig")
    assert "图片,真实类别,预测类别" in csv_text
    assert len(csv_text.strip().splitlines()) == 3


def test_batch_predict_unlabeled(tmp_path: Path) -> None:
    package = build_loadable_package(tmp_path / "pkg")
    images = tmp_path / "flat"
    make_image(images / "one.png", (10, 10, 200))
    output = tmp_path / "flat-result.json"
    assert (
        main(
            ["--package", str(package), "--images", str(images), "--output", str(output)]
        )
        == 0
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["count"] == 1
    assert payload["labeled"] == 0
    assert payload["accuracy"] is None
    assert payload["per_batch"] == {}


def test_batch_predict_missing_package(tmp_path: Path) -> None:
    exit_code = main(
        ["--package", str(tmp_path / "missing"), "--images", str(tmp_path)]
    )
    assert exit_code == 1
