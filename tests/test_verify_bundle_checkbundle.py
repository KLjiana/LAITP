"""check-bundle.bat 一键自检脚本校验测试。

目标机双击 check-bundle.bat 是现场自检入口：脚本必须切换 UTF-8 代码页、使用
包内 Python 与相对路径调用 verify_offline_bundle.py --extracted .。构建或手工
替换若破坏内容，双击会静默失败，因此这里只测纯函数 check_check_bundle_script。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

GOOD_CONTENT = (
    "@echo off\r\n"
    "chcp 65001 >nul\r\n"
    'cd /d "%~dp0"\r\n'
    "python\\python.exe scripts\\verify_offline_bundle.py --extracted .\r\n"
    "echo.\r\n"
    "pause\r\n"
)


def load_verifier():
    spec = importlib.util.spec_from_file_location(
        "verify_offline_bundle_checkbundle_test",
        ROOT / "scripts/verify_offline_bundle.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_script(tmp_path: Path, content: str) -> None:
    (tmp_path / "check-bundle.bat").write_text(content, encoding="utf-8")


def test_correct_check_bundle_script_passes(tmp_path: Path) -> None:
    verifier = load_verifier()
    write_script(tmp_path, GOOD_CONTENT)
    assert verifier.check_check_bundle_script(tmp_path) == []
    # 大小写不敏感、正反斜杠归一化：大写与正斜杠写法同样视为正确。
    write_script(
        tmp_path,
        "@echo off\r\n"
        "CHCP 65001 >NUL\r\n"
        'CD /D "%~DP0"\r\n'
        "PYTHON/PYTHON.EXE SCRIPTS/VERIFY_OFFLINE_BUNDLE.PY --EXTRACTED .\r\n",
    )
    assert verifier.check_check_bundle_script(tmp_path) == []


def test_missing_python_script_and_arguments_are_reported(tmp_path: Path) -> None:
    verifier = load_verifier()
    write_script(
        tmp_path,
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        'cd /d "%~dp0"\r\n'
        "echo done\r\n",
    )
    problems = verifier.check_check_bundle_script(tmp_path)
    assert len(problems) == 3
    assert any("python\\python.exe" in item for item in problems)
    assert any("scripts\\verify_offline_bundle.py" in item for item in problems)
    assert any("--extracted" in item for item in problems)


def test_missing_chcp_is_reported(tmp_path: Path) -> None:
    verifier = load_verifier()
    write_script(
        tmp_path,
        "@echo off\r\n"
        'cd /d "%~dp0"\r\n'
        "python\\python.exe scripts\\verify_offline_bundle.py --extracted .\r\n",
    )
    problems = verifier.check_check_bundle_script(tmp_path)
    assert problems == ["check-bundle.bat 未切换 UTF-8 代码页：缺少 chcp 65001"]


def test_development_absolute_path_is_reported(tmp_path: Path) -> None:
    verifier = load_verifier()
    write_script(
        tmp_path,
        GOOD_CONTENT + 'set "LAITP_HOME=D:/project/Python/LAITP"\r\n',
    )
    problems = verifier.check_check_bundle_script(tmp_path)
    assert len(problems) == 1
    assert "D:\\project" in problems[0]


def test_missing_check_bundle_script_is_reported(tmp_path: Path) -> None:
    verifier = load_verifier()
    assert verifier.check_check_bundle_script(tmp_path) == [
        "缺少自检脚本：check-bundle.bat"
    ]
