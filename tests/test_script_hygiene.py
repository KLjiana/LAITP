"""仓库脚本卫生检查：PowerShell 编码与验收脚本结构。

这些测试防止两类在本仓库实际发生过的回归：

1. 编辑工具写回 PowerShell 脚本时丢失 UTF-8 BOM，导致 Windows PowerShell 5.1
   按 ANSI/CP936 解析中文脚本并报语法错误（`run_acceptance.ps1` 曾出现 9 处解析错误）。
2. `run_acceptance.ps1` 在重构中丢失关键结构（11 个 Add-Step 步骤、界面步骤超时助手、
   预检清理），使包内验收与文档描述不一致。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

ACCEPTANCE_STEPS = (
    "包内自检",
    "窗口自检",
    "启动耗时",
    "演示数据生成",
    "新项目与导入",
    "训练与预测",
    "保存与恢复",
    "数据体检",
    "批量历史汇总",
    "严格验收（正向）",
    "自检幂等性复核",
)


def test_powershell_scripts_keep_utf8_bom() -> None:
    scripts = sorted(SCRIPTS.glob("*.ps1"))
    assert scripts, "scripts/ 下应有 PowerShell 脚本"
    missing = [
        script.name
        for script in scripts
        if script.read_bytes()[:3] != b"\xef\xbb\xbf"
    ]
    assert not missing, f"以下脚本缺少 UTF-8 BOM（PS 5.1 会解析失败）：{missing}"


def test_run_acceptance_has_all_steps() -> None:
    text = (SCRIPTS / "run_acceptance.ps1").read_text(encoding="utf-8-sig")
    missing = [name for name in ACCEPTANCE_STEPS if name not in text]
    assert not missing, f"run_acceptance.ps1 缺少步骤：{missing}"
    # 部分步骤在跳过分支会再次调用 Add-Step（pass/skip 两条记录），因此只要求
    # 出现次数不少于步骤数，且步骤名去重后覆盖 11 个环节。
    names = re.findall(r'Add-Step -Name "([^"]+)"', text)
    assert len(names) >= len(ACCEPTANCE_STEPS)
    assert set(ACCEPTANCE_STEPS) <= set(names)


def test_run_acceptance_has_timeout_and_preflight() -> None:
    text = (SCRIPTS / "run_acceptance.ps1").read_text(encoding="utf-8-sig")
    assert "function Invoke-PowerShellScriptWithTimeout" in text
    for timeout in ("240", "180", "420", "600", "480"):
        assert f"-TimeoutSeconds {timeout}" in text, f"缺少超时 {timeout}s"
    assert "taskkill" in text.lower()
    assert "预检清理残留进程" in text


def test_run_acceptance_has_ui_step_retry() -> None:
    text = (SCRIPTS / "run_acceptance.ps1").read_text(encoding="utf-8-sig")
    assert "function Invoke-UiStepWithRetry" in text, "界面步骤缺少单次重试助手"
    # 重试前等待默认 2 秒，避免紧接失败进程树清理立刻重跑。
    assert re.search(r"\[int\]\$DelaySeconds\s*=\s*2", text), "缺少 DelaySeconds 默认 2"
    # 返回对象需保留首次失败信息与最终结果，供 detail/warnings 留痕。
    for field in ("Retried", "FirstExitCode", "FirstTimedOut"):
        assert field in text, f"重试结果缺少 {field} 字段"


def test_run_acceptance_reports_bundle_identity_and_disk() -> None:
    text = (SCRIPTS / "run_acceptance.ps1").read_text(encoding="utf-8-sig")
    for phrase in (
        "manifest.json",
        "manifest_sha256",
        "## 包身份",
        "- 磁盘：",
        "长路径支持",
        "包目录长度",
    ):
        assert phrase in text, f"验收报告缺少 {phrase!r}"
