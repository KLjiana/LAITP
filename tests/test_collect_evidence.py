from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_collector():
    spec = importlib.util.spec_from_file_location(
        "collect_evidence", ROOT / "scripts" / "collect_evidence.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_collect_evidence_skips_missing_and_packs_present(tmp_path: Path) -> None:
    module = load_collector()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "acceptance-run.json").write_text('{"ok": true}', encoding="utf-8")
    (tmp_path / "acceptance-report.md").write_text("# report", encoding="utf-8")
    output = tmp_path / "bundle.zip"

    manifest = module.build_evidence_zip(tmp_path, output)

    assert {item["path"] for item in manifest["files"]} == {
        "artifacts/acceptance-run.json",
        "acceptance-report.md",
    }
    assert "artifacts/preflight-target.json" in manifest["missing"]
    with zipfile.ZipFile(output) as archive:
        assert "evidence-manifest.json" in archive.namelist()
        payload = json.loads(archive.read("evidence-manifest.json").decode("utf-8"))
    assert payload["format"] == "laitp-acceptance-evidence-1.0"


def test_collect_evidence_hash_matches_bytes(tmp_path: Path) -> None:
    module = load_collector()
    (tmp_path / "acceptance-report.md").write_text("hello", encoding="utf-8")

    manifest = module.build_evidence_zip(tmp_path, tmp_path / "bundle.zip")

    entry = next(item for item in manifest["files"] if item["path"] == "acceptance-report.md")
    assert entry["bytes"] == 5
    assert entry["sha256"] == module.sha256_bytes(b"hello")


def test_collect_evidence_requires_at_least_one_file(tmp_path: Path) -> None:
    module = load_collector()
    try:
        module.build_evidence_zip(tmp_path, tmp_path / "bundle.zip")
    except SystemExit as exc:
        assert "未找到任何可收集的验收产物" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("空目录应当被拒绝")
