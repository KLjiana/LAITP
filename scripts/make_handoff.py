"""生成交付交接目录：离线 ZIP、SHA-256、老师指引、验收清单与交接说明。

用法：
    .venv\\Scripts\\python.exe scripts\\make_handoff.py
    .venv\\Scripts\\python.exe scripts\\make_handoff.py --include-full --clean
"""

from __future__ import annotations

import argparse
import hashlib
import re
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COPY_DOCS = (
    "teacher-quickstart.md",
    "acceptance-card.md",
    "acceptance-checklist.md",
    "verification-evidence.md",
    "known-limitations.md",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_bundle(source: Path, output: Path) -> dict:
    digest = sha256_file(source)
    size = source.stat().st_size
    target = output / source.name
    if target.resolve() != source.resolve():
        shutil.copy2(source, target)
    (output / f"{source.name}.sha256").write_text(
        f"{digest}  {source.name}\n", encoding="utf-8"
    )
    return {"name": source.name, "size": size, "sha256": digest}


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    parser = argparse.ArgumentParser(description="生成 LAITP 交付交接目录")
    parser.add_argument("--zip", default="dist/laitp-offline-lean.zip")
    parser.add_argument("--full-zip", default="dist/laitp-offline-full.zip")
    parser.add_argument("--output", default="dist/handoff")
    parser.add_argument("--include-full", action="store_true", help="同时放入完整包（含 wheel）")
    parser.add_argument("--clean", action="store_true", help="先清空输出目录")
    args = parser.parse_args(argv)

    source = Path(args.zip)
    source = source if source.is_absolute() else ROOT / source
    if not source.is_file():
        print(json.dumps({"ok": False, "error": f"离线包不存在：{source}"}, ensure_ascii=False))
        return 1

    full_source = None
    if args.include_full:
        full_source = Path(args.full_zip)
        full_source = full_source if full_source.is_absolute() else ROOT / full_source
        if not full_source.is_file():
            print(
                json.dumps(
                    {"ok": False, "error": f"完整包不存在：{full_source}"},
                    ensure_ascii=False,
                )
            )
            return 1

    output = Path(args.output)
    output = output if output.is_absolute() else ROOT / output
    if output.exists() and args.clean:
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    lean = copy_bundle(source, output)
    full = copy_bundle(full_source, output) if full_source is not None else None

    copied: list[dict] = []
    readme = ROOT / "README.md"
    if readme.is_file():
        destination = output / "README.md"
        shutil.copy2(readme, destination)
        copied.append({"name": "README.md", "size": destination.stat().st_size,
                       "sha256": sha256_file(destination)})
    for name in COPY_DOCS:
        doc = ROOT / "docs" / name
        if not doc.is_file():
            continue
        destination = output / name
        shutil.copy2(doc, destination)
        copied.append({"name": name, "size": destination.stat().st_size,
                       "sha256": sha256_file(destination)})

    report = ROOT / "artifacts" / "acceptance-report-final.md"
    if report.is_file():
        destination = output / "acceptance-report-sample.md"
        content = report.read_text(encoding="utf-8")
        content = re.sub(r"^- 包目录：.*$", "- 包目录：（解压目录）", content, flags=re.M)
        destination.write_text(content, encoding="utf-8")
        copied.append({"name": "acceptance-report-sample.md",
                       "size": destination.stat().st_size,
                       "sha256": sha256_file(destination)})

    generated = time.strftime("%Y-%m-%d %H:%M:%S")
    # 交接说明里的“已知限制”日期取本次生成当天，避免每次生成都沿用旧日期。
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    full_block = ""
    if full is not None:
        full_block = f"""
完整包（含 wheel，可选）
------------------------
文件：{full['name']}
大小：{full['size']:,} 字节（约 {full['size'] / (1024 * 1024):.1f} MiB）
SHA-256：{full['sha256']}
用途：目标机首次部署或依赖修复（可用 vendor/wheels 重装依赖）。
"""
    guide = f"""LAITP 离线包交接说明
====================

生成时间：{generated}
离线包：{lean['name']}
大小：{lean['size']:,} 字节（约 {lean['size'] / (1024 * 1024):.1f} MiB）
SHA-256：{lean['sha256']}
{full_block}
使用方法
--------
1. 解压 {lean['name']} 到本机磁盘（中文/空格路径也可，避免只读目录或网络盘）。
2. 双击 start-desktop.bat 启动；首次启动会自动自检，状态显示“就绪（环境自检通过）”。
3. 双击 check-bundle.bat 可先做一次包内自检（清单摘要、推理、报告、桌面、自检）。
4. 日常使用请阅读 teacher-quickstart.md；目标机验收请按 acceptance-checklist.md 执行。

目录内容
--------
{lean['name']}            离线分发包（精简）
{lean['name']}.sha256     分发包校验值
{f"{full['name']}            完整包（含 wheel）" + chr(10) + f"{full['name']}.sha256     完整包校验值" + chr(10) if full else ""}README.md                项目总览、快速开始与文档索引
teacher-quickstart.md    老师快速上手
acceptance-card.md       目标机验收操作卡（一页版）
acceptance-checklist.md  目标机离线验收清单
verification-evidence.md 开发机验证命令与证据索引
known-limitations.md     已知限制与验收边界
{f"acceptance-report-sample.md 开发机一键验收报告样例" + chr(10) if report.is_file() else ""}handoff-manifest.json    本目录清单（文件、大小、SHA-256）

已知限制（{today}）
----------------------
- 尚未在干净 Windows 目标机、普通用户、真正断网环境完成验收。
- 摄像头自动化测试自 2026-11-18 起按要求停止；此前设备选择/拍照/连拍/预览在 DroidCam 虚拟摄像头验证，物理 HD Webcam 被禁用（Code 22），真实摄像头待人工验证。
- 无真实课堂采集数据；效果数字来自公开数据（Fashion-MNIST 子集）。
- K230/K210 板端部署未开始（缺硬件与转换工具链）。
"""
    (output / "交接说明.txt").write_text(guide, encoding="utf-8")

    manifest = {
        "generated_at": generated,
        "bundle": lean,
        "bundle_full": full,
        "documents": copied,
        "guide": "交接说明.txt",
        "notes": [
            "本目录用于交付/验收，不包含开发机 artifacts 证据文件",
            "重新验证后请重新运行 scripts/make_handoff.py 保持 SHA 一致",
        ],
    }
    (output / "handoff-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    summary = {
        "ok": True,
        "output": str(output),
        "bundle_bytes": lean["size"],
        "sha256": lean["sha256"],
        "full_sha256": full["sha256"] if full else None,
        "files": sorted(path.name for path in output.iterdir()),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
