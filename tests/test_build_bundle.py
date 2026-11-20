from __future__ import annotations

import importlib.util
import json
import shutil as real_shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_builder():
    spec = importlib.util.spec_from_file_location(
        "build_offline_bundle_for_test", ROOT / "scripts/build_offline_bundle.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sanitize_demo_run_rewrites_absolute_paths(tmp_path: Path) -> None:
    builder = load_builder()
    run_dir = tmp_path / "demo" / "run"
    run_dir.mkdir(parents=True)
    config = {
        "run_id": "demo",
        "dataset_manifest": r"D:\project\Python\LAITP\data\dataset-manifest.json",
        "dataset_root": r"D:\project\Python\LAITP\data",
        "weights": {"path": r"D:\project\Python\LAITP\weights.pth", "id": "w"},
    }
    (run_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
    artifact = {
        "files": {
            "config.json": {"sha256": "0" * 64, "size_bytes": 1},
            "model.pt": {"sha256": "1" * 64, "size_bytes": 2},
        }
    }
    (run_dir / "training-artifact.json").write_text(
        json.dumps(artifact), encoding="utf-8"
    )

    builder.sanitize_demo_run(run_dir)

    rewritten = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    assert rewritten["dataset_manifest"] == "demo/run/dataset-manifest.json"
    assert rewritten["dataset_root"] == "demo/run/data"
    assert rewritten["weights"]["path"] == "demo/run/weights-not-bundled.pth"
    assert rewritten["weights"]["id"] == "w"
    assert "D:\\project" not in (run_dir / "config.json").read_text(encoding="utf-8")
    updated_artifact = json.loads(
        (run_dir / "training-artifact.json").read_text(encoding="utf-8")
    )
    assert updated_artifact["files"]["config.json"]["sha256"] == builder.sha256_file(
        run_dir / "config.json"
    )
    assert updated_artifact["files"]["config.json"]["size_bytes"] == (
        run_dir / "config.json"
    ).stat().st_size
    assert updated_artifact["files"]["model.pt"]["sha256"] == "1" * 64


def test_sanitize_demo_run_is_noop_without_config(tmp_path: Path) -> None:
    builder = load_builder()
    run_dir = tmp_path / "demo" / "run"
    run_dir.mkdir(parents=True)
    builder.sanitize_demo_run(run_dir)
    assert not (run_dir / "config.json").exists()


def test_add_tree_excludes_pycache_and_pyc(tmp_path: Path) -> None:
    builder = load_builder()
    builder.ROOT = tmp_path
    source = tmp_path / "src"
    cache = source / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "module.pyc").write_bytes(b"cache")
    (source / "module.py").write_text("value = 1\n", encoding="utf-8")
    staging = tmp_path / "staging"
    staging.mkdir()
    components: list[dict] = []

    builder.add_tree(staging, source, "pkg", components)

    names = sorted(path.name for path in (staging / "pkg").rglob("*") if path.is_file())
    assert names == ["module.py"]
    listed = [item["path"] for item in components[0]["files"]]
    assert listed == ["pkg/module.py"]


def test_add_tree_hashes_after_post_copy(tmp_path: Path) -> None:
    builder = load_builder()
    builder.ROOT = tmp_path
    source = tmp_path / "src"
    source.mkdir()
    (source / "config.json").write_text("old", encoding="utf-8")
    staging = tmp_path / "staging"
    staging.mkdir()
    components: list[dict] = []

    def rewrite(destination: Path) -> None:
        (destination / "config.json").write_text("new-content", encoding="utf-8")

    builder.add_tree(staging, source, "run", components, post_copy=rewrite)

    listed = components[0]["files"][0]
    assert listed["size"] == len("new-content")
    assert listed["sha256"] == builder.sha256_file(staging / "run" / "config.json")


def test_add_tree_retries_transient_copy_errors(tmp_path: Path) -> None:
    builder = load_builder()
    builder.ROOT = tmp_path
    builder.TREE_COPY_RETRY_DELAY_SECONDS = 0
    source = tmp_path / "src"
    source.mkdir()
    (source / "a.txt").write_text("data", encoding="utf-8")
    staging = tmp_path / "staging"
    staging.mkdir()
    calls = {"count": 0}
    original = builder.shutil.copytree

    def flaky(src, dst, **kwargs):
        calls["count"] += 1
        if calls["count"] < 3:
            Path(dst).mkdir(parents=True, exist_ok=True)
            raise FileNotFoundError("transient lock")
        original(src, dst, **kwargs)

    builder.shutil.copytree = flaky
    try:
        builder.add_tree(staging, source, "pkg", [])
    finally:
        builder.shutil.copytree = original

    assert calls["count"] == 3
    assert (staging / "pkg" / "a.txt").read_text(encoding="utf-8") == "data"

def test_write_batch_script_uses_single_crlf(tmp_path: Path) -> None:
    builder = load_builder()
    target = tmp_path / "run.bat"
    builder.write_batch_script(target, "@echo off\r\nchcp 65001 >nul\r\npause\r\n")
    raw = target.read_bytes()
    assert b"\r\r\n" not in raw
    assert raw.count(b"\r\n") == 3
    assert raw.startswith(b"@echo off\r\n")
