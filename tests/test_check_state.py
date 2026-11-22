"""check_state.py 交接目录一致性与离线包结构检查的单元测试。

覆盖 ``check_handoff_sample``（第 10 项）与 ``check_handoff_documents``（第 11 项）
的可独立测试逻辑：
- 报告包目录行按 make_handoff 规则规范化后一致时无 problem；
- 交接文档副本与仓库一致、manifest SHA 一致时无 problem；
- 篡改交接样例/交接文档副本后返回 problem（含 acceptance-card.md）；
- manifest 记录的 SHA-256 与实际文件不一致时返回 problem；
- 任一文件或交接目录缺失时返回跳过 note（不判失败）。

覆盖 ``check_bundle_structure``（离线包 SHA/体积检查中的 ZIP 结构轻量子项）：
- 正常小 ZIP（含 manifest、自包含 runtimeconfig、coreclr/hostfxr、两个 .bat）通过；
- 缺 coreclr/hostfxr、缺 runtimeconfig 或 runtimeconfig 不为自包含时返回 problem；
- manifest 列出的路径不在 ZIP 中、ZIP 含未登记条目、format 不符时返回 problem；
- 启动/自检脚本内容不符合要求时返回 problem；
- ZIP 缺失或损坏时分别返回跳过 note / problem。

通过 importlib 按文件路径加载脚本模块，不执行 ``main()``，也不依赖仓库真实产物。
"""

from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_NAME = "acceptance-report-sample.md"
HANDOFF_DOC_NAMES = (
    "README.md",
    "teacher-quickstart.md",
    "acceptance-card.md",
    "acceptance-checklist.md",
    "verification-evidence.md",
    "known-limitations.md",
    "third-party-notices.md",
)
HANDOFF_DOC_TEXT = {
    "README.md": "# 临时 README\n\n交接文档一致性测试用项目说明。\n",
    "teacher-quickstart.md": "# 老师快速上手\n\n临时文档。\n",
    "acceptance-card.md": "# 验收操作卡\n\n临时文档。\n",
    "acceptance-checklist.md": "# 验收清单\n\n临时文档。\n",
    "verification-evidence.md": "# 验证证据\n\n临时文档。\n",
    "known-limitations.md": "# 已知限制\n\n临时文档。\n",
    "third-party-notices.md": "# 第三方许可\n\n临时文档。\n",
}

REPORT_TEXT = (
    "# LAITP 离线包验收记录\n"
    "\n"
    "- 时间：2026-11-19 10:49:21\n"
    "- 系统：Microsoft Windows NT 10.0.26200.0\n"
    "- 包目录：C:\\Users\\demo\\AppData\\Local\\Temp\\laitp-stage\n"
    "\n"
    "## 结论\n"
    "\n"
    "通过。\n"
)
SAMPLE_TEXT = REPORT_TEXT.replace(
    "- 包目录：C:\\Users\\demo\\AppData\\Local\\Temp\\laitp-stage",
    "- 包目录：（解压目录）",
)


def load_check_state():
    spec = importlib.util.spec_from_file_location(
        "laitp_check_state", ROOT / "scripts/check_state.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_handoff(
    tmp_path: Path, module, sample_text: str = SAMPLE_TEXT
) -> tuple[Path, Path, dict]:
    """在临时目录构造验收报告、交接样例与 manifest，返回可传给被测函数的参数。"""
    report = tmp_path / "acceptance-report-final.md"
    report.write_text(REPORT_TEXT, encoding="utf-8")

    handoff = tmp_path / "handoff"
    handoff.mkdir()
    sample = handoff / SAMPLE_NAME
    sample.write_text(sample_text, encoding="utf-8")

    manifest = {
        "generated_at": "2026-11-19 10:49:21",
        "documents": [
            {
                "name": SAMPLE_NAME,
                "size": sample.stat().st_size,
                "sha256": module.sha256_file(sample),
            }
        ],
    }
    return report, sample, manifest


def run_check(module, report: Path, sample: Path, manifest: dict) -> dict:
    return module.check_handoff_sample(
        report_path=report, sample_path=sample, manifest=manifest
    )


