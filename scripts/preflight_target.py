"""目标机验收前环境预检（只读，不启动界面、不做 UI 自动化）。

用途：在解压后的离线包目录（或 ZIP 文件）上先跑一遍，提前发现“目标机环境不适合
直接开始 11 环节验收”的问题，例如不是 64 位 Windows、路径过长、磁盘不足、
管理员权限、包文件缺失或 SHA 不符。

结论分级：
- blocker：不满足会直接影响验收/使用（退出码 1）；
- warn：建议处理或记录，但不阻塞（退出码 0）。
本工具不替代 ``run_acceptance.ps1`` 的 11 环节验收，也不证明界面/模型/摄像头可用。
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import platform
import shutil
import sys
from pathlib import Path

MIN_DISK_FREE_BYTES = 1024 * 1024 * 1024
RECOMMENDED_DISK_FREE_BYTES = 2 * 1024 * 1024 * 1024
WARN_ROOT_PATH_LENGTH = 90
MAX_ROOT_PATH_LENGTH = 120
REQUIRED_ROOT_FILES = ("start-desktop.bat", "check-bundle.bat")


MIN_MEMORY_BYTES = 2 * 1024**3
RECOMMENDED_MEMORY_BYTES = 4 * 1024**3


def check_memory(total_bytes: int) -> dict:
    if total_bytes < MIN_MEMORY_BYTES:
        return {
            "id": "memory",
            "status": "blocker",
            "detail": f"物理内存 {total_bytes / 1024**3:.1f} GiB，低于最低 2 GiB",
        }
    if total_bytes < RECOMMENDED_MEMORY_BYTES:
        return {
            "id": "memory",
            "status": "warn",
            "detail": f"物理内存 {total_bytes / 1024**3:.1f} GiB，建议 4 GiB 以上",
        }
    return {
        "id": "memory",
        "status": "pass",
        "detail": f"物理内存 {total_bytes / 1024**3:.1f} GiB",
    }


def available_memory_bytes() -> int | None:
    try:
        import psutil

        return int(psutil.virtual_memory().total)
    except (ImportError, OSError):
        return None


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return False


def long_paths_enabled() -> bool | None:
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\FileSystem",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "LongPathsEnabled")
            return bool(int(value))
    except (ImportError, OSError, ValueError):
        return None


def console_code_page() -> int | None:
    try:
        return int(ctypes.windll.kernel32.GetConsoleCP())  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return None


def check_platform(system: str, machine: str, admin: bool) -> list[dict]:
    checks: list[dict] = []
    if system != "Windows":
        checks.append(
            {"id": "platform", "status": "blocker", "detail": f"当前系统不是 Windows：{system}"}
        )
    elif machine.lower() not in ("amd64", "x86_64", "arm64"):
        checks.append(
            {"id": "platform", "status": "blocker", "detail": f"不是 64 位环境：{machine}"}
        )
    else:
        checks.append(
            {"id": "platform", "status": "pass", "detail": f"Windows / {machine}"}
        )
    if admin:
        checks.append(
            {
                "id": "privilege",
                "status": "warn",
                "detail": "当前为管理员进程；正式验收应在普通用户（非提权）下进行",
            }
        )
    else:
        checks.append({"id": "privilege", "status": "pass", "detail": "非管理员进程"})
    return checks


def check_path_length(root: Path) -> dict:
    length = len(str(root))
    if length > MAX_ROOT_PATH_LENGTH:
        status = "blocker"
        detail = f"包根路径 {length} 字符，超过建议上限 {MAX_ROOT_PATH_LENGTH}；请解压到更短路径"
    elif length > WARN_ROOT_PATH_LENGTH:
        status = "warn"
        detail = f"包根路径 {length} 字符，偏长（建议 ≤ {WARN_ROOT_PATH_LENGTH}）"
    else:
        status = "pass"
        detail = f"包根路径 {length} 字符"
    return {"id": "root-path-length", "status": status, "detail": detail}


def check_disk_free(free_bytes: int) -> dict:
    if free_bytes < MIN_DISK_FREE_BYTES:
        return {
            "id": "disk-free",
            "status": "blocker",
            "detail": f"剩余空间 {free_bytes / 1024**3:.2f} GiB，低于最低 1 GiB",
        }
    if free_bytes < RECOMMENDED_DISK_FREE_BYTES:
        return {
            "id": "disk-free",
            "status": "warn",
            "detail": f"剩余空间 {free_bytes / 1024**3:.2f} GiB，建议预留 2 GiB 以上",
        }
    return {
        "id": "disk-free",
        "status": "pass",
        "detail": f"剩余空间 {free_bytes / 1024**3:.2f} GiB",
    }


def check_root_files(root: Path) -> dict:
    missing = [name for name in REQUIRED_ROOT_FILES if not (root / name).is_file()]
    if missing:
        return {
            "id": "package-root",
            "status": "blocker",
            "detail": "包根缺少文件：" + "、".join(missing),
        }
    exe = root / "desktop" / "app" / "Laitp.Desktop.exe"
    if not exe.is_file():
        return {
            "id": "package-root",
            "status": "blocker",
            "detail": "缺少 desktop/app/Laitp.Desktop.exe",
        }
    return {"id": "package-root", "status": "pass", "detail": "启动脚本与桌面程序存在"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_sha_from_file(zip_path: Path, explicit: str | None) -> tuple[str | None, str]:
    if explicit:
        return explicit.strip().lower(), "--expected-sha256"
    candidate = zip_path.with_suffix(zip_path.suffix + ".sha256")
    if candidate.is_file():
        text = candidate.read_text(encoding="utf-8").strip().split()
        if text:
            return text[0].lower(), str(candidate.name)
    return None, "无"


def check_bundle_sha(zip_path: Path, explicit_sha: str | None) -> dict:
    expected, source = expected_sha_from_file(zip_path, explicit_sha)
    actual = sha256_file(zip_path)
    if expected is None:
        return {
            "id": "bundle-sha256",
            "status": "warn",
            "detail": f"未提供期望 SHA（来源：{source}），实际 {actual[:16]}…",
        }
    if actual == expected:
        return {"id": "bundle-sha256", "status": "pass", "detail": f"SHA-256 匹配（{source}）"}
    return {
        "id": "bundle-sha256",
        "status": "blocker",
        "detail": f"SHA-256 不匹配：期望 {expected[:16]}…，实际 {actual[:16]}…",
    }


def check_long_paths(enabled: bool | None) -> dict:
    if enabled is True:
        return {"id": "long-paths", "status": "pass", "detail": "LongPathsEnabled=1"}
    if enabled is False:
        return {
            "id": "long-paths",
            "status": "warn",
            "detail": "LongPathsEnabled=0；包路径保持在 120 字符内通常仍可用，建议开启或使用短路径",
        }
    return {"id": "long-paths", "status": "warn", "detail": "无法读取 LongPathsEnabled"}


def check_console_code_page(code_page: int | None) -> dict:
    if code_page is None:
        return {"id": "console-code-page", "status": "warn", "detail": "无法读取控制台代码页"}
    if code_page in (936, 65001):
        return {
            "id": "console-code-page",
            "status": "pass",
            "detail": f"控制台代码页 {code_page}（中文 Windows 常见值）",
        }
    return {
        "id": "console-code-page",
        "status": "warn",
        "detail": f"控制台代码页 {code_page}；一键验收会自动切到 UTF-8，中文输出可能显示异常",
    }


def build_report(root: Path | None, zip_path: Path | None, explicit_sha: str | None) -> dict:
    checks: list[dict] = []
    checks.extend(check_platform(platform.system(), platform.machine(), is_admin()))
    target_path = root if root is not None else zip_path
    if target_path is None:
        raise SystemExit("必须提供 --root 或 --zip")
    checks.append(check_path_length(target_path))
    try:
        usage = shutil.disk_usage(target_path.parent if target_path.is_file() else target_path)
        checks.append(check_disk_free(usage.free))
    except OSError as exc:
        checks.append({"id": "disk-free", "status": "warn", "detail": f"无法读取磁盘空间：{exc}"})
    if root is not None:
        checks.append(check_root_files(root))
    if zip_path is not None:
        checks.append(check_bundle_sha(zip_path, explicit_sha))
    memory = available_memory_bytes()
    if memory is not None:
        checks.append(check_memory(memory))
    else:
        checks.append({"id": "memory", "status": "warn", "detail": "无法读取内存信息"})
    checks.append(check_long_paths(long_paths_enabled()))
    checks.append(check_console_code_page(console_code_page()))
    blockers = [item for item in checks if item["status"] == "blocker"]
    warnings = [item for item in checks if item["status"] == "warn"]
    return {
        "format": "laitp-target-preflight-1.0",
        "checked_at": __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds"),
        "target": str(target_path),
        "overall": "blocked" if blockers else "ready-for-acceptance-attempt",
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
        "note": "仅检查本机环境与包完整性；不代表 11 环节验收通过，也不替代目标机验收。",
        "checks": checks,
    }


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    parser = argparse.ArgumentParser(
        description="目标机验收前环境预检（只读；不做界面自动化，不代表验收通过）"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--root", type=Path, help="解压后的包根目录")
    group.add_argument("--zip", type=Path, help="离线包 ZIP（校验 SHA 与路径/磁盘）")
    parser.add_argument("--expected-sha256", help="期望的 ZIP SHA-256（否则读取 .sha256 文件）")
    parser.add_argument("--output", type=Path, help="结果 JSON 输出路径")
    args = parser.parse_args()

    report = build_report(args.root, args.zip, args.expected_sha256)
    print(f"总体：{report['overall']}（blocker={report['blocker_count']}，warn={report['warning_count']}）")
    for item in report["checks"]:
        print(f"- [{item['status']}] {item['id']}：{item['detail']}")
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output = args.output if args.output.is_absolute() else (Path.cwd() / args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
        print(f"已写入 {output}")
    return 0 if report["overall"] == "ready-for-acceptance-attempt" else 1


if __name__ == "__main__":
    raise SystemExit(main())
