"""构建 M2 离线分发包（开发期打包脚本）。

把后端源码、契约 Schema、配置、文档、预训练权重、离线 wheel、桌面构建产物与
演示模型打包为可校验的 ZIP，并生成逐文件 SHA-256 清单。

注意：本脚本只负责“打包 + 清单”，不负责在目标机器上安装运行时；目标机验收见
docs/offline-bundle.md 的说明。产物写入 dist/（已忽略，不提交）。
"""

from __future__ import annotations

import sys

import argparse
import hashlib
import json
import shutil
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TREE_COPY_ATTEMPTS = 3
TREE_COPY_RETRY_DELAY_SECONDS = 0.5
BUNDLE_FORMAT = "laitp-offline-bundle-1.0"

COPY_DIRS = (
    ("backend", "backend"),
    ("schemas", "schemas"),
    ("configs", "configs"),
    ("docs", "docs"),
)
COPY_FILES = (
    ("requirements.txt", "requirements.txt"),
    ("requirements-dev.txt", "requirements-dev.txt"),
    ("pyproject.toml", "pyproject.toml"),
)
WEIGHTS = (
    ("artifacts/weights/mobilenet_v3_small-047dcff4.pth",
     "artifacts/weights/mobilenet_v3_small-047dcff4.pth"),
)
BUNDLE_SCRIPTS = (
    ("scripts/verify_offline_bundle.py", "scripts/verify_offline_bundle.py"),
    ("scripts/measure_startup.ps1", "scripts/measure_startup.ps1"),
    ("scripts/ui_smoke.ps1", "scripts/ui_smoke.ps1"),
    ("scripts/ui_flow.ps1", "scripts/ui_flow.ps1"),
    ("scripts/ui_camera.ps1", "scripts/ui_camera.ps1"),
    ("scripts/ui_preview_stability.ps1", "scripts/ui_preview_stability.ps1"),
    ("scripts/ui_create_import.ps1", "scripts/ui_create_import.ps1"),
    ("scripts/ui_restore.ps1", "scripts/ui_restore.ps1"),
    ("scripts/ui_export_history.ps1", "scripts/ui_export_history.ps1"),
    ("scripts/ui_edit.ps1", "scripts/ui_edit.ps1"),
    ("scripts/project_archive.py", "scripts/project_archive.py"),
    ("scripts/batch_history_export.py", "scripts/batch_history_export.py"),
    ("scripts/dataset_report.py", "scripts/dataset_report.py"),
    ("scripts/preflight_target.py", "scripts/preflight_target.py"),
    ("scripts/run_acceptance.ps1", "scripts/run_acceptance.ps1"),
    ("scripts/make_demo_dataset.py", "scripts/make_demo_dataset.py"),
)
DEMO_PACKAGE = "artifacts/real-data/fashion-project/exports/art-run-real-0001/model-package"
DEMO_RUN = "artifacts/real-data/fashion-project/runs/run-real-0001"
DEMO_SOURCE_IMAGE = "artifacts/real-data/sources/T恤/batch-test/test-000.png"
DESKTOP_RELEASE = "desktop/src/Laitp.Desktop/bin/Release/net8.0-windows10.0.19041.0"
WHEELS = "vendor/wheels"
WHEELS_SHA = "vendor/wheels.sha256"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_tree_with_retry(
    source: Path,
    destination: Path,
    attempts: int = TREE_COPY_ATTEMPTS,
    delay_seconds: float = TREE_COPY_RETRY_DELAY_SECONDS,
) -> None:
    """复制目录；对杀毒/索引等导致的瞬时文件错误做有限重试。"""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            shutil.copytree(
                source,
                destination,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            return
        except (FileNotFoundError, PermissionError, OSError) as error:
            last_error = error
            if destination.exists():
                shutil.rmtree(destination, ignore_errors=True)
            if attempt < attempts:
                time.sleep(delay_seconds * attempt)
    assert last_error is not None
    raise last_error


def add_tree(
    staging: Path,
    source: Path,
    target: str,
    components: list[dict],
    post_copy=None,
) -> None:
    destination = staging / target
    if not source.exists():
        return
    _copy_tree_with_retry(source, destination)
    if post_copy is not None:
        post_copy(destination)
    files = []
    for path in sorted(destination.rglob("*")):
        if path.is_file():
            files.append(
                {
                    "path": path.relative_to(staging).as_posix(),
                    "size": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    components.append(
        {
            "name": target,
            "source": source.relative_to(ROOT).as_posix(),
            "files": files,
            "bytes": sum(item["size"] for item in files),
        }
    )


def write_batch_script(path: Path, text: str) -> None:
    """写批处理脚本：文本已按 CRLF 组织，用字节写入避免 Windows 文本模式
    再转换出 \\r\\r\\n（CMD 仍能执行，但会在编辑/自动检查中留下多余 CR）。"""
    normalized = text.replace("\\r\\n", "\\n").replace("\\n", "\\r\\n")
    path.write_bytes(normalized.encode("utf-8"))


def sanitize_demo_run(run_dir: Path) -> None:
    """把演示训练记录中的开发机绝对路径改写为包内相对位置。"""
    config_path = run_dir / "config.json"
    if not config_path.is_file():
        return
    data = json.loads(config_path.read_text(encoding="utf-8"))
    data["dataset_manifest"] = "demo/run/dataset-manifest.json"
    data["dataset_root"] = "demo/run/data"
    weights = data.get("weights")
    if isinstance(weights, dict):
        weights["path"] = "demo/run/weights-not-bundled.pth"
    config_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    artifact_path = run_dir / "training-artifact.json"
    if not artifact_path.is_file():
        return
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    files = artifact.get("files")
    if isinstance(files, dict) and isinstance(files.get("config.json"), dict):
        files["config.json"]["sha256"] = sha256_file(config_path)
        files["config.json"]["size_bytes"] = config_path.stat().st_size
        artifact_path.write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


def add_file(staging: Path, source: Path, target: str, components: list[dict]) -> None:
    if not source.is_file():
        return
    destination = staging / target
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    components.append(
        {
            "name": target,
            "source": source.relative_to(ROOT).as_posix(),
            "files": [
                {
                    "path": target,
                    "size": destination.stat().st_size,
                    "sha256": sha256_file(destination),
                }
            ],
            "bytes": destination.stat().st_size,
        }
    )


BINARY_SUFFIXES = (
    ".zip", ".dll", ".pyd", ".whl", ".pt", ".pth", ".onnx", ".pb", ".so",
    ".exe", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".gz", ".tar",
)
DEV_PATH_SCAN_INCLUDED_PREFIXES = (
    "backend/", "scripts/", "configs/", "schemas/", "demo/", "desktop/",
)
DEV_PATH_SCAN_EXCLUDED_FILES = (
    "README.md",
    "manifest.json",
    # 该脚本自身定义开发机路径标记常量，需豁免
    "scripts/build_offline_bundle.py",
    "scripts/verify_offline_bundle.py",
)


def development_path_markers() -> list[str]:
    """返回构建期需要拒绝的“开发机绝对路径”标记（去重、忽略大小写）。"""
    markers: list[str] = []
    for candidate in (ROOT, Path.home()):
        for form in (str(candidate), candidate.as_posix()):
            markers.append(form)
    markers.extend(["/d/project", "/mnt/d/project"])
    # JSON/Python 源码中开发机路径常被双反斜杠转义，需同时检查该形式。
    for marker in list(markers):
        if "\\" in marker:
            markers.append(marker.replace("\\", "\\\\"))
    unique: list[str] = []
    for marker in markers:
        if marker and marker.lower() not in [item.lower() for item in unique]:
            unique.append(marker)
    return unique


def find_development_path_references(staging: Path) -> list[str]:
    """扫描暂存包内文本文件是否包含开发机绝对路径；docs/ 与 README 豁免。"""
    markers = [marker.lower() for marker in development_path_markers()]
    problems: list[str] = []
    for path in sorted(staging.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(staging).as_posix()
        is_root_file = "/" not in relative
        if not is_root_file and not relative.startswith(DEV_PATH_SCAN_INCLUDED_PREFIXES):
            continue
        if relative in DEV_PATH_SCAN_EXCLUDED_FILES:
            continue
        if path.suffix.lower() in BINARY_SUFFIXES:
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        for marker in markers:
            if marker in content:
                problems.append(f"{relative} 含开发机路径 {marker}")
                break
    return problems


def write_readme(staging: Path, self_contained: bool, python_embedded: bool) -> None:
    desktop_line = (
        "desktop/app/    WPF 桌面程序（自包含构建，无需预装 .NET 运行时）"
        if self_contained
        else "desktop/app/    WPF 桌面程序（框架依赖构建，需要 .NET 8 Desktop Runtime）"
    )
    runtime_line = (
        "无需预装 .NET（desktop/app 为自包含构建）"
        if self_contained
        else "- .NET 8 Desktop Runtime（desktop/app 为框架依赖构建）"
    )
    python_line = (
        "python/         便携 Python 3.12（含 torch/onnxruntime 等运行依赖）"
        if python_embedded
        else "（未包含 Python，需目标机自备 Python 3.12 与依赖）"
    )
    python_requirement = (
        "- 无需预装 Python（包内 python/ 已含依赖；start-desktop.bat 会自动设置 LAITP_PYTHON）"
        if python_embedded
        else "- Python 3.12（未内置解释器；需安装并 pip install -r requirements.txt）"
    )
    start_line = (
        "start-desktop.bat  双击启动桌面程序（自动设置 LAITP_PYTHON）\n"
        if python_embedded
        else ""
    )
    text = f"""LAITP 离线分发包（开发构建）
================================

内容
----
backend/        Python 后端（契约校验、分类训练/导出、推理、任务协议、项目管理）
schemas/        JSON Schema
configs/        权重与验收配置
docs/           开发文档（老师请先看 docs/teacher-quickstart.md）
README.md       项目总览、快速开始与文档索引（开发/接手入口）
vendor/         离线 wheel（如包含）
artifacts/      预训练权重
{python_line}
{desktop_line}
demo/           演示模型包、训练运行与一张测试图片
{start_line}
运行前提（当前构建）
--------------------
- Windows x64
{python_requirement}
{runtime_line}

快速验证
--------
python/python.exe -m backend.runtime.worker predict ^
  --package demo/model-package --image demo/test.png ^
  --request-id req-demo --project-id proj-demo --task-id task-demo

python/python.exe -m backend.classification report --run demo/run

解压后自检
----------
双击 check-bundle.bat，或运行：
python/python.exe scripts/verify_offline_bundle.py --extracted .

该命令会校验清单摘要、包内 Python 依赖、推理、训练报告、桌面启动与首次运行自检。
需要摄像头时还可运行：powershell -ExecutionPolicy Bypass -File scripts/ui_camera.ps1 -Exe desktop/app/Laitp.Desktop.exe -ProjectParent ./自检项目 -LaitpHome . -LaitpPython python/python.exe

scripts/ 内附带的界面自动化脚本（均可用包内组件运行）：
  ui_smoke.ps1 / ui_flow.ps1 / ui_camera.ps1 / ui_preview_stability.ps1
  ui_create_import.ps1 / ui_restore.ps1 / ui_export_history.ps1 / ui_edit.ps1
通用参数：-Exe desktop/app/Laitp.Desktop.exe -LaitpHome . -LaitpPython python/python.exe

一键验收（推荐目标机执行）：
powershell -ExecutionPolicy Bypass -File scripts/run_acceptance.ps1
该脚本依次执行包内摘要自检、窗口自检与启动耗时测量，并生成 acceptance-run.json
与 acceptance-report.md（含操作系统、用户/管理员、CPU、内存、磁盘余量与步骤结果，可直接作为目标机验收记录）。
加 -IncludeFlow 时还会生成演示数据并跑“新建项目→导入→训练→预测→批量预测”全流程。
再加 -IncludeExtended 时继续跑“训练→关闭重开→恢复→数据检查”的保存恢复流程。

清单
----
manifest.json 记录每个文件的 SHA-256；可用 scripts/verify_offline_bundle.py 校验。

限制
----
这是开发期打包脚本的产物，尚未验证目标机器、真正断网、普通用户权限与
完整“解压双击”课堂流程；详见 docs/offline-bundle.md。
"""
    (staging / "README.txt").write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    parser = argparse.ArgumentParser(description="构建 LAITP 离线分发包")
    parser.add_argument("--output", default=None, help="输出 ZIP 路径（默认 dist/laitp-offline-<日期>.zip）")
    parser.add_argument("--skip-wheels", action="store_true", help="不打包 vendor/wheels")
    parser.add_argument("--skip-demo", action="store_true", help="不打包演示模型包与运行")
    parser.add_argument("--skip-desktop", action="store_true", help="不打包桌面构建产物")
    parser.add_argument(
        "--desktop-dir",
        default=DESKTOP_RELEASE,
        help="桌面构建产物目录（默认框架依赖 Release 输出；可指向自包含 publish 目录）",
    )
    parser.add_argument(
        "--python-dir",
        default="dist/python-portable",
        help="便携 Python 目录（默认 dist/python-portable；不存在则不打包）",
    )
    parser.add_argument("--skip-python", action="store_true", help="不打包便携 Python")
    args = parser.parse_args(argv)

    output = (
        Path(args.output)
        if args.output
        else ROOT / "dist" / f"laitp-offline-{datetime.now():%Y%m%d}.zip"
    )
    output = output if output.is_absolute() else ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    components: list[dict] = []

    with tempfile.TemporaryDirectory(prefix="laitp-bundle-") as temporary:
        staging = Path(temporary) / "laitp"
        staging.mkdir()

        for source, target in COPY_DIRS:
            add_tree(staging, ROOT / source, target, components)
        for source, target in COPY_FILES:
            add_file(staging, ROOT / source, target, components)
        for source, target in BUNDLE_SCRIPTS:
            add_file(staging, ROOT / source, target, components)
        for source, target in WEIGHTS:
            add_file(staging, ROOT / source, target, components)
        if not args.skip_wheels:
            add_tree(staging, ROOT / WHEELS, "vendor/wheels", components)
            add_file(staging, ROOT / WHEELS_SHA, "vendor/wheels.sha256", components)
        desktop_dir = Path(args.desktop_dir)
        desktop_dir = desktop_dir if desktop_dir.is_absolute() else ROOT / desktop_dir
        self_contained = (desktop_dir / "hostfxr.dll").is_file()
        if not args.skip_desktop:
            add_tree(staging, desktop_dir, "desktop/app", components)

        python_dir = Path(args.python_dir)
        python_dir = python_dir if python_dir.is_absolute() else ROOT / python_dir
        python_embedded = (python_dir / "python.exe").is_file() and not args.skip_python
        if python_embedded:
            for cache in [path for path in python_dir.rglob("__pycache__") if path.is_dir()]:
                shutil.rmtree(cache, ignore_errors=True)
            add_tree(staging, python_dir, "python", components)
            write_batch_script(staging / "start-desktop.bat", 
                "@echo off\r\n"
                "setlocal\r\n"
                "set \"LAITP_PYTHON=%~dp0python\\python.exe\"\r\n"
                "start \"\" \"%~dp0desktop\\app\\Laitp.Desktop.exe\"\r\n",
            )
            write_batch_script(staging / "check-bundle.bat", 
                "@echo off\r\n"
                "chcp 65001 >nul\r\n"
                "cd /d \"%~dp0\"\r\n"
                "python\\python.exe scripts\\verify_offline_bundle.py --extracted .\r\n"
                "echo.\r\n"
                "pause\r\n",
            )
        if not args.skip_demo:
            add_tree(staging, ROOT / DEMO_PACKAGE, "demo/model-package", components)
            add_tree(
                staging,
                ROOT / DEMO_RUN,
                "demo/run",
                components,
                post_copy=sanitize_demo_run,
            )
            add_file(staging, ROOT / DEMO_SOURCE_IMAGE, "demo/test.png", components)

        write_readme(staging, self_contained, python_embedded)
        add_file(staging, ROOT / "README.md", "README.md", components)
        development_path_issues = find_development_path_references(staging)
        if development_path_issues:
            details = "\n".join(development_path_issues[:20])
            raise SystemExit(
                "离线包包含开发机绝对路径，构建中止（A13 回归检查）：\n" + details
            )
        total_bytes = sum(component["bytes"] for component in components)
        manifest = {
            "format": BUNDLE_FORMAT,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "root": "laitp",
            "components": components,
            "total_bytes": total_bytes,
            "environment": {
                "platform": "windows-x64",
                "python": "3.12（包内便携 Python）" if python_embedded else "3.12（需外置）",
                "python_embedded": python_embedded,
                "desktop_runtime": (
                    "自包含构建（无需预装 .NET 运行时）"
                    if self_contained
                    else ".NET 8 Desktop Runtime（框架依赖构建）"
                ),
                "desktop_self_contained": self_contained,
                "notes": [
                    "Python 解释器与依赖是否内置见 python_embedded",
                    "vendor/wheels 可用于离线安装/修复 Python 依赖",
                    "未做目标机器与真正断网验收",
                ],
            },
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        file_count = 1
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(staging.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(staging).as_posix())
                    file_count += 1

    size = output.stat().st_size
    digest = sha256_file(output)
    (output.with_suffix(output.suffix + ".sha256")).write_text(
        f"{digest}  {output.name}\n", encoding="utf-8"
    )
    summary = {
        "bundle": str(output),
        "size_bytes": size,
        "size_mib": round(size / (1024 * 1024), 1),
        "files": file_count,
        "payload_bytes": total_bytes,
        "sha256": digest,
        "components": [
            {"name": component["name"], "files": len(component["files"]),
             "bytes": component["bytes"]}
            for component in components
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
