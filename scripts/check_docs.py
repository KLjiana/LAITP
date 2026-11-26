"""文档一致性检查：核对本地链接/锚点、离线包 SHA/体积、测试数、Core 检查数、验证步数与缩写 SHA。

用法：
    .venv\\Scripts\\python.exe scripts\\check_docs.py
退出码 0 表示一致；1 表示发现不一致（输出 JSON 说明）。
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


LINK_RE = re.compile(r"\]\(([^)\s]+)\)")


def find_broken_links_in(paths: list[Path]) -> list[str]:
    """返回一组 Markdown 文件中指向不存在本地文件的链接。"""
    broken: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for target in LINK_RE.findall(text):
            if target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            file_part = target.split("#", 1)[0]
            if not file_part:
                continue
            if not (path.parent / file_part).resolve().exists():
                broken.append(f"{path.name} -> {target}")
    return broken


def find_broken_links(docs_dir: Path) -> list[str]:
    """返回 docs 目录下 Markdown 的失效本地链接（忽略外链与纯锚点）。"""
    return find_broken_links_in(sorted(docs_dir.rglob("*.md")))


HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
ESCAPE_RE = re.compile(r"\\(.)")
SLUG_STRIP_RE = re.compile(r"[^\w\s-]")


def iter_markdown_headings(text: str) -> list[str]:
    """按行提取 Markdown 标题文本，跳过围栏代码块中的 `#` 注释。"""
    headings: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        fence_match = FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)[0]
            if fence is None:
                fence = marker
            elif fence == marker:
                fence = None
            continue
        if fence is not None:
            continue
        heading_match = HEADING_RE.match(line)
        if heading_match:
            headings.append(heading_match.group(2))
    return headings


def slugify_heading(heading: str) -> str:
    """把标题文本转成 GitHub 风格锚点（小写、去行内格式与标点、空格转连字符）。"""
    text = ESCAPE_RE.sub(r"\1", heading.strip())
    text = text.replace("**", "").replace("`", "")
    text = text.lower()
    text = SLUG_STRIP_RE.sub("", text)
    return text.replace(" ", "-")


def heading_slugs(text: str) -> list[str]:
    """返回文档中按出现顺序生成的锚点；重复标题按 GitHub 规则追加 -1、-2。"""
    occurrences: dict[str, int] = {}
    slugs: list[str] = []
    for heading in iter_markdown_headings(text):
        base = slugify_heading(heading)
        if not base:
            continue
        slug = base
        while slug in occurrences:
            occurrences[base] = occurrences.get(base, 0) + 1
            slug = f"{base}-{occurrences[base]}"
        occurrences[slug] = 0
        slugs.append(slug)
    return slugs


def is_anchor_document(
    target: Path, sources: list[Path], source_dirs: set[Path]
) -> bool:
    """锚点目标限于源文档同目录的 .md、docs/ 目录或仓库根 README。"""
    if target.suffix.lower() != ".md" or not target.is_file():
        return False
    if target in sources or target.parent in source_dirs:
        return True
    # README（源文件在仓库根）链接到 docs/ 下的文档。
    if target.parent.name == "docs" and target.parent.parent in source_dirs:
        return True
    # docs 文档链接到仓库根 README。
    root_dirs = {directory.parent for directory in source_dirs if directory.name == "docs"}
    return target.name == "README.md" and target.parent in root_dirs


def find_broken_anchors(paths: list[Path]) -> list[str]:
    """返回一组 Markdown 文件中指向不存在标题锚点的本地链接。

    检查 `file.md#锚点` 与同文件内的 `#锚点`；外链、目标文件不存在或目标不是
    docs 文档/根 README 时跳过（文件缺失由 find_broken_links_in 报告）。
    """
    sources = [path.resolve() for path in paths]
    source_dirs = {path.parent for path in sources}
    slug_cache: dict[Path, set[str]] = {}
    broken: list[str] = []

    def target_slugs(target: Path) -> set[str] | None:
        resolved = target.resolve()
        if resolved in slug_cache:
            return slug_cache[resolved]
        if not is_anchor_document(resolved, sources, source_dirs):
            return None
        slugs = set(heading_slugs(resolved.read_text(encoding="utf-8")))
        slug_cache[resolved] = slugs
        return slugs

    for path in sources:
        text = path.read_text(encoding="utf-8")
        for target in LINK_RE.findall(text):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            if "#" not in target:
                continue
            file_part, anchor = target.split("#", 1)
            if not anchor:
                continue
            target_path = path.parent / file_part if file_part else path
            slugs = target_slugs(target_path)
            if slugs is not None and anchor not in slugs:
                broken.append(f"{path.name} -> {target}")
    return broken


def unique_counts(texts: dict[str, str], pattern: str) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for name, text in texts.items():
        values = set(re.findall(pattern, text))
        if values:
            found[name] = values
    return found


def parse_requirements_pins(path: Path) -> list[tuple[str, str]]:
    """解析 requirements 文件中的 name==version 固定项（跳过 -r/--index/注释）。"""
    if not path.is_file():
        return []
    pins: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("-", "#")):
            continue
        match = re.match(r"^([A-Za-z0-9_.\-]+)==([^\s;#]+)", stripped)
        if match:
            pins.append((match.group(1).lower(), match.group(2)))
    return pins


def parse_notice_versions(path: Path) -> dict[str, set[str]]:
    """解析第三方许可说明表格中的 | 组件 | 版本 | 行。"""
    if not path.is_file():
        return {}
    versions: dict[str, set[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\|\s*([A-Za-z0-9_.\-]+)\s*\|\s*([^\s|]+)", line)
        if match:
            versions.setdefault(match.group(1).lower(), set()).add(match.group(2))
    return versions


def find_dependency_spec_issues(pyproject: Path, requirements: list[Path]) -> list[str]:
    """核对 requirements 的固定版本落在 pyproject 声明的版本范围内。"""
    if not pyproject.is_file():
        return []
    try:
        import tomllib
    except ImportError:  # pragma: no cover
        return []
    try:
        from packaging.requirements import Requirement
    except ImportError:  # pragma: no cover
        return []
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"{pyproject.name} 无法解析：{exc}"]
    declared: dict[str, Requirement] = {}
    for item in (data.get("project") or {}).get("dependencies") or []:
        try:
            requirement = Requirement(item)
        except ValueError:
            continue
        declared[requirement.name.lower()] = requirement
    issues: list[str] = []
    for requirement_file in requirements:
        for name, version in parse_requirements_pins(requirement_file):
            declared_requirement = declared.get(name)
            if declared_requirement is None:
                continue
            if not declared_requirement.specifier.contains(version, prereleases=True):
                issues.append(
                    f"{pyproject.name} 声明 {declared_requirement}，"
                    f"但 {requirement_file.name} 固定为 {name}=={version}，不在范围内"
                )
    return issues


def find_dependency_notice_issues(
    requirements: list[Path], notices: Path
) -> list[str]:
    """核对 requirements 固定版本与第三方许可说明表格一致。"""
    notice_versions = parse_notice_versions(notices)
    issues: list[str] = []
    for requirement in requirements:
        for name, version in parse_requirements_pins(requirement):
            known = notice_versions.get(name)
            if not known:
                issues.append(
                    f"{notices.name} 未列出依赖 {name}=={version}（来自 {requirement.name}）"
                )
            elif version not in known:
                issues.append(
                    f"{notices.name} 中 {name} 版本为 {sorted(known)}，"
                    f"与 {requirement.name} 的 {version} 不一致"
                )
    return issues


def bundle_manifest_file_counts(bundle: Path) -> dict[str, int] | None:
    """从离线包 manifest.json 统计各组件文件总数（精简=1 包，完整=1 包）。"""
    if not bundle.is_file():
        return None
    try:
        with zipfile.ZipFile(bundle) as archive:
            payload = json.loads(archive.read("manifest.json").decode("utf-8"))
    except (KeyError, OSError, ValueError):
        return None
    total = 0
    for component in payload.get("components") or []:
        total += len(component.get("files") or [])
    return {"file_count": total}


def find_acceptance_artifact_issues(artifact_path: Path, status_text: str) -> list[str]:
    """核对 acceptance-run-final.json 与状态报告结论是否一致（产物不存在则跳过）。"""
    if not artifact_path.is_file():
        return []
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return [f"验收产物无法解析：{artifact_path}（{exc}）"]
    issues: list[str] = []
    steps = payload.get("steps") or []
    ok = bool(payload.get("ok"))
    if ok and "未通过" in status_text:
        issues.append("验收产物为通过，但状态报告仍写未通过")
    if not ok and "未通过" not in status_text:
        issues.append("验收产物显示未通过，但状态报告未标注未通过")
    if ok:
        if len(steps) != 11:
            issues.append(f"验收产物步骤数为 {len(steps)}，预期 11")
        if "11 个环节全部通过" not in status_text:
            issues.append("状态报告未写明“11 个环节全部通过”，与验收产物不一致")
        bundle = payload.get("bundle") or {}
        file_count = bundle.get("file_count")
        if isinstance(file_count, int) and f"{file_count:,}" not in status_text:
            issues.append(
                f"状态报告未包含验收产物中的清单文件数（{file_count:,}）"
            )
        if payload.get("preflight") is None:
            issues.append("验收产物缺少 preflight 字段（环境预检未记录）")
    return issues


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    problems: list[str] = []
    notes: list[str] = []
    doc_paths = sorted(DOCS.rglob("*.md"))
    texts = {
        path.relative_to(DOCS).as_posix(): path.read_text(encoding="utf-8")
        for path in doc_paths
    }
    for broken in find_broken_links(DOCS):
        problems.append(f"文档链接失效：{broken}")
    for broken in find_broken_anchors(doc_paths):
        problems.append(f"文档锚点失效：{broken}")
    for issue in find_dependency_notice_issues(
        [ROOT / "requirements.txt", ROOT / "requirements-dev.txt"],
        DOCS / "third-party-notices.md",
    ):
        problems.append(issue)
    for issue in find_acceptance_artifact_issues(
        ROOT / "artifacts" / "acceptance-run-final.json",
        texts.get("status-report.md", ""),
    ):
        problems.append(issue)
    for issue in find_dependency_spec_issues(
        ROOT / "pyproject.toml",
        [ROOT / "requirements.txt", ROOT / "requirements-dev.txt"],
    ):
        problems.append(issue)
    readme = ROOT / "README.md"
    if readme.is_file():
        for broken in find_broken_links_in([readme]):
            problems.append(f"README 链接失效：{broken}")
        for broken in find_broken_anchors([readme]):
            problems.append(f"README 锚点失效：{broken}")

    bundle = ROOT / "dist/laitp-offline-lean.zip"
    if bundle.is_file():
        sha = sha256_file(bundle)
        size = bundle.stat().st_size
        notes.append(f"离线包 {size} 字节，SHA-256 {sha}")
        offline = texts.get("offline-bundle.md", "")
        if sha not in offline:
            problems.append("offline-bundle.md 未包含当前离线包完整 SHA-256")
        if f"{size:,}" not in offline:
            problems.append("offline-bundle.md 未包含当前离线包体积（千分位）")
        allowed_short = {sha[:8]}
        full_bundle = ROOT / "dist/laitp-offline-full.zip"
        if full_bundle.is_file():
            full_sha = sha256_file(full_bundle)
            full_size = full_bundle.stat().st_size
            allowed_short.add(full_sha[:8])
            notes.append(f"完整包 {full_size} 字节，SHA-256 {full_sha}")
            if full_sha not in offline:
                problems.append("offline-bundle.md 未包含当前完整包完整 SHA-256")
            if f"{full_size:,}" not in offline:
                problems.append("offline-bundle.md 未包含当前完整包体积（千分位）")
        for name, text in texts.items():
            for match in re.finditer(r"[0-9a-f]{8}…[0-9a-f]{4,6}", text):
                if match.group(0)[:8] not in allowed_short:
                    problems.append(
                        f"{name} 含过期缩写 SHA：{match.group(0)}（应为 {sha[:8]}…{sha[-5:]} 或完整包缩写）"
                    )
    else:
        notes.append("未找到 dist/laitp-offline-lean.zip，跳过 SHA/体积核对")

    lean_counts = bundle_manifest_file_counts(bundle)
    if lean_counts:
        lean_count = lean_counts["file_count"]
        offline_text = texts.get("offline-bundle.md", "")
        if f"{lean_count:,}" not in offline_text:
            problems.append(
                f"offline-bundle.md 未包含当前精简包清单文件数（{lean_count:,}）"
            )
        if full_bundle.is_file():
            full_counts = bundle_manifest_file_counts(full_bundle)
            if full_counts and f"{full_counts['file_count']:,}" not in offline_text:
                problems.append(
                    "offline-bundle.md 未包含当前完整包清单文件数"
                    f"（{full_counts['file_count']:,}）"
                )

    # “passed”只比较当前状态类文档；历史规划文档保留当时的测试数。
    passed = unique_counts(
        {name: texts[name] for name in ("status-report.md", "verification-evidence.md") if name in texts},
        r"(\d+) passed",
    )
    passed_values = {value for values in passed.values() for value in values}
    if len(passed_values) > 1:
        problems.append(f"文档中的测试通过数不一致：{sorted(passed_values)}")
    elif passed:
        notes.append(f"文档测试通过数：{sorted(passed_values)[0]}")

    core = unique_counts(texts, r"Core[^0-9\n]{0,8}(\d+) 项")
    core_values = {value for values in core.values() for value in values}
    if len(core_values) > 1:
        problems.append(f"文档中的 Core 检查数不一致：{sorted(core_values)}")
    elif core:
        notes.append(f"文档 Core 检查数：{sorted(core_values)[0]}")

    # “默认 14 步 / 加摄像头 15 步”是合理区分；只核对“N 步全部通过”的当前结论。
    steps = unique_counts(texts, r"(\d+) 步全部通过")
    step_values = {value for values in steps.values() for value in values}
    if len(step_values) > 1:
        problems.append(f"文档中的验证步数不一致：{sorted(step_values)}")
    elif steps:
        notes.append(f"文档验证步数：{sorted(step_values)[0]}")

    payload = {"ok": not problems, "problems": problems, "notes": notes}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
