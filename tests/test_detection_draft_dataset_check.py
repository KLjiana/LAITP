"""检测数据集清单 2.0 草案跨字段校验器的测试（草案，未激活，不接入生产）。

这些测试只验证 ``scripts/detection_draft_dataset_check.py`` 能在**临时目录**中：

1. 对 ``scripts/detection_draft_check.py`` 生成的合成图片/标注构造的合法草案清单
   校验通过，并写出 UTF-8 无 BOM 的 JSON 报告；
2. 篡改图片内容后按 ``sha256`` 不符失败并定位到该样本；
3. ``box_count`` 与标注框数不一致时失败；
4. 标注框越界时失败；
5. 缺图片文件时失败。

同时确认清单结构错误时输出错误 JSON 且退出码为 1、跨划分 ``capture_batch``
只产生 warning 不阻断。测试数据只存在于 tmp 目录，不写入仓库 ``data/``；
这些测试通过**不表示**检测标注、数据集清单、训练、导出、推理或转换能力已经
实现或验证通过。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
DRAFT_CHECK_SCRIPT = SCRIPTS_DIR / "detection_draft_check.py"
DATASET_CHECK_SCRIPT = SCRIPTS_DIR / "detection_draft_dataset_check.py"
MANIFEST_NAME = "dataset-manifest-2.0-draft.json"
SAMPLE_IMAGES = 3
SPLITS = ("train", "val", "test")
CAPTURE_BATCHES = ("batch-1", "batch-2", "batch-3")
UTF8_BOM = b"\xef\xbb\xbf"


# --------------------------------------------------------------------------- #
# 模块加载与 tmp 数据构造
# --------------------------------------------------------------------------- #


def load_draft_check_module() -> Any:
    """按文件路径加载既有草案工具，复用它的 ``generate_valid_dataset``。"""
    name = "detection_draft_check"
    existing = sys.modules.get(name)
    if existing is not None and hasattr(existing, "generate_valid_dataset"):
        return existing
    spec = importlib.util.spec_from_file_location(name, DRAFT_CHECK_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


def load_dataset_check_module() -> Any:
    """按文件路径加载被测校验器（用于读取 docstring 与常量）。"""
    name = "detection_draft_dataset_check"
    existing = sys.modules.get(name)
    if existing is not None and hasattr(existing, "run_check"):
        return existing
    spec = importlib.util.spec_from_file_location(name, DATASET_CHECK_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


def read_json(path: Path) -> Any:
    raw = path.read_bytes()
    assert not raw.startswith(UTF8_BOM), f"{path} 必须是不带 BOM 的 UTF-8"
    return json.loads(raw.decode("utf-8"))


def write_json(path: Path, payload: Any) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")
    assert not path.read_bytes().startswith(UTF8_BOM)


def run_cli(
    manifest_path: Path, output: Path | None = None
) -> tuple[int, dict[str, Any]]:
    """以子进程调用被测 CLI，返回退出码与标准输出 JSON。"""
    command = [
        sys.executable,
        str(DATASET_CHECK_SCRIPT),
        "--manifest",
        str(manifest_path),
    ]
    if output is not None:
        command += ["--output", str(output)]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True)
    stdout = completed.stdout.decode("utf-8")
    assert not stdout.startswith("\ufeff"), "标准输出必须是不带 BOM 的 UTF-8 JSON"
    return completed.returncode, json.loads(stdout)


@pytest.fixture(scope="module")
def base_dataset(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """用既有草案工具生成 3 张合成图 + 标注，并构造合法的清单 2.0 草案。"""
    root = tmp_path_factory.mktemp("dataset-check") / "dataset"
    root.mkdir()
    draft = load_draft_check_module()
    samples = draft.generate_valid_dataset(root, SAMPLE_IMAGES)
    assert len(samples) == SAMPLE_IMAGES

    manifest: dict[str, Any] = {
        "schema_version": "2.0-draft",
        "dataset_version": "2.0-draft",
        "dataset_id": "ds-20261119-0001",
        "created_at": "2026-11-19T10:00:00+08:00",
        "classes": list(draft.CLASSES),
        "splits": {},
    }
    assert 1 <= len(manifest["classes"]) <= 2
    for split, batch, sample in zip(SPLITS, CAPTURE_BATCHES, samples):
        image_path = root / sample.image_rel
        annotation = sample.annotation
        manifest["splits"][split] = {
            "samples": [
                {
                    "image": sample.image_rel,
                    "annotation": sample.annotation_rel,
                    "sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
                    "width": annotation["width"],
                    "height": annotation["height"],
                    "box_count": len(annotation["boxes"]),
                    "capture_batch": batch,
                }
            ]
        }
    write_json(root / MANIFEST_NAME, manifest)
    return root


def clone_dataset(base_root: Path, tmp_path: Path) -> Path:
    """每个测试复制一份独立数据集，避免相互污染。"""
    root = tmp_path / "dataset"
    shutil.copytree(base_root, root)
    return root


# --------------------------------------------------------------------------- #
# 1. 合法清单通过、报告契约与结构错误 JSON
# --------------------------------------------------------------------------- #


def test_valid_dataset_passes_and_reports_contract(
    base_dataset: Path, tmp_path: Path
) -> None:
    root = clone_dataset(base_dataset, tmp_path)
    manifest_path = root / MANIFEST_NAME
    report_path = tmp_path / "report.json"

    returncode, report = run_cli(manifest_path, report_path)
    assert returncode == 0, report
    assert report["ok"] is True
    assert report["samples"] == SAMPLE_IMAGES
    assert report["issues"] == []
    assert report["warnings"] == []
    assert Path(report["manifest"]).resolve() == manifest_path.resolve()

    checks = report["checks"]
    assert checks["manifest.readable"] == {"passed": 1, "failed": 0}
    assert checks["manifest.schema"] == {"passed": 1, "failed": 0}
    assert checks["image.exists"] == {"passed": SAMPLE_IMAGES, "failed": 0}
    assert checks["image.width"] == {"passed": SAMPLE_IMAGES, "failed": 0}
    assert checks["image.height"] == {"passed": SAMPLE_IMAGES, "failed": 0}
    assert checks["image.sha256"] == {"passed": SAMPLE_IMAGES, "failed": 0}
    assert checks["annotation.schema"] == {"passed": SAMPLE_IMAGES, "failed": 0}
    assert checks["box_count"] == {"passed": SAMPLE_IMAGES, "failed": 0}
    assert checks["box.class_id"] == {"passed": SAMPLE_IMAGES, "failed": 0}
    assert checks["box.bounds"] == {"passed": SAMPLE_IMAGES, "failed": 0}
    assert checks["capture_batch"] == {"passed": SAMPLE_IMAGES, "failed": 0}
    assert all(entry["failed"] == 0 for entry in checks.values())

    # 报告文件与标准输出一致，UTF-8 且不带 BOM。
    assert report_path.is_file()
    raw = report_path.read_bytes()
    assert not raw.startswith(UTF8_BOM)
    assert json.loads(raw.decode("utf-8")) == report

    # 草案/未激活/不接入生产必须在报告 notes 与模块 docstring 中说明。
    assert report["draft"] is True
    assert report["activated"] is False
    notes = "\n".join(report["notes"])
    for phrase in ("草案", "未激活", "不接入生产"):
        assert phrase in notes, f"报告 notes 必须提示 {phrase!r}"
    docstring = load_dataset_check_module().__doc__ or ""
    for phrase in ("草案", "未激活", "不接入生产", "退出码"):
        assert phrase in docstring, f"模块 docstring 必须提示 {phrase!r}"

    # 同一 capture_batch 出现在多个划分：只 warning，不阻断。
    overlapping = read_json(manifest_path)
    overlapping["splits"]["val"]["samples"][0]["capture_batch"] = "batch-1"
    overlap_path = root / "dataset-manifest-overlap.json"
    write_json(overlap_path, overlapping)
    returncode, report = run_cli(overlap_path)
    assert returncode == 0
    assert report["ok"] is True
    assert report["issues"] == []
    warning_codes = {warning["code"] for warning in report["warnings"]}
    assert "CAPTURE_BATCH_CROSS_SPLIT" in warning_codes
    warning = next(
        item
        for item in report["warnings"]
        if item["code"] == "CAPTURE_BATCH_CROSS_SPLIT"
    )
    assert warning["samples"] == ["train[0]", "val[0]"]

    # 清单结构错误：退出码 1，输出错误 JSON 并定位到字段。
    broken = read_json(manifest_path)
    del broken["splits"]["train"]["samples"][0]["width"]
    broken_path = root / "dataset-manifest-broken.json"
    write_json(broken_path, broken)
    returncode, report = run_cli(broken_path)
    assert returncode == 1
    assert report["ok"] is False
    assert report["error"]["code"] == "MANIFEST_SCHEMA_INVALID"
    assert report["checks"]["manifest.schema"] == {"passed": 0, "failed": 1}
    assert report["issues"], "结构错误必须给出 issues"
    assert all(issue["code"] == "MANIFEST_SCHEMA_INVALID" for issue in report["issues"])
    assert any("samples[0]" in issue["location"] for issue in report["issues"])


# --------------------------------------------------------------------------- #
# 2. 篡改图片 → sha256 不符
# --------------------------------------------------------------------------- #


def test_tampered_image_sha256_is_located(
    base_dataset: Path, tmp_path: Path
) -> None:
    root = clone_dataset(base_dataset, tmp_path)
    manifest_path = root / MANIFEST_NAME
    image_path = root / "images" / "case-000.png"
    # 追加字节：图片仍可解码、宽高不变，只有文件内容摘要改变。
    image_path.write_bytes(image_path.read_bytes() + b"\n")

    returncode, report = run_cli(manifest_path)
    assert returncode == 1
    assert report["ok"] is False
    codes = {issue["code"] for issue in report["issues"]}
    assert codes == {"IMAGE_SHA256_MISMATCH"}, report["issues"]
    issue = report["issues"][0]
    assert issue["sample"] == "train[0]"
    assert "sha256" in issue["location"]
    assert report["checks"]["image.sha256"] == {
        "passed": SAMPLE_IMAGES - 1,
        "failed": 1,
    }


# --------------------------------------------------------------------------- #
# 3. box_count 与实际标注框数不一致
# --------------------------------------------------------------------------- #


def test_box_count_mismatch_is_rejected(
    base_dataset: Path, tmp_path: Path
) -> None:
    root = clone_dataset(base_dataset, tmp_path)
    manifest_path = root / MANIFEST_NAME
    manifest = read_json(manifest_path)
    manifest["splits"]["val"]["samples"][0]["box_count"] += 2
    write_json(manifest_path, manifest)

    returncode, report = run_cli(manifest_path)
    assert returncode == 1
    codes = {issue["code"] for issue in report["issues"]}
    assert codes == {"BOX_COUNT_MISMATCH"}, report["issues"]
    issue = report["issues"][0]
    assert issue["sample"] == "val[0]"
    assert "box_count" in issue["location"]
    assert report["checks"]["box_count"] == {
        "passed": SAMPLE_IMAGES - 1,
        "failed": 1,
    }


# --------------------------------------------------------------------------- #
# 4. 标注框越界
# --------------------------------------------------------------------------- #


def test_out_of_bounds_box_is_rejected(
    base_dataset: Path, tmp_path: Path
) -> None:
    root = clone_dataset(base_dataset, tmp_path)
    manifest_path = root / MANIFEST_NAME
    annotation_path = root / "annotations" / "case-002.json"
    annotation = read_json(annotation_path)
    assert annotation["boxes"], "合成标注应至少有一个框"
    # 只改坐标：Schema 仍通过（整数且 x >= 0），但 x + w 超出图片宽度。
    annotation["boxes"][0]["x"] = annotation["width"] - 1
    write_json(annotation_path, annotation)

    returncode, report = run_cli(manifest_path)
    assert returncode == 1
    codes = {issue["code"] for issue in report["issues"]}
    assert codes == {"BOX_OUT_OF_BOUNDS"}, report["issues"]
    issue = report["issues"][0]
    assert issue["sample"] == "test[0]"
    assert "boxes[0]" in issue["location"]
    assert report["checks"]["box.bounds"] == {
        "passed": SAMPLE_IMAGES - 1,
        "failed": 1,
    }


# --------------------------------------------------------------------------- #
# 5. 缺图片文件
# --------------------------------------------------------------------------- #


def test_missing_image_is_rejected(base_dataset: Path, tmp_path: Path) -> None:
    root = clone_dataset(base_dataset, tmp_path)
    manifest_path = root / MANIFEST_NAME
    (root / "images" / "case-001.png").unlink()

    returncode, report = run_cli(manifest_path)
    assert returncode == 1
    codes = {issue["code"] for issue in report["issues"]}
    assert codes == {"IMAGE_MISSING"}, report["issues"]
    issue = report["issues"][0]
    assert issue["sample"] == "val[0]"
    assert "image" in issue["location"]
    assert report["checks"]["image.exists"] == {
        "passed": SAMPLE_IMAGES - 1,
        "failed": 1,
    }
    # 图片缺失后依赖它的规则不评估，避免级联噪声。
    assert report["checks"]["image.readable"] == {"passed": SAMPLE_IMAGES - 1, "failed": 0}
    assert report["checks"]["image.sha256"] == {"passed": SAMPLE_IMAGES - 1, "failed": 0}
