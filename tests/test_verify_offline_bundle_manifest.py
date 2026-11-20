"""verify_offline_bundle.py 清单卫生校验测试。

历史缺陷：旧打包把 backend/__pycache__/*.pyc 计入清单，包内自检时 Python
重写缓存会导致清单摘要不幂等。这里只测纯函数
find_manifest_hygiene_issues，不实际解包或运行推理。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_verifier():
    spec = importlib.util.spec_from_file_location(
        "verify_offline_bundle_for_test",
        ROOT / "scripts/verify_offline_bundle.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_clean_manifest_has_no_hygiene_issues() -> None:
    verifier = load_verifier()
    files = [
        "backend/app.py",
        "backend/classification/service.py",
        "python/python.exe",
        "python/Lib/site-packages/torch/__init__.py",
        "docs/offline-bundle.md",
    ]
    assert verifier.find_manifest_hygiene_issues(files) == []


def test_pycache_and_pyc_are_reported() -> None:
    verifier = load_verifier()
    dirty = "backend/__pycache__/worker.cpython-312.pyc"
    issues = verifier.find_manifest_hygiene_issues(["backend/app.py", dirty])
    assert issues == [f"清单包含缓存/编译产物：{dirty}"]


def test_pyo_and_pycache_directory_are_reported() -> None:
    verifier = load_verifier()
    dirty = ["abc.pyo", "inner/__pycache__/a"]
    issues = verifier.find_manifest_hygiene_issues(["backend/app.py", *dirty])
    assert issues == [f"清单包含缓存/编译产物：{path}" for path in dirty]


def test_matching_is_case_insensitive() -> None:
    verifier = load_verifier()
    dirty = ["backend/__PYCACHE__/a.pyc", "lib/module.PYC", "lib/other.PYO"]
    issues = verifier.find_manifest_hygiene_issues(dirty)
    assert issues == [f"清单包含缓存/编译产物：{path}" for path in dirty]