def test_normalize_acceptance_report_rewrites_only_package_directory_line() -> None:
    module = load_check_state()
    normalized = module.normalize_acceptance_report(REPORT_TEXT)

    assert "- 包目录：（解压目录）" in normalized
    assert "C:\\Users" not in normalized
    # 其它行原样保留，且与 make_handoff 生成样例的规范化结果完全一致。
    assert "- 时间：2026-11-19 10:49:21" in normalized
    assert normalized == SAMPLE_TEXT


def test_consistent_sample_has_no_problems(tmp_path: Path) -> None:
    module = load_check_state()
    report, sample, manifest = build_handoff(tmp_path, module)

    result = run_check(module, report, sample, manifest)

    assert result["checked"] is True
    assert result["problems"] == []
    assert result["notes"] == []
    assert "一致" in result["detail"]


def test_tampered_sample_is_reported(tmp_path: Path) -> None:
    module = load_check_state()
    report, sample, manifest = build_handoff(tmp_path, module)
    # 样例被手工改动（manifest 仍记录原 SHA），应同时暴露内容与 SHA 不一致。
    sample.write_text(SAMPLE_TEXT.replace("通过。", "未通过。"), encoding="utf-8")

    result = run_check(module, report, sample, manifest)

    assert result["checked"] is True
    joined = "".join(result["problems"])
    assert "不一致" in joined
    assert "重新生成 handoff" in joined
    assert "SHA-256" in joined


def test_manifest_sha_mismatch_is_reported_even_when_content_matches(
    tmp_path: Path,
) -> None:
    module = load_check_state()
    report, sample, manifest = build_handoff(tmp_path, module)
    manifest["documents"][0]["sha256"] = "0" * 64

    result = run_check(module, report, sample, manifest)

    assert result["checked"] is True
    joined = "".join(result["problems"])
    assert "SHA-256" in joined
    assert "不一致" in joined


@pytest.mark.parametrize("removed", ["report", "sample", "both"])
def test_missing_files_skip_without_problem(tmp_path: Path, removed: str) -> None:
    module = load_check_state()
    report, sample, manifest = build_handoff(tmp_path, module)
    if removed in ("report", "both"):
        report.unlink()
    if removed in ("sample", "both"):
        sample.unlink()

    result = run_check(module, report, sample, manifest)

    assert result["checked"] is False
    assert result["problems"] == []
    assert len(result["notes"]) == 1
    assert "未找到" in result["notes"][0]
    assert "跳过一致性检查（不判失败）" in result["notes"][0]


def repo_relative_doc(name: str) -> Path:
    """交接文档在仓库中的相对位置：README.md 在根，其余四份在 docs/ 下。"""
    return Path(name) if name == "README.md" else Path("docs") / name


