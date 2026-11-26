"""工具脚本回归测试：交接目录生成与验收证据汇总。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
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

def test_script_help_commands_exit_zero() -> None:
    scripts = (
        "detection_draft_check.py",
        "detection_draft_dataset_check.py",
        "detection_draft_probe.py",
        "dataset_report.py",
        "k230_model_probe.py",
        "k230_readiness.py",
    )
    for name in scripts:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / name), "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
        )
        assert completed.returncode == 0, f"{name} --help 失败：{completed.stderr[:800]}"

def _script_help(name: str, subcommand: str | None, cache: dict) -> str:
    key = (name, subcommand)
    if key not in cache:
        command = [sys.executable, str(ROOT / "scripts" / name)]
        if subcommand:
            command.append(subcommand)
        command.append("--help")
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
        )
        cache[key] = completed.stdout + completed.stderr
    return cache[key]


def test_documentation_commands_match_script_help() -> None:
    import re as _re

    documents = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
    cache: dict = {}
    problems: list[str] = []
    flag_re = _re.compile(r"(?<!\S)(--[A-Za-z0-9_\-]+)")
    tail_re = _re.compile(r"[A-Za-z0-9_\-\.\\/:\s<>\[\]{}]+")
    script_re = _re.compile(r"scripts[\\/]([A-Za-z0-9_\-]+\.py)([^`\n]*)")
    for document in documents:
        for line in document.read_text(encoding="utf-8").splitlines():
            for match in script_re.finditer(line):
                name = match.group(1)
                if not (ROOT / "scripts" / name).is_file():
                    continue
                tail_match = tail_re.match(match.group(2))
                tail = tail_match.group(0) if tail_match else ""
                flags = {flag for flag in flag_re.findall(tail) if flag != "--help"}
                if not flags:
                    continue
                tokens = [token for token in tail.split() if not token.startswith("-")]
                subcommand = tokens[0] if tokens else None
                help_text = _script_help(name, subcommand, cache)
                for flag in sorted(flags):
                    if flag not in help_text:
                        problems.append(f"{document.name}: {name} 不支持 {flag}")
    assert not problems, "\n".join(problems)

def test_documentation_powershell_commands_match_script_params() -> None:
    documents = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
    script_re = re.compile(r"scripts[\\/]([A-Za-z0-9_\-]+\.ps1)([^`\n]*)")
    flag_re = re.compile(r"(?<!\S)-([A-Za-z][A-Za-z0-9_\-]*)")
    params_cache: dict[str, set[str]] = {}
    problems: list[str] = []
    for document in documents:
        for line in document.read_text(encoding="utf-8").splitlines():
            for match in script_re.finditer(line):
                name, tail = match.group(1), match.group(2)
                script = ROOT / "scripts" / name
                if not script.is_file():
                    continue
                if name not in params_cache:
                    source = script.read_text(encoding="utf-8-sig")
                    params_cache[name] = set(re.findall(r"\$([A-Za-z][A-Za-z0-9_]*)", source))
                flags = set(flag_re.findall(re.split(r"[;|&`]", tail)[0]))
                for flag in sorted(flags):
                    if flag not in params_cache[name]:
                        problems.append(f"{document.name}: {name} 无参数 -{flag}")
    assert not problems, "\n".join(problems)

def test_check_docs_reads_bundle_manifest_file_count(tmp_path: Path) -> None:
    import zipfile

    module = load_check_docs("check_docs_file_count")
    bundle = tmp_path / "bundle.zip"
    manifest = {
        "format": "laitp-offline-bundle-1.0",
        "components": [
            {"name": "backend", "files": ["a.py", "b.py"]},
            {"name": "desktop", "files": ["app.exe"]},
        ],
    }
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))

    counts = module.bundle_manifest_file_counts(bundle)

    assert counts == {"file_count": 3}
    assert module.bundle_manifest_file_counts(tmp_path / "missing.zip") is None

def test_check_docs_acceptance_artifact_mismatch(tmp_path: Path) -> None:
    module = load_check_docs("check_docs_acceptance")
    artifact = tmp_path / "acceptance.json"
    artifact.write_text(
        json.dumps(
            {
                "ok": False,
                "steps": [{"name": "a", "status": "fail", "seconds": 1}],
                "warnings": ["failed"],
            }
        ),
        encoding="utf-8",
    )

    issues = module.find_acceptance_artifact_issues(artifact, "| 包内一键验收 | 11 个环节全部通过 |")

    assert any("未通过" in issue for issue in issues)


def test_check_docs_acceptance_artifact_consistent(tmp_path: Path) -> None:
    module = load_check_docs("check_docs_acceptance_ok")
    artifact = tmp_path / "acceptance.json"
    steps = [{"name": f"s{index}", "status": "pass", "seconds": 1} for index in range(11)]
    artifact.write_text(
        json.dumps(
            {
                "ok": True,
                "steps": steps,
                "bundle": {"file_count": 18179},
                "preflight": {"overall": "ready-for-acceptance-attempt"},
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    status = "| x | 11 个环节全部通过，未使用重试 | 18,179 文件 |"

    assert module.find_acceptance_artifact_issues(artifact, status) == []

def test_check_docs_dependency_spec_mismatch(tmp_path: Path) -> None:
    module = load_check_docs("check_docs_spec")
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "laitp"\ndependencies = ["torch>=2.9,<3"]\n',
        encoding="utf-8",
    )
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("torch==2.8.0+cpu\n", encoding="utf-8")

    issues = module.find_dependency_spec_issues(pyproject, [requirements])

    assert len(issues) == 1
    assert "torch" in issues[0]


def test_check_docs_dependency_spec_ok(tmp_path: Path) -> None:
    module = load_check_docs("check_docs_spec_ok")
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "laitp"\ndependencies = ["torch>=2.8,<2.9"]\n',
        encoding="utf-8",
    )
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("torch==2.8.0+cpu\n", encoding="utf-8")

    assert module.find_dependency_spec_issues(pyproject, [requirements]) == []

def test_check_docs_acceptance_audit_summary_mismatch(tmp_path: Path) -> None:
    module = load_check_docs("check_docs_audit")
    audit = tmp_path / "acceptance-local.json"
    audit.write_text(
        json.dumps({"summary": {"verified": 9, "partial": 4, "not_run": 1, "blocked": 1}}),
        encoding="utf-8",
    )
    texts = {"acceptance-checklist.md": "最近一次汇总：**已验证 8 项、部分 4 项、未执行 1 项、阻塞 2 项**"}

    issues = module.find_acceptance_audit_issues(audit, texts)

    assert len(issues) == 1
    assert "已验证 9 项" in issues[0]


def test_check_docs_acceptance_audit_summary_ok(tmp_path: Path) -> None:
    module = load_check_docs("check_docs_audit_ok")
    audit = tmp_path / "acceptance-local.json"
    audit.write_text(
        json.dumps({"summary": {"verified": 9, "partial": 4, "not_run": 1, "blocked": 1}}),
        encoding="utf-8",
    )
    texts = {"acceptance-checklist.md": "最近一次汇总：**已验证 9 项、部分 4 项、未执行 1 项、阻塞 1 项**"}

    assert module.find_acceptance_audit_issues(audit, texts) == []
