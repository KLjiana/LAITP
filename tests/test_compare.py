"""模型对比命令测试。"""

from __future__ import annotations

import contextlib
import csv
import io
import json
from pathlib import Path
from typing import Any

import onnx
from onnx import TensorProto, helper
from PIL import Image

from backend.runtime.compare import main
from tests.support.packages import (
    build_package,
    refresh_digests,
    reopen_manifest,
    save_manifest,
)

LABELS = ("水杯", "书本", "笔袋")


def add_output_bias(package: Path, bias: list[float]) -> None:
    """在 ReduceMean 之后叠加常量偏置，让该包总是预测偏置最大的类别。"""
    model_path = package / "model.onnx"
    model = onnx.load(str(model_path))
    graph = model.graph
    reduce_node = next(node for node in graph.node if node.op_type == "ReduceMean")
    original_output = reduce_node.output[0]
    # 原 ReduceMean 输出改名，再经 Add 叠加偏置后写回清单声明的输出名。
    reduce_node.output[0] = "logits_raw"
    graph.initializer.append(
        helper.make_tensor("bias", TensorProto.FLOAT, [len(bias)], bias)
    )
    graph.node.append(
        helper.make_node("Add", ["logits_raw", "bias"], [original_output])
    )
    model.ir_version = 10
    onnx.save(model, str(model_path))


def build_loadable_package(
    root: Path,
    *,
    artifact_id: str = "art-20261117-0001",
    bias: list[float] | None = None,
) -> Path:
    """构建可加载的测试包；可改产物 ID、叠加输出偏置，并刷新清单摘要。"""
    package = build_package(
        root, patch=lambda manifest: manifest.update(artifact_id=artifact_id)
    )
    if bias is None:
        model_path = package / "model.onnx"
        model = onnx.load(str(model_path))
        model.ir_version = 10
        onnx.save(model, str(model_path))
    else:
        add_output_bias(package, bias)
    manifest = reopen_manifest(package)
    refresh_digests(manifest, package)
    save_manifest(package, manifest)
    return package


def build_compare_packages(tmp_path: Path) -> tuple[Path, Path]:
    """构造两个预测结果不同的包：B 在输出上偏向“书本”，A 按图像颜色预测。"""
    package_a = build_loadable_package(tmp_path / "pkg-a")
    package_b = build_loadable_package(
        tmp_path / "pkg-b",
        artifact_id="art-20261117-0002",
        bias=[0.0, 100.0, 0.0],
    )
    return package_a, package_b


