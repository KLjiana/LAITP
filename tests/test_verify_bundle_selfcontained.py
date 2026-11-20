from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_verifier():
    spec = importlib.util.spec_from_file_location(
        "verify_offline_bundle_for_test", ROOT / "scripts/verify_offline_bundle.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_desktop(extracted: Path, included: bool) -> None:
    app = extracted / "desktop" / "app"
    app.mkdir(parents=True)
    if included:
        config = {
            "runtimeOptions": {
                "tfm": "net8.0",
                "includedFrameworks": [
                    {"name": "Microsoft.WindowsDesktop.App", "version": "8.0.34"}
                ],
            }
        }
        for name in ("coreclr.dll", "hostfxr.dll"):
            (app / name).write_bytes(b"runtime")
    else:
        config = {
            "runtimeOptions": {
                "tfm": "net8.0",
                "framework": {"name": "Microsoft.WindowsDesktop.App", "version": "8.0.0"},
            }
        }
    (app / "Laitp.Desktop.runtimeconfig.json").write_text(
        json.dumps(config), encoding="utf-8"
    )


def test_self_contained_desktop_passes(tmp_path: Path) -> None:
    verifier = load_verifier()
    _make_desktop(tmp_path, included=True)
    assert verifier.check_desktop_self_contained(tmp_path) == []


def test_framework_dependent_desktop_is_reported(tmp_path: Path) -> None:
    verifier = load_verifier()
    _make_desktop(tmp_path, included=False)
    problems = verifier.check_desktop_self_contained(tmp_path)
    assert len(problems) == 3
    assert any("不是自包含发布" in item for item in problems)
    assert any("coreclr.dll" in item for item in problems)
    assert any("hostfxr.dll" in item for item in problems)


def test_missing_runtime_files_are_reported(tmp_path: Path) -> None:
    verifier = load_verifier()
    _make_desktop(tmp_path, included=True)
    (tmp_path / "desktop" / "app" / "coreclr.dll").unlink()
    problems = verifier.check_desktop_self_contained(tmp_path)
    assert problems == ["桌面程序缺少运行时文件：desktop/app/coreclr.dll"]


def test_missing_runtimeconfig_is_reported(tmp_path: Path) -> None:
    verifier = load_verifier()
    problems = verifier.check_desktop_self_contained(tmp_path)
    assert problems and "缺少桌面运行时配置" in problems[0]


def test_start_script_points_to_packaged_desktop(tmp_path: Path) -> None:
    verifier = load_verifier()
    script = tmp_path / "start-desktop.bat"
    script.write_text(
        "@echo off\r\n"
        'cd /d "%~dp0"\r\n'
        'start "" desktop\\app\\Laitp.Desktop.exe\r\n',
        encoding="utf-8",
    )
    assert verifier.check_start_script(tmp_path) == []


def test_start_script_pointing_to_bin_is_reported(tmp_path: Path) -> None:
    verifier = load_verifier()
    script = tmp_path / "start-desktop.bat"
    script.write_text(
        "start desktop\\src\\Laitp.Desktop\\bin\\Debug\\Laitp.Desktop.exe\r\n",
        encoding="utf-8",
    )
    problems = verifier.check_start_script(tmp_path)
    assert len(problems) == 2
    assert any("未指向包内" in item for item in problems)
    assert any("bin" in item for item in problems)


def test_missing_start_script_is_reported(tmp_path: Path) -> None:
    verifier = load_verifier()
    assert verifier.check_start_script(tmp_path) == ["缺少启动脚本：start-desktop.bat"]