def build_handoff_documents(
    tmp_path: Path, module
) -> tuple[Path, Path, dict]:
    """在临时目录构造仓库文档、交接副本与 handoff-manifest.json。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    handoff = tmp_path / "handoff"
    handoff.mkdir()

    documents: list[dict] = []
    for name in HANDOFF_DOC_NAMES:
        source = repo / repo_relative_doc(name)
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(HANDOFF_DOC_TEXT[name], encoding="utf-8")
        destination = handoff / name
        destination.write_bytes(source.read_bytes())
        documents.append(
            {
                "name": name,
                "size": destination.stat().st_size,
                "sha256": module.sha256_file(destination),
            }
        )

    manifest = {
        "generated_at": "2026-11-19 10:49:21",
        "documents": documents,
    }
    (handoff / "handoff-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return repo, handoff, manifest


def test_handoff_documents_consistent_has_no_problems(tmp_path: Path) -> None:
    module = load_check_state()
    repo, handoff, _ = build_handoff_documents(tmp_path, module)

    # 不显式传 manifest，验证函数会自行读取 handoff-manifest.json。
    result = module.check_handoff_documents(repo, handoff)

    assert result["checked"] is True
    assert result["problems"] == []
    assert result["notes"] == []
    assert "与仓库一致" in result["detail"]
    for name in HANDOFF_DOC_NAMES:
        assert name in result["detail"]


def test_tampered_handoff_document_is_reported(tmp_path: Path) -> None:
    module = load_check_state()
    repo, handoff, _ = build_handoff_documents(tmp_path, module)
    # 交接副本被手工改动（manifest 仍记录原 SHA），应暴露与仓库及 manifest 不一致。
    tampered = handoff / "teacher-quickstart.md"
    tampered.write_text(
        HANDOFF_DOC_TEXT["teacher-quickstart.md"] + "\n过期内容。\n", encoding="utf-8"
    )

    result = module.check_handoff_documents(repo, handoff)

    assert result["checked"] is True
    joined = "".join(result["problems"])
    assert "teacher-quickstart.md 与仓库不一致" in joined
    assert "重新运行 scripts/make_handoff.py" in joined
    assert "SHA-256" in joined


def test_acceptance_card_mismatch_is_reported(tmp_path: Path) -> None:
    module = load_check_state()
    repo, handoff, _ = build_handoff_documents(tmp_path, module)
    # 仓库里的验收操作卡已更新，但交接目录未重新生成：应判不一致。
    (repo / "docs" / "acceptance-card.md").write_text(
        HANDOFF_DOC_TEXT["acceptance-card.md"] + "\n新增验收步骤。\n", encoding="utf-8"
    )

    result = module.check_handoff_documents(repo, handoff)

    assert result["checked"] is True
    joined = "".join(result["problems"])
    assert "acceptance-card.md 与仓库不一致" in joined
    assert "重新运行 scripts/make_handoff.py" in joined
    # 交接副本自身与 manifest 记录仍一致，问题只来自仓库文件已更新。
    assert "handoff-manifest.json" not in joined


def test_manifest_sha_mismatch_is_reported_even_when_copies_match(
    tmp_path: Path,
) -> None:
    module = load_check_state()
    repo, handoff, manifest = build_handoff_documents(tmp_path, module)
    for item in manifest["documents"]:
        if item["name"] == "acceptance-checklist.md":
            item["sha256"] = "0" * 64
    (handoff / "handoff-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )

    result = module.check_handoff_documents(repo, handoff)

    assert result["checked"] is True
    joined = "".join(result["problems"])
    assert "acceptance-checklist.md" in joined
    assert "handoff-manifest.json" in joined
    assert "SHA-256" in joined
    # 副本本身仍与仓库一致，问题只来自 manifest 记录。
    assert "与仓库不一致" not in joined


@pytest.mark.parametrize("case", ["handoff_dir", "handoff_file"])
def test_missing_handoff_paths_skip_without_problem(
    tmp_path: Path, case: str
) -> None:
    module = load_check_state()
    repo, handoff, _ = build_handoff_documents(tmp_path, module)
    if case == "handoff_dir":
        result = module.check_handoff_documents(repo, tmp_path / "missing-handoff")
        assert result["checked"] is False
        assert len(result["notes"]) == 1
        assert "未找到交接目录" in result["notes"][0]
    else:
        (handoff / "README.md").unlink()
        result = module.check_handoff_documents(repo, handoff)
        # 其余四份仍被比较，缺失的一份只记 note。
        assert result["checked"] is True
        assert any(
            "README.md" in note and "跳过" in note for note in result["notes"]
        )
    assert result["problems"] == []
    assert all("不判失败" in note for note in result["notes"])


# --- 离线包 ZIP 结构轻量校验（check_bundle_structure） -------------------------

BUNDLE_FORMAT = "laitp-offline-bundle-1.0"
RUNTIMECONFIG_PATH = "desktop/app/Laitp.Desktop.runtimeconfig.json"
CORE_PATHS = (
    RUNTIMECONFIG_PATH,
    "desktop/app/coreclr.dll",
    "desktop/app/hostfxr.dll",
)
SELF_CONTAINED_RUNTIMECONFIG = {
    "runtimeOptions": {
        "includedFrameworks": [
            {"name": "Microsoft.NETCore.App", "version": "8.0.0"},
        ]
    }
}
CHECK_BUNDLE_BAT = (
    "@echo off\r\n"
    "chcp 65001 >nul\r\n"
    "cd /d \"%~dp0\"\r\n"
    "python\\python.exe scripts\\verify_offline_bundle.py --extracted .\r\n"
)
START_DESKTOP_BAT = (
    "@echo off\r\n"
    "start \"\" \"%~dp0desktop\\app\\Laitp.Desktop.exe\"\r\n"
)


def bundle_files() -> dict[str, bytes]:
    """构造可通过结构校验的包内文件（内容只需存在且可解析，无需真实 SHA）。"""
    return {
        "README.txt": b"LAITP offline bundle\r\n",
        "check-bundle.bat": CHECK_BUNDLE_BAT.encode("utf-8"),
        "start-desktop.bat": START_DESKTOP_BAT.encode("utf-8"),
        RUNTIMECONFIG_PATH: json.dumps(
            SELF_CONTAINED_RUNTIMECONFIG, ensure_ascii=False
        ).encode("utf-8"),
        "desktop/app/coreclr.dll": b"coreclr-runtime",
        "desktop/app/hostfxr.dll": b"hostfxr-runtime",
    }


def bundle_manifest(
    paths: tuple[str, ...] = CORE_PATHS,
    format_version: str = BUNDLE_FORMAT,
) -> dict:
    """构造 manifest.json：components 文件列表 + 包身份信息。"""
    return {
        "format": format_version,
        "created_at": "2026-11-20T00:00:00+00:00",
        "root": "laitp",
        "total_bytes": 1,
        "components": [
            {
                "name": "desktop",
                "source": "desktop",
                "files": [
                    {"path": path, "size": 1, "sha256": "0" * 64}
                    for path in paths
                ],
            }
        ],
    }


def write_bundle(
    tmp_path: Path,
    files: dict[str, bytes] | None = None,
    manifest: dict | None = None,
) -> Path:
    """把文件与 manifest 写成小 ZIP，默认即一个结构合法的精简包。"""
    entries = bundle_files() if files is None else dict(files)
    manifest_data = bundle_manifest() if manifest is None else manifest
    entries["manifest.json"] = json.dumps(
        manifest_data, ensure_ascii=False
    ).encode("utf-8")
    bundle = tmp_path / "laitp-offline-lean.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return bundle


def test_valid_bundle_structure_passes(tmp_path: Path) -> None:
    module = load_check_state()
    bundle = write_bundle(tmp_path)

    result = module.check_bundle_structure(bundle)

    assert result["checked"] is True
    assert result["problems"] == []
    assert result["notes"] == []
    assert "ZIP 结构/自包含/启动脚本通过" in result["detail"]
    assert "manifest 3 个文件" in result["detail"]


def test_missing_coreclr_is_reported(tmp_path: Path) -> None:
    module = load_check_state()
    files = bundle_files()
    files.pop("desktop/app/coreclr.dll")
    bundle = write_bundle(
        tmp_path,
        files=files,
        manifest=bundle_manifest((RUNTIMECONFIG_PATH, "desktop/app/hostfxr.dll")),
    )

    result = module.check_bundle_structure(bundle)

    assert result["problems"] == ["离线包结构异常：缺少 desktop/app/coreclr.dll"]


def test_missing_runtimeconfig_is_reported(tmp_path: Path) -> None:
    module = load_check_state()
    files = bundle_files()
    files.pop(RUNTIMECONFIG_PATH)
    bundle = write_bundle(
        tmp_path,
        files=files,
        manifest=bundle_manifest(("desktop/app/coreclr.dll", "desktop/app/hostfxr.dll")),
    )

    result = module.check_bundle_structure(bundle)

    assert result["problems"] == [
        f"离线包结构异常：缺少 {RUNTIMECONFIG_PATH}"
    ]


def test_framework_dependent_runtimeconfig_is_reported(tmp_path: Path) -> None:
    module = load_check_state()
    files = bundle_files()
    files[RUNTIMECONFIG_PATH] = json.dumps(
        {"runtimeOptions": {"framework": {"name": "Microsoft.WindowsDesktop.App"}}}
    ).encode("utf-8")
    bundle = write_bundle(tmp_path, files=files)

    result = module.check_bundle_structure(bundle)

    joined = "；".join(result["problems"])
    assert "桌面程序不是自包含发布" in joined
    assert "includedFrameworks" in joined


def test_manifest_path_missing_from_zip_is_reported(tmp_path: Path) -> None:
    module = load_check_state()
    bundle = write_bundle(
        tmp_path,
        manifest=bundle_manifest(CORE_PATHS + ("desktop/app/missing-file.txt",)),
    )

    result = module.check_bundle_structure(bundle)

    joined = "；".join(result["problems"])
    assert "manifest 列出的 1 个文件不在 ZIP 中" in joined
    assert "desktop/app/missing-file.txt" in joined


def test_unregistered_zip_entry_is_reported(tmp_path: Path) -> None:
    module = load_check_state()
    files = bundle_files()
    files["desktop/app/unlisted.txt"] = b"extra"
    bundle = write_bundle(tmp_path, files=files)

    result = module.check_bundle_structure(bundle)

    joined = "；".join(result["problems"])
    assert "未在 manifest 登记的条目" in joined
    assert "desktop/app/unlisted.txt" in joined


def test_manifest_format_mismatch_is_reported(tmp_path: Path) -> None:
    module = load_check_state()
    bundle = write_bundle(
        tmp_path, manifest=bundle_manifest(format_version="laitp-offline-bundle-0.9")
    )

    result = module.check_bundle_structure(bundle)

    assert any(
        "format" in problem and BUNDLE_FORMAT in problem
        for problem in result["problems"]
    )


@pytest.mark.parametrize(
    ("bat_content", "expected"),
    [
        (
            "@echo off\r\npython\\python.exe scripts\\verify_offline_bundle.py\r\n",
            "缺少 chcp 65001",
        ),
        (
            "@echo off\r\nchcp 65001 >nul\r\npython\\python.exe run.py\r\n",
            "缺少 scripts\\verify_offline_bundle.py",
        ),
    ],
)
def test_check_bundle_script_content_is_validated(
    tmp_path: Path, bat_content: str, expected: str
) -> None:
    module = load_check_state()
    files = bundle_files()
    files["check-bundle.bat"] = bat_content.encode("utf-8")

    result = module.check_bundle_structure(write_bundle(tmp_path, files=files))

    assert len(result["problems"]) == 1
    assert expected in result["problems"][0]


def test_start_desktop_wrong_target_is_reported(tmp_path: Path) -> None:
    module = load_check_state()
    files = bundle_files()
    files["start-desktop.bat"] = (
        "@echo off\r\n"
        "start \"\" \"%~dp0desktop\\src\\bin\\Debug\\Laitp.Desktop.exe\"\r\n"
    ).encode("utf-8")

    result = module.check_bundle_structure(write_bundle(tmp_path, files=files))

    assert len(result["problems"]) == 1
    assert "start-desktop.bat 未指向包内" in result["problems"][0]
    assert "Laitp.Desktop.exe" in result["problems"][0]


def test_missing_bundle_skips_without_problem(tmp_path: Path) -> None:
    module = load_check_state()

    result = module.check_bundle_structure(tmp_path / "missing.zip")

    assert result["checked"] is False
    assert result["problems"] == []
    assert len(result["notes"]) == 1
    assert "跳过 ZIP 结构检查（不判失败）" in result["notes"][0]


def test_broken_zip_is_reported(tmp_path: Path) -> None:
    module = load_check_state()
    bundle = tmp_path / "broken.zip"
    bundle.write_bytes(b"not a zip file")

    result = module.check_bundle_structure(bundle)

    assert result["checked"] is True
    assert any("无法作为 ZIP 打开" in problem for problem in result["problems"])
