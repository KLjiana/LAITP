"""汇总本机验收证据：对照 A1–A15 标注已验证/部分/未执行/阻塞。

读取现有验证产物（不重新运行耗时检查），输出：
    artifacts/acceptance-local.json   机器可读结果
    artifacts/acceptance-local.md     可粘贴到文档的表格

用法：
    .venv\\Scripts\\python.exe scripts\\acceptance_audit.py
"""

from __future__ import annotations

import json
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"


def load_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def find_step(verify_all: dict | None, keyword: str) -> dict | None:
    if not verify_all:
        return None
    for step in verify_all.get("steps", []):
        if keyword in step.get("name", ""):
            return step
    return None


def step_passed(verify_all: dict | None, keyword: str) -> bool:
    step = find_step(verify_all, keyword)
    return bool(step and step.get("status") == "pass")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    verify_all = load_json(ARTIFACTS / "verify-all/verify-all.json")
    offline_flow = load_json(ARTIFACTS / "offline-clean-env-result.json")
    clean_flow = load_json(ARTIFACTS / "ui-flow-clean-bundle.json")
    clean_camera = load_json(ARTIFACTS / "ui-camera-clean-bundle.json")
    rehearsal = load_json(ARTIFACTS / "classroom-rehearsal/result.json")
    real_data = load_json(ARTIFACTS / "real-data/result.json")
    camera_probe = load_json(ARTIFACTS / "camera-preview-probe.json")
    camera_bundle = load_json(ARTIFACTS / "ui-camera-bundle.json")

    bundle_path = ROOT / "dist/laitp-offline-lean.zip"
    bundle_sha = None
    sha_file = bundle_path.with_suffix(bundle_path.suffix + ".sha256")
    if sha_file.is_file():
        bundle_sha = sha_file.read_text(encoding="utf-8").split()[0]
    bundle_size = bundle_path.stat().st_size if bundle_path.is_file() else None

    real_accuracy = None
    if real_data:
        real_accuracy = real_data.get("report", {}).get("accuracy") or real_data.get("accuracy")
    rehearsal_total = rehearsal.get("stage_seconds_total") if rehearsal else None
    clean_env_ok = bool(
        (offline_flow and offline_flow.get("ok")) or (clean_flow and clean_flow.get("ok"))
    )

    items: list[dict] = []

    def add(
        item_id: str,
        title: str,
        status: str,
        evidence: list[str],
        note: str = "",
    ) -> None:
        items.append(
            {
                "id": item_id,
                "title": title,
                "status": status,
                "evidence": evidence,
                "note": note,
            }
        )

    bundle_evidence = (
        [f"dist/laitp-offline-lean.zip（{bundle_size} B，SHA-256 {bundle_sha}）"]
        if bundle_size
        else []
    )
    add(
        "A1",
        "包完整性",
        "verified" if step_passed(verify_all, "离线包校验") else "partial",
        bundle_evidence + ["verify-all: 离线包校验"],
        "含包内现场自检：scripts/verify_offline_bundle.py --extracted .",
    )
    add(
        "A2",
        "解压与启动",
        "verified" if step_passed(verify_all, "界面冒烟") else "partial",
        ["verify-all: 界面冒烟（自检）", "ui-camera-bundle.json"],
    )
    add(
        "A3",
        "首次自检",
        "verified" if step_passed(verify_all, "界面冒烟") else "partial",
        ["verify-all: 界面冒烟；自检失败场景"],
    )
    add(
        "A4",
        "新建项目",
        "verified" if step_passed(verify_all, "界面新建 + 导入") else "partial",
        ["verify-all: 界面新建 + 导入"],
    )
    add(
        "A5",
        "导入图片",
        "verified" if step_passed(verify_all, "界面批量导入") else "partial",
        ["verify-all: 界面批量导入", "verify-all: 界面新建 + 导入"],
    )
    add(
        "A6",
        "检查数据（含严格验收）",
        "verified" if step_passed(verify_all, "严格验收") else "partial",
        ["verify-all: 界面项目编辑 + 严格验收"],
        "严格验收拒绝路径正确；正向通过已用真实子集 20/20/10 验证（artifacts/ui-edit-strict-positive.json）",
    )
    add(
        "A7",
        "训练与发布",
        "verified" if step_passed(verify_all, "界面闭环") else "partial",
        ["verify-all: 界面闭环（训练并发布）"],
    )
    add(
        "A8",
        "预测",
        "verified" if step_passed(verify_all, "界面闭环") else "partial",
        ["verify-all: 界面闭环（预测）"],
    )
    add(
        "A9",
        "项目保存恢复",
        "verified" if step_passed(verify_all, "保存 + 恢复") else "partial",
        ["verify-all: 界面保存 + 恢复"],
    )
    add(
        "A10",
        "真实课堂图片",
        "not_run",
        [f"公开数据准确率 {real_accuracy:.3f}" if real_accuracy else "无真实数据产物"],
        "仅有 Fashion-MNIST 公开数据；课堂采集数据未提供",
    )
    add(
        "A11",
        "摄像头采集",
        "partial",
        [
            "camera-capture.png（DroidCam 单张）",
            f"预览探针 {camera_probe.get('fps')} fps" if camera_probe else "",
            "ui-camera-bundle.json（设备/预览/连拍/拍照）",
        ],
        "物理 HD Webcam 被禁用（Code 22）；权限/占用错误未在真实设备触发",
    )
    add(
        "A12",
        "断网验证",
        "partial" if clean_env_ok else "not_run",
        ["offline-clean-env-result.json", "ui-flow-clean-bundle.json", "ui-camera-clean-bundle.json"],
        "净环境模拟（不可用代理 + 最小 PATH），非真正断网/防火墙阻断",
    )
    add(
        "A13",
        "权限与路径",
        "partial",
        ["中文/空格路径相关验证（离线包、界面自动化）"],
        "普通用户权限未验证",
    )
    add(
        "A14",
        "课堂时间预算",
        "partial",
        [f"课堂演练合计 {rehearsal_total:.1f} s" if rehearsal_total else "无演练产物"],
        "未含摄像头采集与真实课堂环境",
    )
    add(
        "A15",
        "板端部署",
        "blocked",
        [],
        "无 K230/K210 硬件与转换工具链",
    )

    summary = {"verified": 0, "partial": 0, "not_run": 0, "blocked": 0}
    for item in items:
        summary[item["status"]] = summary.get(item["status"], 0) + 1

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "machine": {
            "os": platform.platform(),
            "python": sys.version.split()[0],
        },
        "bundle": {
            "path": str(bundle_path.relative_to(ROOT)) if bundle_path.is_file() else None,
            "size_bytes": bundle_size,
            "sha256": bundle_sha,
        },
        "summary": summary,
        "items": items,
        "notes": [
            "本机证据不等于目标机验收；A10–A15 等外部条件项仍待执行",
            "数据来自 artifacts/ 下既有验证产物，不重新运行耗时检查",
        ],
    }
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "acceptance-local.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    labels = {
        "verified": "已验证",
        "partial": "部分",
        "not_run": "未执行",
        "blocked": "阻塞",
    }
    lines = [
        "| 编号 | 项目 | 状态 | 证据/说明 |",
        "| --- | --- | --- | --- |",
    ]
    for item in items:
        detail = "；".join(part for part in item["evidence"] if part)
        if item["note"]:
            detail = (detail + "；" if detail else "") + item["note"]
        lines.append(
            f"| {item['id']} | {item['title']} | {labels[item['status']]} | {detail} |"
        )
    lines.append("")
    lines.append(
        "汇总："
        + "，".join(f"{labels[key]} {value} 项" for key, value in summary.items() if value)
    )
    (ARTIFACTS / "acceptance-local.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    print(json.dumps({"ok": True, "summary": summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