def rewrite_labels(package: Path, labels: list[str]) -> None:
    """改写包内标签文件并刷新清单摘要，用于构造标签顺序不一致的包。"""
    (package / "labels.json").write_text(
        json.dumps(labels, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    manifest = reopen_manifest(package)
    manifest["labels"]["count"] = len(labels)
    refresh_digests(manifest, package)
    save_manifest(package, manifest)


def make_image(path: Path, color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32), color).save(path)


def run_cli(*args: str) -> tuple[int, dict[str, Any]]:
    """捕获命令的 JSON 输出（与 test_runtime.py 的 run_cli 写法一致）。"""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        exit_code = main(list(args))
    return exit_code, json.loads(buffer.getvalue())


def test_compare_labeled_directory(tmp_path: Path) -> None:
    package_a, package_b = build_compare_packages(tmp_path)
    images = tmp_path / "images"
    make_image(images / "水杯" / "batch-a" / "a.png", (200, 10, 10))
    make_image(images / "书本" / "batch-a" / "b.png", (10, 200, 10))
    output = tmp_path / "result.json"
    exit_code, _ = run_cli(
        "--packages",
        str(package_a),
        str(package_b),
        "--images",
        str(images),
        "--output",
        str(output),
    )
    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["count"] == 2
    assert payload["labeled"] == 2
    assert payload["errors"] == []
    # 两个包标签一致：labels_match 为 true，无标签相关告警。
    assert payload["labels_match"] is True
    assert payload["labels_a"] == payload["labels_b"] == list(LABELS)
    assert payload["warnings"] == []

    reports = payload["packages"]
    assert [item["package"] for item in reports] == [str(package_a), str(package_b)]
    assert [item["artifact_id"] for item in reports] == [
        "art-20261117-0001",
        "art-20261117-0002",
    ]
    assert [item["labels"] for item in reports] == [list(LABELS), list(LABELS)]
    assert [item["accuracy"] for item in reports] == [1.0, 0.5]
    for report in reports:
        assert isinstance(report["mean_seconds"], float)
        assert report["mean_seconds"] >= 0.0
    assert reports[0]["per_class"] == {
        "书本": {"count": 1, "correct": 1, "accuracy": 1.0},
        "水杯": {"count": 1, "correct": 1, "accuracy": 1.0},
    }
    assert reports[1]["per_class"]["水杯"] == {
        "count": 1,
        "correct": 0,
        "accuracy": 0.0,
    }
    assert reports[1]["per_class"]["书本"] == {
        "count": 1,
        "correct": 1,
        "accuracy": 1.0,
    }

    assert payload["agreement"] == {"count": 1, "total": 2, "ratio": 0.5}

    cup_image = str(Path("水杯") / "batch-a" / "a.png")
    book_image = str(Path("书本") / "batch-a" / "b.png")
    assert len(payload["disagreements"]) == 1
    disagreement = payload["disagreements"][0]
    assert disagreement["image"] == cup_image
    assert disagreement["true_label"] == "水杯"
    assert disagreement["pred_a"] == "水杯"
    assert disagreement["pred_b"] == "书本"
    assert 0.0 < disagreement["confidence_a"] <= 1.0
    assert 0.0 < disagreement["confidence_b"] <= 1.0
    assert disagreement["correct_a"] is True
    assert disagreement["correct_b"] is False

    details = {item["image"]: item for item in payload["images"]}
    assert set(details) == {cup_image, book_image}
    assert details[cup_image]["true_label"] == "水杯"
    assert details[cup_image]["agree"] is False
    assert [
        entry["predicted_label"] for entry in details[cup_image]["packages"]
    ] == ["水杯", "书本"]
    assert [entry["correct"] for entry in details[cup_image]["packages"]] == [
        True,
        False,
    ]
    assert details[cup_image]["packages"][0]["artifact_id"] == "art-20261117-0001"
    assert details[book_image]["agree"] is True
    assert [
        entry["predicted_label"] for entry in details[book_image]["packages"]
    ] == ["书本", "书本"]


def test_compare_flat_unlabeled_directory(tmp_path: Path) -> None:
    package_a, package_b = build_compare_packages(tmp_path)
    images = tmp_path / "flat"
    make_image(images / "one.png", (200, 10, 10))
    make_image(images / "two.png", (10, 200, 10))
    exit_code, payload = run_cli(
        "--packages", str(package_a), str(package_b), "--images", str(images)
    )
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["count"] == 2
    assert payload["labeled"] == 0
    assert [item["accuracy"] for item in payload["packages"]] == [None, None]
    assert [item["per_class"] for item in payload["packages"]] == [{}, {}]
    assert payload["agreement"] == {"count": 1, "total": 2, "ratio": 0.5}
    assert payload["disagreements"][0]["image"] == "one.png"
    assert payload["disagreements"][0]["true_label"] is None
    assert payload["disagreements"][0]["correct_a"] is None
    assert payload["disagreements"][0]["correct_b"] is None
    for item in payload["images"]:
        assert item["true_label"] is None
        assert all(entry["correct"] is None for entry in item["packages"])


def test_compare_missing_package(tmp_path: Path) -> None:
    _, package_b = build_compare_packages(tmp_path)
    images = tmp_path / "images"
    make_image(images / "水杯" / "batch-a" / "a.png", (200, 10, 10))
    exit_code, payload = run_cli(
        "--packages", str(tmp_path / "missing"), str(package_b), "--images", str(images)
    )
    assert exit_code == 1
    assert payload["ok"] is False
    assert "模型包不存在" in payload["error"]
    assert payload["package_index"] == 0


def test_compare_writes_output_file(tmp_path: Path) -> None:
    package_a, package_b = build_compare_packages(tmp_path)
    images = tmp_path / "images"
    make_image(images / "笔袋" / "batch-a" / "a.png", (10, 10, 200))
    output = tmp_path / "reports" / "compare.json"
    exit_code, printed = run_cli(
        "--packages",
        str(package_a),
        str(package_b),
        "--images",
        str(images),
        "--output",
        str(output),
    )
    assert exit_code == 0
    text = output.read_text(encoding="utf-8")
    assert text.endswith("\n")
    payload = json.loads(text)
    assert payload == printed
    assert payload["ok"] is True
    assert payload["count"] == 1
    assert len(payload["packages"]) == 2
    assert payload["disagreements"][0]["pred_a"] == "笔袋"
    assert payload["disagreements"][0]["pred_b"] == "书本"
    assert payload["packages"][0]["accuracy"] == 1.0
    assert payload["packages"][1]["accuracy"] == 0.0


def test_compare_csv_labeled_directory(tmp_path: Path) -> None:
    package_a, package_b = build_compare_packages(tmp_path)
    images = tmp_path / "images"
    make_image(images / "水杯" / "batch-a" / "a.png", (200, 10, 10))
    make_image(images / "书本" / "batch-a" / "b.png", (10, 200, 10))
    csv_path = tmp_path / "reports" / "compare.csv"
    exit_code, payload = run_cli(
        "--packages",
        str(package_a),
        str(package_b),
        "--images",
        str(images),
        "--csv",
        str(csv_path),
    )
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["csv"] == str(csv_path)
    assert csv_path.is_file()

    # UTF-8 BOM 保证 Excel 直接打开不乱码。
    raw = csv_path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == [
        "图片",
        "真实类别",
        "A 预测",
        "A 置信度",
        "A 是否正确",
        "B 预测",
        "B 置信度",
        "B 是否正确",
        "是否一致",
    ]
    # 表头 + 可对比图片逐行。
    assert len(rows) == payload["count"] + 1 == 3

    by_image = {row[0]: row for row in rows[1:]}
    cup = by_image[str(Path("水杯") / "batch-a" / "a.png")]
    assert cup[1] == "水杯"
    assert cup[2] == "水杯"
    assert 0.0 < float(cup[3]) <= 1.0
    assert cup[4] == "1"
    assert cup[5] == "书本"
    assert 0.0 < float(cup[6]) <= 1.0
    assert cup[7] == "0"
    assert cup[8] == "0"
    book = by_image[str(Path("书本") / "batch-a" / "b.png")]
    assert book[1] == "书本"
    assert book[2] == "书本" and book[5] == "书本"
    assert book[4] == "1" and book[7] == "1"
    assert book[8] == "1"


def test_compare_csv_flat_unlabeled_directory(tmp_path: Path) -> None:
    package_a, package_b = build_compare_packages(tmp_path)
    images = tmp_path / "flat"
    make_image(images / "one.png", (200, 10, 10))
    make_image(images / "two.png", (10, 200, 10))
    csv_path = tmp_path / "reports" / "flat.csv"
    exit_code, payload = run_cli(
        "--packages",
        str(package_a),
        str(package_b),
        "--images",
        str(images),
        "--csv",
        str(csv_path),
    )
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["csv"] == str(csv_path)
    assert csv_path.is_file()

    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert len(rows) == payload["count"] + 1 == 3
    assert rows[0][:2] == ["图片", "真实类别"]
    assert {row[0] for row in rows[1:]} == {"one.png", "two.png"}
    for row in rows[1:]:
        # 平铺目录无标签：真实类别与两包“是否正确”均留空。
        assert row[1] == ""
        assert row[4] == ""
        assert row[7] == ""
        assert row[2] in LABELS and row[5] in LABELS
        assert row[8] in {"0", "1"}
        assert 0.0 < float(row[3]) <= 1.0
        assert 0.0 < float(row[6]) <= 1.0


def test_compare_label_order_mismatch_is_warning_only(tmp_path: Path) -> None:
    package_a, package_b = build_compare_packages(tmp_path)
    reordered = ["书本", "水杯", "笔袋"]
    # 只改 B 包标签顺序并刷新清单摘要，模型与类别数保持不变。
    rewrite_labels(package_b, reordered)

    images = tmp_path / "images"
    make_image(images / "水杯" / "batch-a" / "a.png", (200, 10, 10))
    make_image(images / "书本" / "batch-a" / "b.png", (10, 200, 10))
    exit_code, payload = run_cli(
        "--packages", str(package_a), str(package_b), "--images", str(images)
    )

    # 标签不一致只提示，不改变 ok/退出码，也不中断预测与统计。
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["count"] == 2
    assert payload["labeled"] == 2
    assert payload["errors"] == []
    assert payload["labels_match"] is False
    assert payload["labels_a"] == list(LABELS)
    assert payload["labels_b"] == reordered
    assert payload["labels_a"] != payload["labels_b"]
    assert payload["warnings"]
    assert any("标签" in warning for warning in payload["warnings"])

    reports = payload["packages"]
    assert [report["labels"] for report in reports] == [list(LABELS), reordered]
    assert all(report["accuracy"] is not None for report in reports)
    # 预测仍按各包自己的类别索引映射标签：B 包输出偏置固定在索引 1，
    # 即 B 的第二个类别“水杯”，而不是 A 包索引 1 的“书本”。
    for item in payload["images"]:
        entry_a, entry_b = item["packages"]
        assert entry_a["predicted_label"] in LABELS
        assert entry_b["predicted_label"] in reordered
        assert entry_b["predicted_label"] == "水杯"
