"""项目归档：把项目目录打包为单个 ZIP，或从 ZIP 恢复项目。

用法：
    python scripts/project_archive.py export --project <project.json 或项目目录> --output <zip>
    python scripts/project_archive.py import --archive <zip> --target <目标目录>
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

PROJECT_FILE = "project.json"


def resolve_project_root(project: str | Path) -> Path:
    path = Path(project)
    if path.is_file():
        return path.parent
    return path


def export_project(project: str | Path, output: str | Path) -> dict:
    root = resolve_project_root(project)
    project_file = root / PROJECT_FILE
    if not project_file.is_file():
        raise FileNotFoundError(f"项目文件不存在：{project_file}")
    json.loads(project_file.read_text(encoding="utf-8"))

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.NamedTemporaryFile(
        prefix="laitp-project-archive-", suffix=".zip", delete=False
    )
    temporary.close()
    try:
        with zipfile.ZipFile(temporary.name, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(root).as_posix())
        shutil.move(temporary.name, output_path)
    finally:
        Path(temporary.name).unlink(missing_ok=True)
    return {
        "ok": True,
        "archive": str(output_path),
        "files": len([
            path for path in root.rglob("*") if path.is_file()
        ]),
    }


def import_project(archive: str | Path, target: str | Path) -> dict:
    archive_path = Path(archive)
    target_path = Path(target)
    if not archive_path.is_file():
        raise FileNotFoundError(f"归档不存在：{archive_path}")
    if target_path.exists() and any(target_path.iterdir()):
        raise ValueError(f"目标目录已存在且非空：{target_path}")

    with zipfile.ZipFile(archive_path) as bundle:
        for name in bundle.namelist():
            candidate = Path(name)
            if candidate.is_absolute() or ".." in candidate.parts:
                raise ValueError(f"归档包含不安全路径：{name}")
        bundle.extractall(target_path)

    project_file = target_path / PROJECT_FILE
    if not project_file.is_file():
        shutil.rmtree(target_path, ignore_errors=True)
        raise ValueError("归档内缺少 project.json")
    json.loads(project_file.read_text(encoding="utf-8"))
    return {"ok": True, "project": str(project_file)}


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    parser = argparse.ArgumentParser(description="LAITP 项目归档导出/导入")
    sub = parser.add_subparsers(dest="command", required=True)
    exporter = sub.add_parser("export")
    exporter.add_argument("--project", required=True)
    exporter.add_argument("--output", required=True)
    importer = sub.add_parser("import")
    importer.add_argument("--archive", required=True)
    importer.add_argument("--target", required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "export":
            payload = export_project(args.project, args.output)
        else:
            payload = import_project(args.archive, args.target)
    except Exception as error:  # 命令行工具统一输出错误 JSON
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
