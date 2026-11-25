from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_preflight():
    spec = importlib.util.spec_from_file_location(
        "preflight_target", ROOT / "scripts" / "preflight_target.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_platform_check_blocks_non_windows() -> None:
    module = load_preflight()

    checks = module.check_platform("Linux", "x86_64", admin=False)

    assert checks[0]["status"] == "blocker"
    assert checks[1]["status"] == "pass"


def test_platform_check_warns_admin() -> None:
    module = load_preflight()

    checks = module.check_platform("Windows", "AMD64", admin=True)

    statuses = {item["id"]: item["status"] for item in checks}
    assert statuses["platform"] == "pass"
    assert statuses["privilege"] == "warn"


def test_path_length_thresholds() -> None:
    module = load_preflight()

    short = module.check_path_length(Path("D:/laitp"))
    medium = module.check_path_length(Path("D:/" + "a" * module.WARN_ROOT_PATH_LENGTH))
    long = module.check_path_length(Path("D:/" + "a" * module.MAX_ROOT_PATH_LENGTH))

    assert short["status"] == "pass"
    assert medium["status"] == "warn"
    assert long["status"] == "blocker"


def test_disk_free_thresholds() -> None:
    module = load_preflight()

    assert module.check_disk_free(4 * 1024**3)["status"] == "pass"
    assert module.check_disk_free(1536 * 1024**2)["status"] == "warn"
    assert module.check_disk_free(512 * 1024**2)["status"] == "blocker"


def test_bundle_sha_mismatch_blocks(tmp_path: Path) -> None:
    module = load_preflight()
    zip_path = tmp_path / "bundle.zip"
    zip_path.write_bytes(b"payload")
    expected = "0" * 64

    result = module.check_bundle_sha(zip_path, expected)

    assert result["status"] == "blocker"

def test_memory_thresholds() -> None:
    module = load_preflight()

    assert module.check_memory(8 * 1024**3)["status"] == "pass"
    assert module.check_memory(3 * 1024**3)["status"] == "warn"
    assert module.check_memory(1536 * 1024**2)["status"] == "blocker"
