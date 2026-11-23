"""工具脚本回归测试：交接目录生成与验收证据汇总。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


def run_script(arguments: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, *arguments],
        cwd=ROOT,
        capture_output=True,
    )


def test_make_handoff_creates_directory_and_manifest(tmp_path: Path) -> None:
    dummy = tmp_path / "bundle.zip"
    dummy.write_bytes(b"laitp-bundle-dummy")
    output = tmp_path / "handoff"
    completed = run_script(
        [
            "scripts/make_handoff.py",
            "--zip",
            str(dummy),
            "--output",
            str(output),
        ]
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
    assert (output / "bundle.zip").read_bytes() == dummy.read_bytes()

    digest = hashlib.sha256(dummy.read_bytes()).hexdigest()
    sha_line = (output / "bundle.zip.sha256").read_text(encoding="utf-8").split()
    assert sha_line[0] == digest
    manifest = json.loads(
        (output / "handoff-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["bundle"]["sha256"] == digest
    assert manifest["bundle"]["size"] == len(dummy.read_bytes())
    assert (output / "交接说明.txt").is_file()
    assert (output / "teacher-quickstart.md").is_file()

    summary = json.loads(completed.stdout.decode("utf-8"))
    assert summary["ok"] is True
    assert summary["sha256"] == digest


def test_make_handoff_rejects_missing_bundle(tmp_path: Path) -> None:
    completed = run_script(
        [
            "scripts/make_handoff.py",
            "--zip",
            str(tmp_path / "missing.zip"),
            "--output",
            str(tmp_path / "handoff"),
        ]
    )
    assert completed.returncode == 1
    payload = json.loads(completed.stdout.decode("utf-8"))
    assert payload["ok"] is False
    assert "不存在" in payload["error"]


def test_acceptance_audit_without_artifacts(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location(
        "acceptance_audit", ROOT / "scripts/acceptance_audit.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ARTIFACTS = tmp_path / "artifacts"

    assert module.main() == 0
    payload = json.loads(
        (tmp_path / "artifacts/acceptance-local.json").read_text(encoding="utf-8")
    )
    assert len(payload["items"]) == 15
    assert payload["summary"]["blocked"] == 1
    # 无产物时 A10（课堂数据）与 A12（断网模拟）均为未执行。
    assert payload["summary"]["not_run"] == 2
    assert (tmp_path / "artifacts/acceptance-local.md").is_file()

def test_check_docs_finds_broken_links(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location(
        "check_docs", ROOT / "scripts/check_docs.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "target.md").write_text("# target", encoding="utf-8")
    (docs / "good.md").write_text(
        "[ok](target.md) [anchor](#section) [web](https://example.com)",
        encoding="utf-8",
    )
    (docs / "bad.md").write_text(
        "[missing](missing.md) [partial](target.md#x)", encoding="utf-8"
    )
    assert module.find_broken_links(docs) == ["bad.md -> missing.md"]

def test_check_docs_checks_readme_links(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location(
        "check_docs_readme", ROOT / "scripts/check_docs.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "target.md").write_text("# target", encoding="utf-8")
    readme = tmp_path / "README.md"
    readme.write_text(
        "[ok](docs/target.md) [bad](docs/missing.md)", encoding="utf-8"
    )
    assert module.find_broken_links_in([readme]) == ["README.md -> docs/missing.md"]


def load_check_docs(module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        module_name, ROOT / "scripts/check_docs.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_check_docs_generates_github_heading_slugs() -> None:
    module = load_check_docs("check_docs_heading_slugs")

    text = (
        "## 3.6 可移植性与绝对路径扫描（2026-11-19）\n"
        "## 重复标题\n"
        "## 重复标题\n"
        "## 重复标题\n"
        "## **粗体** 与 `代码`\n"
        "```\n"
        "# 代码块内的注释不是标题\n"
        "```\n"
    )
    assert module.heading_slugs(text) == [
        "36-可移植性与绝对路径扫描2026-11-19",
        "重复标题",
        "重复标题-1",
        "重复标题-2",
        "粗体-与-代码",
    ]


def test_check_docs_accepts_valid_anchors(tmp_path: Path) -> None:
    module = load_check_docs("check_docs_anchors_valid")

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "target.md").write_text(
        "# 目标文档\n## 3.6 可移植性（2026-11-19）\n", encoding="utf-8"
    )
    (docs / "source.md").write_text(
        "[ok](target.md#36-可移植性2026-11-19) [top](target.md#目标文档)\n",
        encoding="utf-8",
    )
    assert module.find_broken_anchors(sorted(docs.glob("*.md"))) == []


def test_check_docs_reports_broken_anchors(tmp_path: Path) -> None:
    module = load_check_docs("check_docs_anchors_broken")

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "target.md").write_text("# 目标文档\n", encoding="utf-8")
    (docs / "source.md").write_text(
        "[bad](target.md#已失效的章节) [ok](target.md#目标文档)", encoding="utf-8"
    )
    assert module.find_broken_anchors([docs / "source.md"]) == [
        "source.md -> target.md#已失效的章节"
    ]


def test_check_docs_checks_same_file_anchors(tmp_path: Path) -> None:
    module = load_check_docs("check_docs_anchors_same_file")

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "page.md").write_text(
        "## 本文件章节\n[ok](#本文件章节) [bad](#遗失章节)\n",
        encoding="utf-8",
    )
    assert module.find_broken_anchors([docs / "page.md"]) == [
        "page.md -> #遗失章节"
    ]


def test_check_docs_skips_external_and_missing_anchor_targets(tmp_path: Path) -> None:
    module = load_check_docs("check_docs_anchors_skip")

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "target.md").write_text("# 目标文档\n", encoding="utf-8")
    (docs / "source.md").write_text(
        "[web](https://example.com#foo) [mail](mailto:teacher@example.com#bar) "
        "[missing](missing.md#nope) [empty](#)\n",
        encoding="utf-8",
    )
    assert module.find_broken_anchors(sorted(docs.glob("*.md"))) == []

def test_check_docs_accepts_matching_third_party_notices(tmp_path: Path) -> None:
    module = load_check_docs("check_docs_notices_ok")
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(
        "torch==2.8.0+cpu\njsonschema==4.25.1\n", encoding="utf-8"
    )
    notices = tmp_path / "third-party-notices.md"
    notices.write_text(
        "| 组件 | 版本 | 许可证 |\n"
        "| --- | --- | --- |\n"
        "| torch | 2.8.0+cpu | BSD-3-Clause |\n"
        "| jsonschema | 4.25.1 | MIT |\n",
        encoding="utf-8",
    )

    assert module.find_dependency_notice_issues([requirements], notices) == []


def test_check_docs_reports_missing_third_party_notice(tmp_path: Path) -> None:
    module = load_check_docs("check_docs_notices_missing")
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("onnxruntime==1.23.2\n", encoding="utf-8")
    notices = tmp_path / "third-party-notices.md"
    notices.write_text("| torch | 2.8.0+cpu | BSD-3-Clause |\n", encoding="utf-8")

    issues = module.find_dependency_notice_issues([requirements], notices)

    assert len(issues) == 1
    assert "onnxruntime" in issues[0]


def test_check_docs_reports_third_party_version_mismatch(tmp_path: Path) -> None:
    module = load_check_docs("check_docs_notices_version")
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("torch==2.9.0\n", encoding="utf-8")
    notices = tmp_path / "third-party-notices.md"
    notices.write_text("| torch | 2.8.0+cpu | BSD-3-Clause |\n", encoding="utf-8")

    issues = module.find_dependency_notice_issues([requirements], notices)

    assert len(issues) == 1
    assert "不一致" in issues[0]

def test_check_docs_scans_subdirectories(tmp_path: Path) -> None:
    module = load_check_docs("check_docs_subdir")
    nested = tmp_path / "evidence"
    nested.mkdir()
    (nested / "README.md").write_text("[缺失](../missing.md)\n", encoding="utf-8")

    broken = module.find_broken_links(tmp_path)

    assert len(broken) == 1
    assert "README.md" in broken[0]
    assert "missing.md" in broken[0]
