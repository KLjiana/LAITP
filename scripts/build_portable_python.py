"""构建可随离线包分发的便携 Python（开发期脚本）。

从当前 venv 的基础解释器与 site-packages 复制出独立目录，剔除仅开发期需要
的文件（静态库 .lib、头文件、测试包、pip 等），并验证关键依赖可导入、可推理。

用法：
    .venv\\Scripts\\python.exe scripts\\build_portable_python.py
输出：dist/python-portable/（已忽略，不提交）
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SKIP_DIR_NAMES = {
    "__pycache__",
    "include",
    "pip",
    "setuptools",
    "pkg_resources",
    "wheel",
}
SKIP_SUFFIXES = {".lib", ".pdb", ".obj", ".exp", ".a", ".h", ".hpp", ".c", ".cpp", ".md"}
# torch.testing 被 torch.autograd 导入，不能删除；这里只剔除头文件、cmake 共享数据与
# 基础解释器的测试包。
SKIP_RELATIVE_PREFIXES = ("torch/include", "torch/share", "Lib/test", "Lib/idlelib")


def copy_filtered(source: Path, target: Path) -> tuple[int, int]:
    copied = 0
    skipped = 0
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        parts = set(relative.parts)
        if parts & SKIP_DIR_NAMES:
            skipped += 1
            continue
        relative_text = relative.as_posix()
        if any(relative_text.startswith(prefix) for prefix in SKIP_RELATIVE_PREFIXES):
            skipped += 1
            continue
        if path.is_dir():
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            skipped += 1
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        copied += 1
    return copied, skipped


def total_size(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="构建便携 Python")
    parser.add_argument("--output", default="dist/python-portable")
    parser.add_argument("--python-home", default=None, help="基础解释器目录；默认读取 .venv/pyvenv.cfg")
    parser.add_argument("--site-packages", default=None)
    parser.add_argument("--skip-import-check", action="store_true")
    args = parser.parse_args(argv)

    venv = ROOT / ".venv"
    config = {}
    for line in (venv / "pyvenv.cfg").read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            config[key.strip()] = value.strip()
    python_home = Path(args.python_home or config["home"])
    site_packages = Path(args.site_packages or venv / "Lib" / "site-packages")
    output = Path(args.output)
    output = output if output.is_absolute() else ROOT / output

    if not (python_home / "python.exe").is_file():
        print(json.dumps({"ok": False, "error": f"基础解释器不存在：{python_home}"}, ensure_ascii=False))
        return 1

    shutil.rmtree(output, ignore_errors=True)
    output.mkdir(parents=True)
    base_files, base_skipped = copy_filtered(python_home, output)
    print(f"基础解释器：复制 {base_files} 个文件，跳过 {base_skipped} 个（{total_size(output)} 字节）")

    lib_site = output / "Lib" / "site-packages"
    if lib_site.exists():
        shutil.rmtree(lib_site)
    lib_site.mkdir(parents=True)
    site_files, site_skipped = copy_filtered(site_packages, lib_site)
    print(f"site-packages：复制 {site_files} 个文件，跳过 {site_skipped} 个")

    size = total_size(output)
    interpreter = output / "python.exe"
    checks: list[str] = []
    failures: list[str] = []
    if not args.skip_import_check:
        probe = subprocess.run(
            [
                str(interpreter), "-c",
                "import torch, torchvision, onnxruntime, numpy, PIL, jsonschema; "
                "print(torch.__version__, torchvision.__version__, onnxruntime.__version__)",
            ],
            cwd=str(output),
            capture_output=True,
        )
        if probe.returncode == 0:
            checks.append("依赖导入成功：" + probe.stdout.decode("utf-8", "replace").strip())
        else:
            failures.append("依赖导入失败：" + probe.stderr.decode("utf-8", "replace")[-800:])

        demo = ROOT / "artifacts/real-data/fashion-project/exports/art-run-real-0001/model-package"
        image = ROOT / "artifacts/real-data/sources/T恤/batch-test/test-000.png"
        if demo.is_dir() and image.is_file():
            predict = subprocess.run(
                [
                    str(interpreter), "-m", "backend.runtime.worker", "predict",
                    "--package", str(demo),
                    "--image", str(image),
                    "--request-id", "req-portable",
                    "--project-id", "proj-portable",
                    "--task-id", "task-portable",
                ],
                cwd=str(ROOT),
                capture_output=True,
                env={"PYTHONPATH": str(ROOT)},
            )
            terminal = [
                line for line in predict.stdout.decode("utf-8").splitlines()
                if '"message_type":"result"' in line.replace(" ", "")
            ]
            if predict.returncode == 0 and terminal:
                checks.append("便携 Python 推理成功")
            else:
                failures.append(
                    "便携 Python 推理失败：" + predict.stderr.decode("utf-8", "replace")[-800:]
                )
        else:
            checks.append("无演示模型，跳过推理检查")

    # 探测导入/推理会在 site-packages 生成 __pycache__；清掉以保证离线包摘要稳定。
    removed = 0
    for cache in [path for path in output.rglob("__pycache__") if path.is_dir()]:
        shutil.rmtree(cache, ignore_errors=True)
        removed += 1
    size = total_size(output)
    checks.append(f"已清理 __pycache__（{removed} 个目录）")

    summary = {
        "ok": not failures,
        "output": str(output),
        "size_bytes": size,
        "size_mib": round(size / (1024 * 1024), 1),
        "files": sum(1 for path in output.rglob("*") if path.is_file()),
        "python_home": str(python_home),
        "site_packages": str(site_packages),
        "checks": checks,
        "failures": failures,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
