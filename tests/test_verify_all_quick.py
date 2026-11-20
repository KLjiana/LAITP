"""verify_all.py 快速验证模式测试：步骤计划、输出目录与报告标记。

不实际运行完整验证或耗时步骤，只针对可纯函数化的计划与报告逻辑断言。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_verify_all():
    spec = importlib.util.spec_from_file_location(
        "verify_all", ROOT / "scripts/verify_all.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_quick_step_names_contains_expected_steps() -> None:
    module = load_verify_all()
    assert module.quick_step_names() == [
        "Python 单元测试",
        "桌面构建",
        "Core 检查",
        "验收证据汇总",
        "文档一致性",
        "交付状态自检",
    ]


def test_quick_step_names_excludes_slow_and_ui_steps() -> None:
    module = load_verify_all()
    names = module.quick_step_names()
    assert len(names) == 6
    joined = "".join(names)
    for keyword in ("离线包", "离线流程", "净环境", "课堂演练", "界面", "摄像头"):
        assert keyword not in joined, f"快速模式不应包含：{keyword}"


def test_quick_default_output_dir() -> None:
    module = load_verify_all()
    assert (
        module.resolve_output_dir(None, quick=True)
        == module.ROOT / "artifacts/verify-quick"
    )
    assert (
        module.resolve_output_dir(None, quick=False)
        == module.ROOT / "artifacts/verify-all"
    )


def test_quick_output_dir_respects_explicit_output() -> None:
    module = load_verify_all()
    assert (
        module.resolve_output_dir("artifacts/custom-verify", quick=True)
        == module.ROOT / "artifacts/custom-verify"
    )


def test_quick_report_marks_quick_true(tmp_path: Path) -> None:
    module = load_verify_all()
    runner = module.Runner()
    runner.record("Python 单元测试", "pass", "成功", 0.1)
    runner.skip("界面自动化", "跳过：--quick 快速模式优先，忽略 --ui")
    summary = module.write_report(runner, tmp_path, "verify-quick", quick=True)

    assert summary["ok"] is True
    payload = json.loads((tmp_path / "verify-quick.json").read_text(encoding="utf-8"))
    assert payload["quick"] is True
    assert payload["ok"] is True
    assert [step["name"] for step in payload["steps"]] == ["Python 单元测试", "界面自动化"]
    assert (tmp_path / "verify-quick.txt").is_file()


def test_quick_mode_ignores_ui_and_camera(tmp_path: Path, capsys) -> None:
    """--quick 与 --ui/--camera 同传时快速模式优先：替换执行函数，只验证冲突处理与报告。"""
    module = load_verify_all()
    module.run_quick = lambda runner: runner.skip("Python 单元测试", "测试桩")
    code = module.main(["--quick", "--ui", "--camera", "--output", str(tmp_path)])
    capsys.readouterr()

    assert code == 0
    payload = json.loads((tmp_path / "verify-quick.json").read_text(encoding="utf-8"))
    assert payload["quick"] is True
    steps = payload["steps"]
    assert [step["name"] for step in steps] == [
        "界面自动化",
        "界面摄像头拍照导入",
        "Python 单元测试",
    ]
    assert "忽略 --ui" in steps[0]["detail"]
    assert "忽略 --camera" in steps[1]["detail"]
