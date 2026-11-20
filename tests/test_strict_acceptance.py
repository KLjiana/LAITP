"""严格验收数据检查（``check-dataset``）命令行测试。

界面严格验收与数据检查都调用同一入口。本文件用最小项目验证：阈值恰好达标
时通过并回显策略；低于阈值、缺少独立测试集时拒绝；阈值按类别而不是按总量
判定。全部使用 ``tmp_path`` 构造，单个用例在秒级完成。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.project.cli import main
from backend.project.dataset import rebuild_dataset
from backend.project.project import create_project
from tests.support.images import build_dataset_tree, make_image

CLASSES = ("水杯", "书本")
CREATED_AT = "2026-11-17T10:00:00+08:00"
# 每个类别 train 2 / val 2 / test 2 时的严格验收参数。
STRICT_ARGS = ("--require-test", "--min-train", "2", "--min-val", "2", "--min-test", "2")


def build_project(tmp_path: Path, *, with_test_split: bool = True) -> Path:
    """建 2 类项目：每类 2 个采集批次（分成 train/val），可选独立 test 划分。"""
    root = tmp_path / "严格验收 项目"
    create_project(
        root,
        project_id="proj-strict-0001",
        name="严格验收项目",
        classes=CLASSES,
        created_at=CREATED_AT,
    )
    build_dataset_tree(
        root / "data",
        classes=CLASSES,
        train_batches=2,
        images_per_batch=2,
        test_batches=1 if with_test_split else 0,
        test_images_per_batch=2,
    )
    rebuild_dataset(root, dataset_id="ds-strict-0001")
    return root


def run_check(
    root: Path, capsys: pytest.CaptureFixture[str], *args: str
) -> tuple[int, dict]:
    """调用 CLI 入口并解析 stdout 的 UTF-8 JSON，与界面调用方式一致。"""
    exit_code = main(["check-dataset", "--root", str(root), *args])
    return exit_code, json.loads(capsys.readouterr().out)


def pad_class(root: Path, class_name: str, *, extra: int = 2) -> None:
    """给某类别每个采集批次追加图片，使其各划分计数高于其他类别。"""
    index = 0
    for split_dir in ("images", "test-images"):
        base = root / "data" / split_dir / class_name
        for batch_dir in sorted(path for path in base.iterdir() if path.is_dir()):
            for _ in range(extra):
                make_image(
                    batch_dir / f"extra-{index:02d}.png",
                    (200, 20 + index, 30),
                )
                index += 1


def test_strict_acceptance_passes_at_exact_minimums(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = build_project(tmp_path)

    exit_code, payload = run_check(root, capsys, *STRICT_ARGS)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["issues"] == []
    assert payload["counts"]["by_class"] == [
        {"class_id": index, "name": name, "train": 2, "val": 2, "test": 2}
        for index, name in enumerate(CLASSES)
    ]
    assert payload["counts"]["splits"] == {"train": 4, "val": 4, "test": 4}
    assert payload["policy"] == {
        "require_test_split": True,
        "min_train_per_class": 2,
        "min_val_per_class": 2,
        "min_test_per_class": 2,
    }
    assert Path(payload["manifest_path"]).is_file()


def test_strict_acceptance_rejects_too_few_train_samples(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = build_project(tmp_path)

    exit_code, payload = run_check(
        root,
        capsys,
        "--require-test",
        "--min-train",
        "3",
        "--min-val",
        "2",
        "--min-test",
        "2",
    )

    assert exit_code == 1
    assert payload["ok"] is False
    # 只提高训练阈值：两个类别的 train 各 2 张，各报一条。
    assert [issue["code"] for issue in payload["issues"]] == [
        "DATASET_CLASS_TOO_FEW_SAMPLES",
        "DATASET_CLASS_TOO_FEW_SAMPLES",
    ]
    assert [issue["location"] for issue in payload["issues"]] == [
        "classes[0]",
        "classes[1]",
    ]
    assert {issue["stage"] for issue in payload["issues"]} == {"semantics"}
    assert all("train" in issue["message"] for issue in payload["issues"])
    assert all("至少需要 3 张" in issue["message"] for issue in payload["issues"])
    assert payload["policy"]["min_train_per_class"] == 3
    assert payload["counts"]["splits"]["train"] == 4


def test_strict_acceptance_requires_independent_test_split(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # 现有 test_project_check.py 在函数层验证过该错误码；这里补 CLI 入口的
    # JSON 契约（退出码、code/stage/location、策略回显）。
    root = build_project(tmp_path, with_test_split=False)

    exit_code, payload = run_check(root, capsys, *STRICT_ARGS)

    assert exit_code == 1
    assert payload["ok"] is False
    assert [issue["code"] for issue in payload["issues"]] == [
        "DATASET_TEST_SPLIT_MISSING"
    ]
    issue = payload["issues"][0]
    assert issue["stage"] == "semantics"
    assert issue["location"] == "samples"
    assert issue["message"]
    assert payload["counts"]["splits"]["test"] == 0
    assert payload["policy"]["require_test_split"] is True
    assert payload["policy"]["min_test_per_class"] == 2


def test_strict_acceptance_checks_each_class_not_just_totals(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = build_project(tmp_path)
    pad_class(root, CLASSES[1])
    rebuild_dataset(root, dataset_id="ds-strict-0002")

    exit_code, payload = run_check(
        root,
        capsys,
        "--require-test",
        "--min-train",
        "3",
        "--min-val",
        "3",
        "--min-test",
        "3",
    )

    assert exit_code == 1
    assert payload["ok"] is False
    by_class = {row["name"]: row for row in payload["counts"]["by_class"]}
    assert by_class[CLASSES[0]] == {
        "class_id": 0,
        "name": CLASSES[0],
        "train": 2,
        "val": 2,
        "test": 2,
    }
    assert by_class[CLASSES[1]] == {
        "class_id": 1,
        "name": CLASSES[1],
        "train": 4,
        "val": 4,
        "test": 4,
    }
    # 总量 6/6/6 已达到 2 类 × 3 张，但类别 0 不足，不能只按总量判定。
    assert payload["counts"]["splits"] == {"train": 6, "val": 6, "test": 6}
    assert [issue["location"] for issue in payload["issues"]] == [
        "classes[0]",
        "classes[0]",
        "classes[0]",
    ]
    assert {issue["code"] for issue in payload["issues"]} == {
        "DATASET_CLASS_TOO_FEW_SAMPLES"
    }
    messages = [issue["message"] for issue in payload["issues"]]
    assert "train" in messages[0] and "val" in messages[1] and "test" in messages[2]
