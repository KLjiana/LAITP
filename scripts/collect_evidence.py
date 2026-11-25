"""收集目标机验收证据，打包为可回传的 ZIP。

用途：在目标机跑完 ``run_acceptance.ps1`` 与必要的人工记录后，把验收产物、
环境预检、数据体检与界面自动化结果打包成单个 ZIP，连同 ``evidence-manifest.json``
（每个文件的 SHA-256/大小）一起回传。**只打包已存在的文件**；缺项会写入清单的
``missing`` 列表，便于验收方核对“哪些证据没跑/没产出”。

本工具不运行验收、不修改被测包，也不代表验收通过。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_ARTIFACTS = (
    "artifacts/acceptance-run.json",
    "acceptance-report.md",
    "artifacts/preflight-target.json",
    "artifacts/startup-acceptance.json",
    "artifacts/ui-smoke-acceptance.json",
    "artifacts/ui-flow-acceptance.json",
    "artifacts/ui-create-import-acceptance.json",
    "artifacts/ui-restore-acceptance.json",
    "acceptance-demo/dataset-report.md",
    "acceptance-demo/batch-history.md",
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_evidence(root: Path) -> tuple[list[Path], list[str]]:
    """返回 (存在的证据相对路径列表, 缺失的期望相对路径列表)。"""
    present: list[Path] = []
    missing: list[str] = []
    for relative in EXPECTED_ARTIFACTS:
        path = root / relative
        if path.is_file():
            present.append(Path(relative))
        else:
            missing.append(relative)
    return present, missing


def build_evidence_zip(root: Path, output: Path, extra: list[Path] | None = None) -> dict:
    present, missing = collect_evidence(root)
    for item in extra or []:
        candidate = item if item.is_absolute() else root / item
        if candidate.is_file():
            try:
                relative = candidate.resolve().relative_to(root.resolve())
            except ValueError:
                relative = Path(candidate.name)
            if relative not in present:
                present.append(relative)
        else:
            missing.append(str(item))
    if not present:
        raise SystemExit("未找到任何可收集的验收产物（先运行 run_acceptance.ps1 或人工记录）")

    entries: list[dict] = []
    payloads: list[tuple[Path, bytes]] = []
    for relative in present:
        path = root / relative
        data = path.read_bytes()
        payloads.append((relative, data))
        entries.append(
            {
                "path": relative.as_posix(),
                "bytes": len(data),
                "sha256": sha256_bytes(data),
            }
        )
    manifest = {
        "format": "laitp-acceptance-evidence-1.0",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "root": str(root.resolve()),
        "files": entries,
        "missing": missing,
        "note": "证据收集包；不代表验收通过。missing 列出未产出的期望产物。",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative, data in payloads:
            archive.writestr(relative.as_posix(), data)
        archive.writestr(
            "evidence-manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        )
    return manifest


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    parser = argparse.ArgumentParser(description="收集目标机验收证据并打包（只读，不运行验收）")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="验收工作目录（默认当前目录）")
    parser.add_argument("--output", type=Path, help="输出 ZIP（默认 artifacts/evidence-bundle-<时间>.zip）")
    parser.add_argument("--extra", type=Path, nargs="*", default=[], help="额外要打包的文件（相对 root）")
    args = parser.parse_args()

    root = args.root.resolve()
    if not root.is_dir():
        raise SystemExit(f"--root 不是目录：{root}")
    output = args.output
    if output is None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output = root / "artifacts" / f"evidence-bundle-{stamp}.zip"
    elif not output.is_absolute():
        output = root / output

    manifest = build_evidence_zip(root, output, args.extra)
    print(f"已写入 {output}")
    print(f"文件数：{len(manifest['files'])}，缺失项：{len(manifest['missing'])}")
    for item in manifest["files"]:
        print(f"- {item['path']}（{item['bytes']} B，SHA-256 {item['sha256'][:16]}…）")
    for item in manifest["missing"]:
        print(f"- 缺失：{item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
