"""检测草案“合成图片 + 合成标注”边界检查工具的测试（草案，未激活）。

这些测试只验证 ``scripts/detection_draft_check.py`` 能在**临时目录**生成合成
图片与草案标注、通过草案 Schema 与代码补充的边界规则、并按预期拒绝故意无效
样例；同时确认工具不写入仓库 ``data/`` 或 ``artifacts/`` 以外位置。

草案 Schema 与合成数据都不进入正式课堂数据、训练或后端加载路径；这些测试
通过**不表示**检测标注、训练、导出、推理、转换或板端能力已经实现或验证通过。
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "detection_draft_check.py"
SUMMARY_NAME = "detection-draft-summary.json"
ANNOTATION_SCHEMA = ROOT / "schemas" / "detection" / "annotation.schema.json"
EXPECTED_IMAGES = 12
EXPECTED_SIZE = (128, 96)
# 工具产物只允许出现在 --output 目录；这些仓库根目录条目运行前后必须不变。
MANAGED_REPO_ENTRIES = ("data", "images", "annotations", "invalid", SUMMARY_NAME)


def load_check_module() -> Any:
    """按文件路径加载工具模块（与 tests/test_tooling.py 的做法一致）。

    工具模块使用 ``dataclass`` + ``from __future__ import annotations``，
    必须先注册到 ``sys.modules``，否则 dataclass 解析字符串注解会失败。
    """
    name = "detection_draft_check"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


@pytest.fixture(scope="module")
def draft_run(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Any, dict, Path, dict[str, bool]]:
    """在临时目录运行一次 CLI，供四个测试共享，保持秒级执行。"""
    root_entries_before = {
        name: (ROOT / name).exists() for name in MANAGED_REPO_ENTRIES
    }
    output = tmp_path_factory.mktemp("detection-draft") / "run"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--output",
            str(output),
            "--images",
            str(EXPECTED_IMAGES),
        ],
        cwd=ROOT,
        capture_output=True,
    )
    stdout = completed.stdout.decode("utf-8")
    assert completed.returncode == 0, (
        f"CLI 退出码 {completed.returncode}："
        + completed.stderr.decode("utf-8", "replace")
    )
    assert not stdout.startswith("\ufeff"), "标准输出必须是不带 BOM 的 UTF-8 JSON"
    summary = json.loads(stdout)
    return completed, summary, output, root_entries_before


# --------------------------------------------------------------------------- #
# 1. 生成与通过
# --------------------------------------------------------------------------- #


def test_cli_generates_images_annotations_and_passes(
    draft_run: tuple[Any, dict, Path, dict[str, bool]],
) -> None:
    completed, summary, output, _root_entries_before = draft_run
    assert completed.returncode == 0
    assert summary["ok"] is True
    assert summary["images"] == EXPECTED_IMAGES
    assert summary["valid_annotations"] == EXPECTED_IMAGES

    image_files = sorted((output / "images").glob("*.png"))
    annotation_files = sorted((output / "annotations").glob("*.json"))
    assert len(image_files) == EXPECTED_IMAGES
    assert len(annotation_files) == EXPECTED_IMAGES

    # 独立用草案 Schema 复核所有标注，而不是只信工具自己的汇总。
    validator = Draft202012Validator(
        json.loads(ANNOTATION_SCHEMA.read_text(encoding="utf-8"))
    )
    for image_path in image_files:
        assert image_path.stat().st_size > 0
        annotation_path = output / "annotations" / f"{image_path.stem}.json"
        assert annotation_path.is_file(), "每张合成图片必须有一个标注 JSON"
        annotation = json.loads(annotation_path.read_text(encoding="utf-8"))
        validator.validate(annotation)
        assert annotation["image"] == f"images/{image_path.name}"
        assert (annotation["width"], annotation["height"]) == EXPECTED_SIZE
        assert annotation["boxes"], "合成标注至少要有一个框"
        for box in annotation["boxes"]:
            assert set(box) == {"class_id", "x", "y", "w", "h"}

    assert summary["rejected_cases"], "必须生成故意无效样例"
    summary_file = output / SUMMARY_NAME
    assert summary_file.is_file(), "工具必须把 JSON 摘要写入输出目录"
    assert json.loads(summary_file.read_text(encoding="utf-8"))["ok"] is True


# --------------------------------------------------------------------------- #
# 2. 无效样例全部被拒绝，边界规则确实被代码捕获
# --------------------------------------------------------------------------- #


def test_invalid_cases_rejected_and_boundary_rules_detected(
    draft_run: tuple[Any, dict, Path, dict[str, bool]],
) -> None:
    _, summary, output, _root_entries_before = draft_run
    cases = summary["rejected_cases"]
    assert summary["invalid_annotations"] == len(cases) >= 8
    assert all(case["rejected"] is True for case in cases)
    assert all(case["ok"] is True for case in cases)
    assert summary["valid_set_violations"] == []
    assert summary["boundary_violations"] >= 5
    assert summary["edge_case_annotations"] >= 1, "必须覆盖贴边框合法边界"

    by_name = {case["name"]: case for case in cases}
    for name in (
        "x-overflow",
        "y-overflow",
        "class-id-out-of-range",
        "width-mismatch",
        "height-mismatch",
        "negative-x",
    ):
        assert name in by_name, f"缺少无效样例 {name}"

    detected_rules = {
        item.get("rule") for case in cases for item in case["violations"]
    }
    for rule in (
        "x + w <= width",
        "y + h <= height",
        "class_id < class_count",
        "image.width == annotation.width",
        "image.height == annotation.height",
        "schema",
    ):
        assert rule in detected_rules, f"无效样例未被 {rule!r} 捕获"
    assert {case["rejected_by"] for case in cases} >= {"schema", "semantic"}

    # 独立调用补充检查函数，直接确认越界被捕获，而不是只信工具自己的汇总。
    module = load_check_module()
    violations = module.semantic_violations(
        {
            "image": "images/case-000.png",
            "width": 128,
            "height": 96,
            "boxes": [{"class_id": 0, "x": 120, "y": 10, "w": 20, "h": 20}],
        },
        output / "images" / "case-000.png",
        len(module.CLASSES),
    )
    assert [item["rule"] for item in violations] == ["x + w <= width"]

    # 右/下边界不包含但可等于：x+w==width、y+h==height 的贴边框不得误报。
    edge_violations = module.semantic_violations(
        {
            "image": "images/case-003.png",
            "width": 128,
            "height": 96,
            "boxes": [{"class_id": 0, "x": 0, "y": 0, "w": 128, "h": 96}],
        },
        output / "images" / "case-003.png",
        len(module.CLASSES),
    )
    assert edge_violations == []


# --------------------------------------------------------------------------- #
# 3. 草案/未激活提示
# --------------------------------------------------------------------------- #


def test_summary_and_docstring_declare_draft_inactive(
    draft_run: tuple[Any, dict, Path, dict[str, bool]],
) -> None:
    _, summary, _, _root_entries_before = draft_run
    assert summary["draft"] is True
    assert summary["activated"] is False
    notes = "\n".join(summary["notes"])
    for phrase in ("草案", "未激活", "检测未实现", "不进入正式课堂数据", "不训练"):
        assert phrase in notes, f"JSON 摘要必须提示 {phrase!r}"
    assert summary["schema_path"] == "schemas/detection/annotation.schema.json"
    assert (ROOT / summary["schema_path"]).is_file()

    docstring = load_check_module().__doc__ or ""
    for phrase in (
        "草案",
        "未激活",
        "草案验证工具，检测未实现/未激活",
        "不进入正式课堂数据",
        "不训练",
    ):
        assert phrase in docstring, f"模块 docstring 必须提示 {phrase!r}"


# --------------------------------------------------------------------------- #
# 4. 只写输出目录，不写仓库 data/ 等位置
# --------------------------------------------------------------------------- #


def test_writes_stay_inside_output_directory(
    draft_run: tuple[Any, dict, Path, dict[str, bool]],
) -> None:
    _, summary, output, root_entries_before = draft_run
    output_root = output.resolve()
    assert Path(summary["output"]).resolve() == output_root
    assert Path(summary["summary_file"]).resolve() == output_root / SUMMARY_NAME

    for case in summary["rejected_cases"]:
        annotation_path = (output_root / case["annotation"]).resolve()
        assert annotation_path.is_file()
        assert annotation_path.is_relative_to(output_root)
    for image_path in (output_root / "images").glob("*.png"):
        assert image_path.resolve().is_relative_to(output_root)

    # 工具产物只能落在 --output 指定的目录里，仓库根目录不得新增同名产物。
    for name, existed_before in root_entries_before.items():
        assert (ROOT / name).exists() == existed_before, (
            f"使用 tmp 输出路径时，工具不得在仓库根目录创建或删除 {name}"
        )

    # 默认输出位于系统临时目录，而不是仓库。
    module = load_check_module()
    assert module.DEFAULT_OUTPUT == Path(tempfile.gettempdir()) / "laitp-detection-draft"

    # 显式把输出指到仓库 data/ 时被拒绝，且不创建目录。
    forbidden = ROOT / "data" / "detection-draft-forbidden"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--output", str(forbidden), "--images", "2"],
        cwd=ROOT,
        capture_output=True,
    )
    payload = json.loads(completed.stdout.decode("utf-8"))
    assert completed.returncode == 1
    assert payload["ok"] is False
    assert payload["code"] == "OUTPUT_PATH_FORBIDDEN"
    assert not forbidden.exists()
