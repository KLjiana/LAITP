"""交付状态快速自检：包 SHA/结构、交接目录、最近验证报告、验收汇总与文档一致性。

只读取现有产物，不重新运行耗时验证（约 1 秒）。

用法：
    .venv\\Scripts\\python.exe scripts\\check_state.py
退出码 0 表示状态一致；1 表示发现问题。
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "dist/laitp-offline-lean.zip"
FULL_BUNDLE = ROOT / "dist/laitp-offline-full.zip"
HANDOFF = ROOT / "dist/handoff"
BUNDLE_FORMAT = "laitp-offline-bundle-1.0"
# 打包器写在包根、但不列入 manifest components 的元数据/入口文件。
BUNDLE_ROOT_METADATA = frozenset(
    ("manifest.json", "README.txt", "check-bundle.bat", "start-desktop.bat")
)
DESKTOP_RUNTIMECONFIG = "desktop/app/Laitp.Desktop.runtimeconfig.json"
DESKTOP_RUNTIME_FILES = ("desktop/app/coreclr.dll", "desktop/app/hostfxr.dll")
VERIFY_ALL = ROOT / "artifacts/verify-all/verify-all.json"
ACCEPTANCE = ROOT / "artifacts/acceptance-local.json"
ACCEPTANCE_REPORT = ROOT / "artifacts/acceptance-report-final.md"
HANDOFF_SAMPLE_NAME = "acceptance-report-sample.md"
# 交接目录中文档副本与仓库中的源文件（名称、仓库相对路径），与 make_handoff.py 保持一致。
HANDOFF_DOCUMENTS = (
    ("known-limitations.md", "docs/known-limitations.md"),
    ("README.md", "README.md"),
    ("teacher-quickstart.md", "docs/teacher-quickstart.md"),
    ("acceptance-card.md", "docs/acceptance-card.md"),
    ("acceptance-checklist.md", "docs/acceptance-checklist.md"),
    ("verification-evidence.md", "docs/verification-evidence.md"),
)
PACKAGE_DIR_LINE = re.compile(r"^- 包目录：.*$", re.MULTILINE)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def normalize_acceptance_report(content: str) -> str:
    """按 scripts/make_handoff.py 相同规则改写包目录行，便于比较报告内容。"""
    return PACKAGE_DIR_LINE.sub("- 包目录：（解压目录）", content)


def manifest_document_sha(manifest: dict | None, name: str) -> str | None:
    """从 handoff-manifest.json 的 documents 中读取指定文件的 SHA-256。"""
    documents = manifest.get("documents") if isinstance(manifest, dict) else None
    if not isinstance(documents, list):
        return None
    for item in documents:
        if isinstance(item, dict) and item.get("name") == name:
            digest = item.get("sha256")
            return digest if isinstance(digest, str) and digest else None
    return None


def display_path(path: Path) -> str:
    """优先用仓库相对路径展示（测试临时路径则退回绝对路径）。"""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except (OSError, ValueError):
        return str(path)


def check_handoff_sample(
    report_path: Path | None = None,
    sample_path: Path | None = None,
    manifest: dict | None = None,
) -> dict:
    """核对交接目录样例是否由最新验收报告生成。

    比较前按 make_handoff.py 的规则把 ``- 包目录：...`` 行规范化为固定文本；
    manifest 记录了 documents 中该文件的 SHA-256 时，同时核对交接目录实际文件。
    两个文件任一缺失时只返回跳过 note，不报告问题（不判失败）。

    返回 dict：
    - ``checked``：两个文件都存在、已实际执行比较时为 True；
    - ``problems``：内容不一致或 SHA 不一致的问题列表；
    - ``notes``：文件缺失/无法读取时的跳过说明；
    - ``detail``：通过时写入 checks 的摘要。
    """
    report = ACCEPTANCE_REPORT if report_path is None else Path(report_path)
    sample = HANDOFF / HANDOFF_SAMPLE_NAME if sample_path is None else Path(sample_path)
    missing = [display_path(path) for path in (report, sample) if not path.is_file()]
    if missing:
        return {
            "checked": False,
            "problems": [],
            "notes": [f"未找到 {'、'.join(missing)}，跳过一致性检查（不判失败）"],
            "detail": "",
        }

    try:
        report_text = report.read_text(encoding="utf-8")
        sample_text = sample.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        return {
            "checked": False,
            "problems": [],
            "notes": [f"读取交接报告样例失败，跳过一致性检查（不判失败）：{error}"],
            "detail": "",
        }

    problems: list[str] = []
    if normalize_acceptance_report(report_text) != sample_text:
        problems.append(
            "交接目录 acceptance-report-sample.md 与最新验收报告不一致，"
            "请重新生成 handoff"
        )
    recorded_sha = manifest_document_sha(manifest, HANDOFF_SAMPLE_NAME)
    if recorded_sha is not None:
        actual_sha = sha256_file(sample)
        if recorded_sha != actual_sha:
            problems.append(
                "handoff-manifest.json 记录的 acceptance-report-sample.md SHA-256 "
                f"与交接目录实际文件不一致（记录 {recorded_sha}，实际 {actual_sha}）"
            )

    detail = (
        "；".join(problems)
        if problems
        else "acceptance-report-sample.md 与最新验收报告一致（包目录行已按 make_handoff 规则规范化）"
    )
    return {"checked": True, "problems": problems, "notes": [], "detail": detail}


def check_handoff_documents(
    repo_root: Path | None = None,
    handoff_dir: Path | None = None,
    manifest: dict | None = None,
) -> dict:
    """核对交接目录中的 README.md 与四份 docs 副本是否与仓库最新内容一致。

    - 仓库文件与交接副本都存在时按 SHA-256 比较，不一致记为 problem，
      并提示重新运行 ``scripts/make_handoff.py``；
    - ``handoff-manifest.json``（未显式传入时从交接目录读取）记录了该文档的 SHA-256 时，
      同时核对与交接目录实际文件一致，不一致记为 problem；
    - 交接目录或任一文件缺失、manifest 未记录时只记 note，不判失败。

    返回 dict：
    - ``checked``：至少有一份文档实际执行了比较时为 True；
    - ``problems``：仓库副本不一致或 manifest SHA 不一致的问题列表；
    - ``notes``：跳过说明；
    - ``detail``：通过时写入 checks 的摘要。
    """
    root = ROOT if repo_root is None else Path(repo_root)
    handoff = HANDOFF if handoff_dir is None else Path(handoff_dir)
    problems: list[str] = []
    notes: list[str] = []

    if not handoff.is_dir():
        return {
            "checked": False,
            "problems": problems,
            "notes": [
                f"未找到交接目录 {display_path(handoff)}，跳过文档一致性检查（不判失败）"
            ],
            "detail": "",
        }

    manifest_data = manifest
    if manifest_data is None:
        manifest_data = load_json(handoff / "handoff-manifest.json")
    if not isinstance(manifest_data, dict):
        notes.append(
            "未找到或无法解析 handoff-manifest.json，跳过 manifest SHA 核对（不判失败）"
        )

    compared: list[str] = []
    for handoff_name, repo_relative in HANDOFF_DOCUMENTS:
        repo_file = root / repo_relative
        handoff_file = handoff / handoff_name
        missing = [path for path in (repo_file, handoff_file) if not path.is_file()]
        if missing:
            notes.append(
                f"未找到 {'、'.join(display_path(path) for path in missing)}，"
                f"跳过 {handoff_name} 一致性检查（不判失败）"
            )
            continue
        try:
            repo_sha = sha256_file(repo_file)
            handoff_sha = sha256_file(handoff_file)
        except OSError as error:
            notes.append(f"读取 {handoff_name} 失败，跳过一致性检查（不判失败）：{error}")
            continue
        compared.append(handoff_name)
        if repo_sha != handoff_sha:
            problems.append(
                f"交接目录 {handoff_name} 与仓库不一致，"
                "请重新运行 scripts/make_handoff.py"
            )
        if not isinstance(manifest_data, dict):
            continue
        recorded_sha = manifest_document_sha(manifest_data, handoff_name)
        if recorded_sha is None:
            notes.append(
                f"handoff-manifest.json 未记录 {handoff_name} 的 SHA-256，跳过 manifest 核对"
            )
        elif recorded_sha != handoff_sha:
            problems.append(
                f"handoff-manifest.json 记录的 {handoff_name} SHA-256 与交接目录"
                f"实际文件不一致（记录 {recorded_sha}，实际 {handoff_sha}）"
            )

    if problems:
        detail = "；".join(problems)
    elif compared:
        detail = f"交接目录 {'、'.join(compared)} 与仓库一致"
    else:
        detail = ""
    return {
        "checked": bool(compared),
        "problems": problems,
        "notes": notes,
        "detail": detail,
    }


def manifest_component_paths(manifest: dict) -> tuple[list[str], list[str]]:
    """展开离线包 ``manifest.json`` 的 components 文件路径。

    返回 ``(路径列表, 问题列表)``；components/files 结构异常时只记录问题，
    不抛异常。路径按 ZIP 内相对路径（正斜杠）原样返回。
    """
    components = manifest.get("components")
    if not isinstance(components, list) or not components:
        return [], ["manifest.json 缺少 components 组件列表"]
    paths: list[str] = []
    problems: list[str] = []
    for component in components:
        name = component.get("name") if isinstance(component, dict) else None
        files = component.get("files") if isinstance(component, dict) else None
        if not isinstance(files, list):
            problems.append(
                f"manifest.json 组件 {name or '（未命名）'} 缺少 files 文件列表"
            )
            continue
        for item in files:
            path = item.get("path") if isinstance(item, dict) else None
            if not isinstance(path, str) or not path:
                problems.append(
                    f"manifest.json 组件 {name or '（未命名）'} 含无效文件路径"
                )
                continue
            paths.append(path)
    return paths, problems


def check_bundle_structure(
    bundle_path: Path | None = None,
    label: str = "离线包",
) -> dict:
    """快速校验离线分发包 ZIP 的内部结构（只读 ZIP 目录与少量关键文件）。

    不逐文件校验 SHA-256、不完整解包（约 0.1 秒），用于发现 manifest 与 ZIP
    条目不符、桌面非自包含、启动/自检脚本被替换等结构问题。检查项：

    - ``manifest.json`` 存在、可 JSON 解析，且 ``format`` 为
      ``laitp-offline-bundle-1.0``；
    - manifest components 列出的每个文件都存在于 ZIP，ZIP 也没有未登记
      的非包根元数据条目（可发现 manifest 文件数与 ZIP 条目数不符）；
    - ``desktop/app/Laitp.Desktop.runtimeconfig.json`` 的
      ``runtimeOptions.includedFrameworks`` 非空，且含 ``coreclr.dll``、
      ``hostfxr.dll``（桌面自包含）；
    - ``check-bundle.bat`` 含 ``chcp 65001`` 与
      ``scripts\\verify_offline_bundle.py``；
    - ``start-desktop.bat`` 指向 ``desktop\\app\\Laitp.Desktop.exe``。

    返回 dict（与 ``check_handoff_*`` 一致）：``checked``、``problems``、
    ``notes``、``detail``。文件不存在时只返回跳过 note，不判失败；
    完整解包校验仍由 ``scripts/verify_offline_bundle.py`` 负责。
    """
    bundle = BUNDLE if bundle_path is None else Path(bundle_path)
    problems: list[str] = []

    def fail(message: str) -> None:
        problems.append(f"{label}结构异常：{message}")

    if not bundle.is_file():
        return {
            "checked": False,
            "problems": [],
            "notes": [f"未找到 {display_path(bundle)}，跳过 ZIP 结构检查（不判失败）"],
            "detail": "",
        }

    try:
        archive = zipfile.ZipFile(bundle)
    except (OSError, zipfile.BadZipFile) as error:
        fail(f"无法作为 ZIP 打开：{error}")
        return {
            "checked": True,
            "problems": problems,
            "notes": [],
            "detail": "；".join(problems),
        }

    manifest_paths: list[str] = []
    file_entries: set[str] = set()
    with archive:
        try:
            names = archive.namelist()
        except (OSError, zipfile.BadZipFile) as error:
            fail(f"无法读取 ZIP 目录：{error}")
            return {
                "checked": True,
                "problems": problems,
                "notes": [],
                "detail": "；".join(problems),
            }
        # 只比较文件条目；容忍打包器可能写入的目录条目。
        file_entries = {name for name in names if not name.endswith("/")}

        manifest_loaded = False
        manifest: object = None
        if "manifest.json" not in file_entries:
            fail("缺少 manifest.json")
        else:
            try:
                manifest = json.loads(
                    archive.read("manifest.json").decode("utf-8")
                )
            except (OSError, UnicodeDecodeError, ValueError, zipfile.BadZipFile) as error:
                fail(f"manifest.json 无法解析：{error}")
            else:
                manifest_loaded = True

        if manifest_loaded and not isinstance(manifest, dict):
            fail("manifest.json 顶层不是 JSON 对象")
        elif isinstance(manifest, dict):
            format_version = manifest.get("format")
            if format_version != BUNDLE_FORMAT:
                fail(
                    f"manifest.json format 为 {format_version!r}，"
                    f"应为 {BUNDLE_FORMAT}"
                )
            manifest_paths, path_problems = manifest_component_paths(manifest)
            for problem in path_problems:
                fail(problem)
            missing = [path for path in manifest_paths if path not in file_entries]
            if missing:
                fail(
                    f"manifest 列出的 {len(missing)} 个文件不在 ZIP 中："
                    + "、".join(missing[:5])
                    + (" 等" if len(missing) > 5 else "")
                )
            unregistered = sorted(
                file_entries - set(manifest_paths) - BUNDLE_ROOT_METADATA
            )
            if unregistered:
                fail(
                    f"ZIP 含 {len(unregistered)} 个未在 manifest 登记的条目："
                    + "、".join(unregistered[:5])
                    + (" 等" if len(unregistered) > 5 else "")
                )
            if len(manifest_paths) != len(set(manifest_paths)):
                fail("manifest 文件列表含重复路径")

        if DESKTOP_RUNTIMECONFIG not in file_entries:
            fail(f"缺少 {DESKTOP_RUNTIMECONFIG}")
        else:
            try:
                runtimeconfig = json.loads(
                    archive.read(DESKTOP_RUNTIMECONFIG).decode("utf-8")
                )
            except (OSError, UnicodeDecodeError, ValueError, zipfile.BadZipFile) as error:
                fail(f"无法解析 {DESKTOP_RUNTIMECONFIG}：{error}")
            else:
                runtime_options = (
                    runtimeconfig.get("runtimeOptions")
                    if isinstance(runtimeconfig, dict)
                    else None
                )
                included = (
                    runtime_options.get("includedFrameworks")
                    if isinstance(runtime_options, dict)
                    else None
                )
                if not included:
                    fail(
                        "桌面程序不是自包含发布"
                        "（runtimeconfig 缺少 includedFrameworks）"
                    )

        for runtime_file in DESKTOP_RUNTIME_FILES:
            if runtime_file not in file_entries:
                fail(f"缺少 {runtime_file}")

        if "check-bundle.bat" not in file_entries:
            fail("缺少 check-bundle.bat")
        else:
            normalized = (
                archive.read("check-bundle.bat")
                .decode("utf-8", "replace")
                .lower()
                .replace("/", "\\")
            )
            if "chcp 65001" not in normalized:
                fail("check-bundle.bat 未切换 UTF-8 代码页：缺少 chcp 65001")
            if "scripts\\verify_offline_bundle.py" not in normalized:
                fail(
                    "check-bundle.bat 未调用包内自检脚本："
                    "缺少 scripts\\verify_offline_bundle.py"
                )

        if "start-desktop.bat" not in file_entries:
            fail("缺少 start-desktop.bat")
        else:
            normalized = (
                archive.read("start-desktop.bat")
                .decode("utf-8", "replace")
                .lower()
                .replace("/", "\\")
            )
            if "desktop\\app\\laitp.desktop.exe" not in normalized:
                fail(
                    "start-desktop.bat 未指向包内 "
                    "desktop\\app\\Laitp.Desktop.exe"
                )

    if problems:
        return {
            "checked": True,
            "problems": problems,
            "notes": [],
            "detail": "；".join(problems),
        }
    return {
        "checked": True,
        "problems": [],
        "notes": [],
        "detail": (
            "ZIP 结构/自包含/启动脚本通过"
            f"（manifest {len(manifest_paths)} 个文件均存在于 ZIP，"
            f"共 {len(file_entries)} 个条目）"
        ),
    }


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    problems: list[str] = []
    notes: list[str] = []
    checks: list[dict] = []

    def record(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            problems.append(f"{name}：{detail}")

    bundle_sha = None
    if BUNDLE.is_file():
        bundle_sha = sha256_file(BUNDLE)
        size = BUNDLE.stat().st_size
        notes.append(f"离线包 {size:,} 字节，SHA-256 {bundle_sha}")
        offline = ROOT / "docs/offline-bundle.md"
        text = offline.read_text(encoding="utf-8") if offline.is_file() else ""
        document_problems: list[str] = []
        if not (bundle_sha and bundle_sha in text):
            document_problems.append("offline-bundle.md 未包含当前离线包完整 SHA-256")
        if f"{size:,}" not in text:
            document_problems.append("offline-bundle.md 未包含当前离线包体积（千分位）")
        # 精简包 SHA 与体积同属交付文档一致性，合并为 1 项；
        # 原有“离线包”检查仍为 SHA/体积 + ZIP 结构 2 项，check_state 总项数保持 11。
        record(
            "离线包 SHA/体积写入文档",
            not document_problems,
            "；".join(document_problems)
            if document_problems
            else "offline-bundle.md 含当前完整 SHA-256 与体积（千分位）",
        )

        structure_problems: list[str] = []
        structure_details: list[str] = []
        lean_structure = check_bundle_structure(BUNDLE)
        notes.extend(lean_structure["notes"])
        structure_problems.extend(lean_structure["problems"])
        if lean_structure["checked"]:
            structure_details.append(f"精简包：{lean_structure['detail']}")
        if FULL_BUNDLE.is_file():
            full_structure = check_bundle_structure(
                FULL_BUNDLE, label="完整离线包"
            )
            notes.extend(full_structure["notes"])
            structure_problems.extend(full_structure["problems"])
            if full_structure["checked"]:
                structure_details.append(f"完整包：{full_structure['detail']}")
        record(
            "离线包结构轻量校验",
            not structure_problems,
            "；".join(structure_problems)
            if structure_problems
            else "；".join(structure_details),
        )
        notes.append(
            "离线包结构为轻量 ZIP 检查（manifest 引用/桌面自包含/启动脚本），"
            "不替代 verify_offline_bundle.py 的完整解包校验"
        )
    else:
        record("离线包存在", False, "未找到 dist/laitp-offline-lean.zip")

    handoff_zip = HANDOFF / "laitp-offline-lean.zip"
    manifest = load_json(HANDOFF / "handoff-manifest.json")
    if handoff_zip.is_file() and manifest:
        handoff_sha = sha256_file(handoff_zip)
        record(
            "交接目录 SHA 一致",
            bundle_sha == handoff_sha == manifest.get("bundle", {}).get("sha256"),
            "交接 ZIP 与 manifest、dist 包 SHA 一致",
        )
        required = [
            "交接说明.txt",
            "teacher-quickstart.md",
            "acceptance-checklist.md",
            "verification-evidence.md",
            "laitp-offline-lean.zip.sha256",
        ]
        missing = [name for name in required if not (HANDOFF / name).is_file()]
        record("交接目录文件齐全", not missing, f"缺失：{missing}" if missing else "关键文件齐全")
    else:
        record("交接目录存在", False, "dist/handoff 或 handoff-manifest.json 缺失")

    verify_all = load_json(VERIFY_ALL)
    if verify_all:
        steps = verify_all.get("steps", [])
        failed = [
            step.get("name")
            for step in steps
            if step.get("status") not in ("pass", "skip")
        ]
        skipped = [
            step.get("name") for step in steps if step.get("status") == "skip"
        ]
        detail = f"{len(steps) - len(skipped)} 步通过" if not failed else f"{len(steps)} 步，失败：{failed}"
        if skipped and not failed:
            detail += f"，{len(skipped)} 步跳过：{skipped}"
        record("最近一键验证通过", bool(verify_all.get("ok")) and not failed, detail)
    else:
        record("最近一键验证存在", False, "未找到 artifacts/verify-all/verify-all.json")

    acceptance = load_json(ACCEPTANCE)
    if acceptance:
        record(
            "验收汇总与当前包一致",
            bundle_sha is not None
            and acceptance.get("bundle", {}).get("sha256") == bundle_sha,
            "artifacts/acceptance-local.json 引用当前包 SHA",
        )
        record(
            "验收汇总覆盖 A1–A15",
            len(acceptance.get("items", [])) == 15,
            f"共 {len(acceptance.get('items', []))} 项",
        )
    else:
        record("验收汇总存在", False, "未找到 artifacts/acceptance-local.json")

    stability_candidates = [
        path
        for path in (
            ROOT / "artifacts/ui-preview-stability.json",
            ROOT / "artifacts/ui-preview-stability-bundle.json",
        )
        if path.is_file()
    ]
    stability = None
    if stability_candidates:
        latest = max(stability_candidates, key=lambda path: path.stat().st_mtime)
        stability = load_json(latest)
    if stability:
        growth = stability.get("memory_growth_mb")
        growth_ok = growth is None or growth < 150
        fps_ok = "fps" in (stability.get("preview_status") or "")
        record(
            "长时间预览稳定性",
            bool(stability.get("ok")) and growth_ok and fps_ok,
            f"fps 状态 {stability.get('preview_status')}；内存增长 {growth} MB",
        )
    else:
        record("长时间预览稳定性", False, "未找到 ui-preview-stability*.json")

    completed = subprocess.run(
        [sys.executable, "scripts/check_docs.py"],
        cwd=ROOT,
        capture_output=True,
    )
    record(
        "文档一致性检查",
        completed.returncode == 0,
        completed.stdout.decode("utf-8", "replace")[:500]
        if completed.returncode
        else "check_docs.py 通过",
    )

    sample_result = check_handoff_sample(manifest=manifest)
    notes.extend(sample_result["notes"])
    if sample_result["checked"]:
        record(
            "交接目录验收报告样例一致",
            not sample_result["problems"],
            sample_result["detail"],
        )

    documents_result = check_handoff_documents(ROOT, HANDOFF, manifest=manifest)
    notes.extend(documents_result["notes"])
    if documents_result["checked"]:
        record(
            "交接目录文档与仓库一致",
            not documents_result["problems"],
            documents_result["detail"],
        )

    payload = {
        "ok": not problems,
        "problems": problems,
        "checks": checks,
        "notes": notes,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
