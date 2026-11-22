"""K230 转换启动条件自检：把“还需要什么”变成可复现的检查清单。

只检查本机/包内可核对的事实，不执行 nncase 转换，也不接触板卡。
结论 ``blocked`` 表示启动条件未满足；``ready-for-conversion-attempt`` 仅表示
可以尝试转换，**不代表转换会成功或板端可运行**。

用法：
    python scripts/k230_readiness.py --model <模型包> --output artifacts/k230-readiness.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TOOLCHAIN_CONFIG = ROOT / "configs" / "k230-toolchain.json"

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def load_probe():
    spec = importlib.util.spec_from_file_location(
        "k230_model_probe", ROOT / "scripts" / "k230_model_probe.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def check_toolchain(toolchain_config: Path) -> dict:
    required = ("nncase_version", "sdk_version", "board_model")
    if not toolchain_config.is_file():
        return {
            "id": "toolchain-pinned",
            "status": "blocked",
            "detail": f"未找到工具链固定配置：{toolchain_config}",
        }
    try:
        data = json.loads(toolchain_config.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {
            "id": "toolchain-pinned",
            "status": "blocked",
            "detail": f"工具链配置不可读：{exc}",
        }
    missing = [key for key in required if not str(data.get(key, "")).strip()]
    if missing:
        return {
            "id": "toolchain-pinned",
            "status": "blocked",
            "detail": "工具链配置缺少字段：" + "、".join(missing),
        }
    return {
        "id": "toolchain-pinned",
        "status": "pass",
        "detail": (
            f"nncase={data['nncase_version']}、sdk={data['sdk_version']}、"
            f"board={data['board_model']}"
        ),
    }


def check_nncase() -> dict:
    spec = importlib.util.find_spec("nncase")
    if spec is None:
        return {
            "id": "nncase-installed",
            "status": "blocked",
            "detail": "当前环境未安装 nncase（需按固定版本离线安装）",
        }
    version = getattr(__import__("nncase"), "__version__", "未知")
    return {"id": "nncase-installed", "status": "pass", "detail": f"nncase 已安装（版本 {version}）"}


def check_calibration(calibration_dir: Path | None, minimum: int = 20) -> dict:
    if calibration_dir is None:
        return {
            "id": "calibration-data",
            "status": "blocked",
            "detail": "未提供校准数据目录（--calibration-dir）",
        }
    if not calibration_dir.is_dir():
        return {
            "id": "calibration-data",
            "status": "blocked",
            "detail": f"校准数据目录不存在：{calibration_dir}",
        }
    count = sum(
        1
        for path in calibration_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )
    if count < minimum:
        return {
            "id": "calibration-data",
            "status": "blocked",
            "detail": f"校准图片 {count} 张，少于建议的 {minimum} 张",
        }
    return {
        "id": "calibration-data",
        "status": "pass",
        "detail": f"校准图片 {count} 张（建议至少 {minimum} 张）",
    }


def check_model(model_dir: Path) -> dict:
    probe = load_probe()
    try:
        onnx_path = probe.resolve_onnx(model_dir)
        report = probe.probe_onnx(onnx_path)
    except SystemExit as exc:
        return {
            "id": "model-package",
            "status": "blocked",
            "detail": str(exc),
        }
    checks: list[dict] = []
    dynamic = [item["name"] for item in report["inputs"] if item["dynamic"]]
    if dynamic:
        checks.append(
            {
                "id": "model-static-input",
                "status": "blocked",
                "detail": "输入含动态维度：" + "、".join(dynamic),
            }
        )
    else:
        checks.append(
            {
                "id": "model-static-input",
                "status": "pass",
                "detail": f"输入 {report['inputs'][0]['shape']}（静态）",
            }
        )
    if report["warnings"]:
        checks.append(
            {
                "id": "model-plan-review",
                "status": "warn",
                "detail": "；".join(report["warnings"]),
            }
        )
    else:
        checks.append(
            {
                "id": "model-plan-review",
                "status": "pass",
                "detail": f"{report['node_count']} 个节点、{report['parameter_count']} 参数，无动态形状/高危算子提示",
            }
        )
    try:
        manifest = probe.read_manifest(model_dir)
    except SystemExit:
        manifest = {}
    expected = None
    for entry in manifest.get("files") or []:
        if str(entry.get("path", "")).endswith(".onnx"):
            expected = entry.get("sha256")
            break
    report["manifest_sha256_expected"] = expected
    report["manifest_sha256_match"] = expected == report["sha256"] if expected else None
    checks.append(
        {
            "id": "model-manifest-digest",
            "status": "pass" if report.get("manifest_sha256_match") else "warn",
            "detail": (
                "manifest SHA-256 匹配"
                if report.get("manifest_sha256_match")
                else "manifest 未提供摘要或摘要不匹配"
            ),
        }
    )
    return {"checks": checks, "probe": report}


def build_report(
    model_dir: Path, toolchain_config: Path, calibration_dir: Path | None
) -> dict:
    checks: list[dict] = [check_toolchain(toolchain_config), check_nncase()]
    model_result = check_model(model_dir)
    if "checks" in model_result:
        checks.extend(model_result["checks"])
    else:
        checks.append(model_result)
    checks.append(check_calibration(calibration_dir))
    blocked = [item for item in checks if item["status"] == "blocked"]
    warnings = [item for item in checks if item["status"] == "warn"]
    return {
        "format": "laitp-k230-readiness-1.0",
        "model": str(model_dir),
        "overall": "blocked" if blocked else "ready-for-conversion-attempt",
        "note": "只检启动条件；ready-for-conversion-attempt 不代表转换成功或板端可运行。",
        "blocked_count": len(blocked),
        "warning_count": len(warnings),
        "checks": checks,
        "probe": model_result.get("probe"),
    }


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    parser = argparse.ArgumentParser(description="K230 转换启动条件自检（不执行转换）")
    parser.add_argument("--model", type=Path, required=True, help="模型包目录")
    parser.add_argument(
        "--toolchain-config", type=Path, default=DEFAULT_TOOLCHAIN_CONFIG
    )
    parser.add_argument("--calibration-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = build_report(
        args.model.resolve(),
        args.toolchain_config.resolve(),
        args.calibration_dir.resolve() if args.calibration_dir else None,
    )
    status = report["overall"]
    print(
        f"总体：{status}（blocked={report['blocked_count']}，warn={report['warning_count']}）"
    )
    for item in report["checks"]:
        print(f"- [{item['status']}] {item['id']}：{item['detail']}")
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output = args.output if args.output.is_absolute() else (ROOT / args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
        print(f"已写入 {output}")
    print(text)
    return 0 if report["overall"] == "ready-for-conversion-attempt" else 1


if __name__ == "__main__":
    raise SystemExit(main())
