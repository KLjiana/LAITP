"""交接目录与离线打包脚本的回归测试。

覆盖最近新增的“根 README.md 进入交接目录 / 离线包并登记清单”的行为：
- ``scripts/make_handoff.py``：复制 README.md、写入 handoff-manifest.json 的 documents；
- ``scripts/build_offline_bundle.py``：``add_file`` 把 README.md 加入 components。

测试通过 importlib 加载脚本模块并 monkeypatch 模块级 ``ROOT`` 指向临时目录，
避免读写仓库真实路径，也不修改生产脚本。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

README_TEXT = "# 临时 README\n\n交接测试用的项目说明。\n"
COPY_DOCS = (
    "teacher-quickstart.md",
    "acceptance-checklist.md",
    "verification-evidence.md",
)


def load_script(module_name: str, script: str):
    """按文件路径加载 scripts/ 下的脚本模块（不注册到 sys.modules）。"""
    path = ROOT / "scripts" / script
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_zip(path: Path, marker: bytes) -> Path:
    """写一个内容任意的假离线包。"""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("laitp/marker.txt", marker)
    return path


def prepare_repository(tmp_path: Path) -> None:
    """在临时目录模拟仓库根：README.md 与 make_handoff 需要的 docs 文件。"""
    (tmp_path / "README.md").write_text(README_TEXT, encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    for name in COPY_DOCS:
        (docs / name).write_text(f"# {name}\n\n临时文档。\n", encoding="utf-8")


def test_make_handoff_copies_readme_and_records_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_repository(tmp_path)
    lean = make_zip(tmp_path / "laitp-offline-lean.zip", b"lean-bundle")
    full = make_zip(tmp_path / "laitp-offline-full.zip", b"full-bundle")
    output = tmp_path / "handoff"

    module = load_script("laitp_test_make_handoff", "make_handoff.py")
    monkeypatch.setattr(module, "ROOT", tmp_path)

    exit_code = module.main(
        [
            "--zip",
            str(lean),
            "--full-zip",
            str(full),
            "--output",
            str(output),
            "--clean",
            "--include-full",
        ]
    )
    assert exit_code == 0

    # README.md 被复制到交接目录，内容与仓库根 README 一致。
    handoff_readme = output / "README.md"
    assert handoff_readme.is_file()
    assert handoff_readme.read_text(encoding="utf-8") == README_TEXT

    # 清单 documents 登记 README.md，且 SHA-256 与交接目录中的文件一致。
    manifest = json.loads(
        (output / "handoff-manifest.json").read_text(encoding="utf-8")
    )
    documents = {item["name"]: item for item in manifest["documents"]}
    assert "README.md" in documents
    assert documents["README.md"]["sha256"] == sha256(handoff_readme)
    assert documents["README.md"]["size"] == handoff_readme.stat().st_size

    # 交接说明列出 README.md。
    guide = (output / "交接说明.txt").read_text(encoding="utf-8")
    assert "README.md" in guide

    # 附带的完整包也应被复制并登记（--include-full）。
    assert (output / full.name).read_bytes() == full.read_bytes()
    assert manifest["bundle_full"]["sha256"] == sha256(full)


def test_make_handoff_missing_zip_returns_error_without_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_repository(tmp_path)
    output = tmp_path / "handoff"

    module = load_script("laitp_test_make_handoff_missing", "make_handoff.py")
    monkeypatch.setattr(module, "ROOT", tmp_path)

    exit_code = module.main(
        [
            "--zip",
            str(tmp_path / "missing.zip"),
            "--output",
            str(output),
        ]
    )
    assert exit_code == 1
    assert not output.exists()


def test_build_offline_bundle_add_file_includes_readme(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_repository(tmp_path)
    staging = tmp_path / "staging"
    staging.mkdir()
    components: list[dict] = []

    module = load_script("laitp_test_build_offline_bundle", "build_offline_bundle.py")
    # add_file 用 source.relative_to(ROOT) 记录来源；把 ROOT 指向临时目录即可。
    monkeypatch.setattr(module, "ROOT", tmp_path)

    module.add_file(staging, tmp_path / "README.md", "README.md", components)

    staged_readme = staging / "README.md"
    assert staged_readme.is_file()
    assert staged_readme.read_text(encoding="utf-8") == README_TEXT

    assert len(components) == 1
    component = components[0]
    assert component["name"] == "README.md"
    assert component["source"] == "README.md"
    assert component["bytes"] == staged_readme.stat().st_size
    assert component["files"] == [
        {
            "path": "README.md",
            "size": staged_readme.stat().st_size,
            "sha256": sha256(staged_readme),
        }
    ]
