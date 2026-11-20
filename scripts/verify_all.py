"""一键验证：串联单元测试、构建、Core 检查、离线包校验、离线流程与界面自动化。

用法：
    .venv\\Scripts\\python.exe scripts\\verify_all.py
    .venv\\Scripts\\python.exe scripts\\verify_all.py --ui          # 追加界面自动化
    .venv\\Scripts\\python.exe scripts\\verify_all.py --quick       # 日常快速检查（6 步，约 1–2 分钟）
    .venv\\Scripts\\python.exe scripts\\verify_all.py --skip-bundle --skip-flow

输出：默认 artifacts\\verify-all\\verify-all.json 与 verify-all.txt；--quick 默认写入
artifacts\\verify-quick\\verify-quick.json 与 verify-quick.txt（显式 --output 优先）。
退出码 0 表示无失败项（pass/skip），否则 1；--quick 与 --ui/--camera 同传时快速模式优先，
被忽略的界面/摄像头步骤会在报告中记为 skip 并说明原因。
外部条件限制（目标机、真正断网、摄像头、板端）不在本脚本内，见 docs/acceptance-checklist.md。
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
DOTNET = ROOT / ".dotnet" / "dotnet.exe"
DEBUG_EXE = ROOT / "desktop/src/Laitp.Desktop/bin/Debug/net8.0-windows10.0.19041.0/Laitp.Desktop.exe"

DEFAULT_OUTPUT = "artifacts/verify-all"
QUICK_OUTPUT = "artifacts/verify-quick"
QUICK_NOTE = (
    "快速模式不含离线包校验、净环境流程、课堂演练、界面自动化与摄像头；"
    "阶段验收仍运行完整版（--ui/--camera）"
)
EXTERNAL_NOTE = (
    "外部验收（干净机器、真正断网、普通用户、摄像头、板端）见 docs/acceptance-checklist.md"
)


class Runner:
    def __init__(self) -> None:
        self.steps: list[dict] = []

    def record(self, name: str, status: str, detail: str, duration: float) -> None:
        self.steps.append(
            {
                "name": name,
                "status": status,
                "detail": detail[-1200:],
                "duration_seconds": round(duration, 2),
            }
        )
        print(f"[{status.upper():4}] {name}（{duration:.1f}s）")

    def run(
        self,
        name: str,
        command: list[str],
        cwd: Path = ROOT,
        timeout: int = 1800,
        allow_failure: bool = False,
    ) -> bool:
        start = time.monotonic()
        try:
            completed = subprocess.run(
                command, cwd=cwd, capture_output=True, timeout=timeout
            )
        except subprocess.TimeoutExpired:
            self.record(name, "fail", "超时", time.monotonic() - start)
            return False
        duration = time.monotonic() - start
        if completed.returncode == 0:
            self.record(name, "pass", "成功", duration)
            return True
        detail = (
            completed.stderr.decode("utf-8", "replace")
            or completed.stdout.decode("utf-8", "replace")
        )
        self.record(name, "fail" if not allow_failure else "skip", detail, duration)
        return completed.returncode == 0

    def skip(self, name: str, reason: str) -> None:
        self.record(name, "skip", reason, 0.0)


def quick_plan(dotnet: str = "dotnet") -> list[dict]:
    """快速模式（--quick）步骤计划：名称、命令与超时，列表顺序即执行顺序。"""
    return [
        {
            "name": "Python 单元测试",
            "command": [PYTHON, "-m", "pytest", "-q"],
            "timeout": 900,
        },
        {
            "name": "桌面构建",
            "command": [dotnet, "build", "desktop/Laitp.sln", "-v", "quiet"],
            "timeout": 900,
        },
        {
            "name": "Core 检查",
            "command": [
                dotnet,
                "run",
                "--project",
                "desktop/tests/Laitp.Core.Checks",
                "-v",
                "quiet",
            ],
            "timeout": 900,
        },
        {
            "name": "验收证据汇总",
            "command": [PYTHON, "scripts/acceptance_audit.py"],
            "timeout": 120,
        },
        {
            "name": "文档一致性",
            "command": [PYTHON, "scripts/check_docs.py"],
            "timeout": 120,
        },
        {
            "name": "交付状态自检",
            "command": [PYTHON, "scripts/check_state.py"],
            "timeout": 120,
        },
    ]


def quick_step_names() -> list[str]:
    """快速模式应包含的步骤名（顺序与执行顺序一致，供单元测试断言）。"""
    return [step["name"] for step in quick_plan()]


def resolve_output_dir(explicit: str | None, quick: bool, root: Path = ROOT) -> Path:
    """解析输出目录：显式 --output 优先；--quick 默认 artifacts/verify-quick。"""
    if explicit:
        return root / explicit
    return root / (QUICK_OUTPUT if quick else DEFAULT_OUTPUT)


def run_quick(runner: Runner) -> None:
    """按 quick_plan() 的顺序执行快速步骤。"""
    dotnet = str(DOTNET if DOTNET.is_file() else "dotnet")
    for step in quick_plan(dotnet):
        runner.run(step["name"], step["command"], timeout=step["timeout"])


def write_report(
    runner: Runner, output_dir: Path, report_name: str, quick: bool
) -> dict:
    """写入 JSON/TXT 报告并返回汇总；--quick 报告带 "quick": true。"""
    summary = {
        "ok": all(step["status"] != "fail" for step in runner.steps),
        "quick": quick,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "steps": runner.steps,
        "notes": [QUICK_NOTE, EXTERNAL_NOTE] if quick else [EXTERNAL_NOTE],
    }
    (output_dir / f"{report_name}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        f"{step['name']}: {step['status']}（{step['duration_seconds']}s）"
        for step in runner.steps
    ]
    lines.append("总体：" + ("通过" if summary["ok"] else "存在失败项"))
    (output_dir / f"{report_name}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"ok": summary["ok"], "output": str(output_dir / f"{report_name}.json")},
            ensure_ascii=False,
        )
    )
    return summary


def make_images(source: Path, test_source: Path) -> None:
    from PIL import Image

    colors = {"苹果": (210, 60, 40), "香蕉": (50, 170, 70)}
    for name, base in colors.items():
        for batch in (1, 2):
            folder = source / name / f"batch-{batch}"
            folder.mkdir(parents=True, exist_ok=True)
            for index in range(6):
                color = (
                    (base[0] + batch * 9) % 256,
                    (base[1] + index * 5) % 256,
                    base[2],
                )
                Image.new("RGB", (64, 64), color).save(folder / f"{index:02d}.png")
        test_folder = test_source / name / "batch-test"
        test_folder.mkdir(parents=True, exist_ok=True)
        for index in range(3):
            color = ((base[0] + 40) % 256, (base[1] + 40) % 256, (base[2] + 40) % 256)
            Image.new("RGB", (64, 64), color).save(test_folder / f"{index:02d}.png")


def powershell_script(script: Path, arguments: list[str]) -> list[str]:
    return [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        *arguments,
    ]


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    parser = argparse.ArgumentParser(description="LAITP 一键验证")
    parser.add_argument(
        "--quick",
        action="store_true",
        help=(
            "快速验证（日常改动后使用）：仅单元测试、桌面构建、Core 检查、"
            "验收证据汇总、文档一致性与交付状态自检"
        ),
    )
    parser.add_argument("--ui", action="store_true", help="追加界面自动化（需要桌面构建）")
    parser.add_argument(
        "--camera",
        action="store_true",
        help="追加摄像头拍照导入（需要可用摄像头，开发机使用 DroidCam）",
    )
    parser.add_argument("--skip-bundle", action="store_true")
    parser.add_argument("--skip-flow", action="store_true")
    parser.add_argument("--bundle", default="dist/laitp-offline-lean.zip")
    parser.add_argument(
        "--output",
        default=None,
        help="输出目录（默认 artifacts/verify-all；--quick 默认 artifacts/verify-quick）",
    )
    args = parser.parse_args(argv)

    output_dir = resolve_output_dir(args.output, args.quick)
    output_dir.mkdir(parents=True, exist_ok=True)
    runner = Runner()
    temporary = Path(tempfile.mkdtemp(prefix="laitp-verify-all-"))
    report_name = "verify-quick" if args.quick else "verify-all"

    try:
        if args.quick:
            # 快速模式优先：--ui/--camera 不执行，只记录跳过原因。
            if args.ui:
                runner.skip("界面自动化", "跳过：--quick 快速模式优先，忽略 --ui")
            if args.camera:
                runner.skip("界面摄像头拍照导入", "跳过：--quick 快速模式优先，忽略 --camera")
            run_quick(runner)
            summary = write_report(runner, output_dir, report_name, quick=True)
            return 0 if summary["ok"] else 1

        runner.run("Python 单元测试", [PYTHON, "-m", "pytest", "-q"])
        dotnet = str(DOTNET if DOTNET.is_file() else "dotnet")
        runner.run("桌面构建", [dotnet, "build", "desktop/Laitp.sln", "-v", "quiet"])
        runner.run(
            "Core 检查",
            [dotnet, "run", "--project", "desktop/tests/Laitp.Core.Checks", "-v", "quiet"],
        )
        runner.run(
            "验收证据汇总",
            [PYTHON, "scripts/acceptance_audit.py"],
            timeout=120,
        )
        runner.run(
            "文档一致性",
            [PYTHON, "scripts/check_docs.py"],
            timeout=120,
        )

        bundle = ROOT / args.bundle
        if args.skip_bundle or not bundle.is_file():
            runner.skip("离线包校验", "跳过：未指定或不存在分发包")
        else:
            runner.run(
                "离线包校验",
                [PYTHON, "scripts/verify_offline_bundle.py", "--bundle", str(bundle)],
                timeout=2400,
            )

        if args.skip_flow or not bundle.is_file():
            runner.skip("离线流程（净环境）", "跳过：未指定或不存在分发包")
        else:
            runner.run(
                "离线流程（净环境）",
                [
                    PYTHON, "scripts/verify_offline_flow.py",
                    "--bundle", str(bundle), "--clean-env",
                ],
                timeout=2400,
            )
        runner.run(
            "真实数据课堂演练",
            [PYTHON, "scripts/classroom_rehearsal.py"],
            timeout=1800,
        )

        if args.ui:
            if not DEBUG_EXE.is_file():
                runner.skip("界面自动化", "跳过：桌面 Debug 构建不存在")
            else:
                runner.run(
                    "界面冒烟（自检）",
                    powershell_script(ROOT / "scripts/ui_smoke.ps1", []), timeout=600,
                )

                flow_project = temporary / "真实 项目"
                shutil.copytree(ROOT / "artifacts/real-data/fashion-project", flow_project)
                images = sorted((flow_project / "data/test-images").rglob("*.png"))
                image = images[0] if images else None
                if image is not None:
                    runner.run(
                        "界面闭环（打开→检查→训练→预测）",
                        powershell_script(
                            ROOT / "scripts/ui_flow.ps1",
                            ["-ProjectPath", str(flow_project / "project.json"),
                             "-ImagePath", str(image), "-TrainPredict",
                             "-BatchImagesDir", str(flow_project / "data" / "test-images"),
                             "-ComparePackage",
                             str(flow_project / "exports" / "art-run-real-0001" / "model-package")],
                        ),
                        timeout=1200,
                    )
                    runner.run(
                        "界面另存为/归档 + 最近项目",
                        powershell_script(
                            ROOT / "scripts/ui_flow.ps1",
                            ["-ProjectPath", str(flow_project / "project.json"),
                             "-UseRecent",
                             "-SaveAsDir", str(temporary / "另存为 项目"),
                             "-ArchiveDir", str(temporary / "归档 项目")],
                        ),
                        timeout=1200,
                    )
                else:
                    runner.skip("界面闭环", "跳过：真实项目缺少测试图片")

                source = temporary / "图片 来源"
                test_source = temporary / "测试 来源"
                make_images(source, test_source)
                runner.run(
                    "界面新建 + 导入",
                    powershell_script(
                        ROOT / "scripts/ui_create_import.ps1",
                        ["-SourceRoot", str(source),
                         "-ProjectParent", str(temporary / "新建 项目"),
                         "-TestSource", str(test_source)],
                    ),
                    timeout=1200,
                )
                runner.run(
                    "界面批量导入",
                    powershell_script(
                        ROOT / "scripts/ui_create_import.ps1",
                        ["-SourceRoot", str(source),
                         "-ProjectParent", str(temporary / "批量 项目"),
                         "-TreeSource", str(source)],
                    ),
                    timeout=1200,
                )
                runner.run(
                    "界面保存 + 恢复",
                    powershell_script(
                        ROOT / "scripts/ui_restore.ps1",
                        ["-SourceRoot", str(source),
                         "-ProjectParent", str(temporary / "恢复 项目")],
                    ),
                    timeout=1800,
                )
                history_project = temporary / "历史 项目"
                shutil.copytree(ROOT / "artifacts/real-data/fashion-project", history_project)
                runner.run(
                    "界面历史导出",
                    powershell_script(
                        ROOT / "scripts/ui_export_history.ps1",
                        ["-ProjectPath", str(history_project / "project.json")],
                    ),
                    timeout=1200,
                )
                edit_project = temporary / "编辑 项目"
                shutil.copytree(ROOT / "artifacts/real-data/fashion-project", edit_project)
                runner.run(
                    "界面项目编辑 + 严格验收",
                    powershell_script(
                        ROOT / "scripts/ui_edit.ps1",
                        ["-ProjectPath", str(edit_project / "project.json")],
                    ),
                    timeout=1200,
                )
                if args.camera:
                    runner.run(
                        "界面摄像头拍照导入",
                        powershell_script(
                            ROOT / "scripts/ui_camera.ps1",
                            ["-ProjectParent", str(temporary / "摄像头 项目")],
                        ),
                        timeout=1800,
                    )
                else:
                    runner.skip("界面摄像头拍照导入", "跳过：未传 --camera")
        else:
            runner.skip("界面自动化", "跳过：未传 --ui")

        summary = write_report(runner, output_dir, report_name, quick=False)
        return 0 if summary["ok"] else 1
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
