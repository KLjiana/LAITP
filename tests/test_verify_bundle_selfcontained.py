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

def _write_text(root: Path, relative: str, content: str) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def test_development_path_scan_passes_for_clean_bundle(tmp_path: Path) -> None:
    verifier = load_verifier()
    _write_text(tmp_path, "backend/runtime/worker.py", "print('ok')\n")
    _write_text(tmp_path, "start-desktop.bat", "start desktop\\app\\Laitp.Desktop.exe\r\n")

    assert verifier.find_development_path_references(tmp_path) == []


def test_development_path_scan_reports_first_party_reference(tmp_path: Path) -> None:
    verifier = load_verifier()
    _write_text(
        tmp_path, "configs/broken.json", '{"root": "D:\\\\project\\\\Python\\\\LAITP"}\n'
    )

    problems = verifier.find_development_path_references(tmp_path, {"configs/broken.json"})

    assert len(problems) == 1
    assert "configs/broken.json" in problems[0]


def test_development_path_scan_ignores_docs_and_readme(tmp_path: Path) -> None:
    verifier = load_verifier()
    _write_text(tmp_path, "docs/example.md", "示例 C:\\\\Users\\\\KL_jiana\\\\LAITP\n")
    _write_text(tmp_path, "README.md", "示例 /d/project\n")

    assert verifier.find_development_path_references(tmp_path) == []

def test_development_path_scan_ignores_pycache_and_pyc(tmp_path: Path) -> None:
    verifier = load_verifier()
    cache = tmp_path / "backend" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "worker.cpython-312.pyc").write_bytes(
        b"\x00C:\\Users\\KL_jiana\\AppData\\" + b"\x00"
    )

    assert verifier.find_development_path_references(tmp_path) == []

def test_manifest_environment_claims_match_bundle(tmp_path: Path) -> None:
    verifier = load_verifier()
    module = load_verifier()
    _make_desktop(tmp_path, included=True)
    (tmp_path / "python").mkdir()
    (tmp_path / "python" / "python.exe").write_bytes(b"exe")
    manifest = {
        "environment": {
            "platform": "windows-x64",
            "python_embedded": True,
            "desktop_self_contained": True,
        }
    }

    assert module.check_manifest_environment_claims(tmp_path, manifest) == []


def test_manifest_environment_claims_report_python_mismatch(tmp_path: Path) -> None:
    module = load_verifier()
    _make_desktop(tmp_path, included=True)
    manifest = {
        "environment": {
            "platform": "windows-x64",
            "python_embedded": True,
            "desktop_self_contained": True,
        }
    }

    problems = module.check_manifest_environment_claims(tmp_path, manifest)

    assert len(problems) == 1
    assert "python_embedded" in problems[0]


def test_manifest_environment_claims_report_desktop_mismatch(tmp_path: Path) -> None:
    module = load_verifier()
    _make_desktop(tmp_path, included=False)
    manifest = {
        "environment": {
            "platform": "windows-x64",
            "python_embedded": False,
            "desktop_self_contained": True,
        }
    }

    problems = module.check_manifest_environment_claims(tmp_path, manifest)

    assert len(problems) == 1
    assert "desktop_self_contained" in problems[0]

def test_check_bundle_scripts_reports_missing(tmp_path: Path) -> None:
    module = load_verifier()

    problems = module.check_bundle_scripts(tmp_path)

    assert any("preflight_target.py" in problem for problem in problems)


def test_check_bundle_scripts_accepts_present_files(tmp_path: Path) -> None:
    module = load_verifier()
    for relative in module.REQUIRED_BUNDLE_SCRIPTS:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("content", encoding="utf-8")

    assert module.check_bundle_scripts(tmp_path) == []

def test_check_bundle_docs_reports_missing(tmp_path: Path) -> None:
    module = load_verifier()
    (tmp_path / "docs").mkdir()
    (tmp_path / "README.md").write_text("# readme", encoding="utf-8")

    problems = module.check_bundle_docs(tmp_path)

    assert any("docs/acceptance-card.md" in item for item in problems)
    assert any("docs/evidence/README.md" in item for item in problems)


def test_check_bundle_docs_accepts_complete_tree(tmp_path: Path) -> None:
    module = load_verifier()
    for relative in module.REQUIRED_BUNDLE_DOCS:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# doc", encoding="utf-8")

    assert module.check_bundle_docs(tmp_path) == []
