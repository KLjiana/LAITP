"""离线包完整流程验证：在含中文与空格路径下，用包内 Python 走通课堂闭环。

步骤：解包 → 建项目 → 导入 3 类图片（各 2 训练批次 + 测试集）→ 数据检查 →
训练 → 发布（导出 ONNX）→ 预测 → 项目校验。

全部后端命令使用包内 `python/python.exe`，工作目录位于解包根目录。脚本本身用开发机
Python 运行（只负责解包、生成测试图片与调用包内解释器），不代表干净机器验收。

用法：
    .venv\\Scripts\\python.exe scripts\\verify_offline_flow.py --bundle dist\\laitp-offline-lean.zip
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

CLASSES = ("杯子", "书本", "笔袋")
TRAIN_PER_BATCH = 8
BATCHES = 2
TEST_PER_CLASS = 4
DEAD_PROXY = "http://127.0.0.1:9"
_CLEAN_ENV: dict[str, str] | None = None


def clean_environment(extracted: Path) -> dict[str, str]:
    """模拟干净机器：PATH 仅保留 Windows 系统目录，清除 Python/.NET 相关变量，
    并把代理指向不可用地址（仅模拟断网，不代表真正断网）。"""
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    return {
        "SystemRoot": system_root,
        "WINDIR": system_root,
        "SystemDrive": os.environ.get("SystemDrive", "C:"),
        "TEMP": tempfile.gettempdir(),
        "TMP": tempfile.gettempdir(),
        "USERPROFILE": os.environ.get("USERPROFILE", str(Path.home())),
        "LOCALAPPDATA": os.environ.get("LOCALAPPDATA", str(Path.home())),
        "PATH": str(Path(system_root) / "System32") + os.pathsep + system_root,
        "PYTHONPATH": str(extracted),
        "PYTHONIOENCODING": "utf-8",
        "HTTP_PROXY": DEAD_PROXY,
        "HTTPS_PROXY": DEAD_PROXY,
        "NO_PROXY": "",
    }


def _make_images(source: Path, color: tuple[int, int, int], count: int, prefix: str) -> None:
    from PIL import Image, ImageDraw

    for index in range(count):
        image = Image.new("RGB", (64, 64), color)
        draw = ImageDraw.Draw(image)
        draw.rectangle((8 + index, 8, 56, 56), outline=(255, 255, 255), width=2)
        target = source / f"{prefix}-{index:02d}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target)


def run(
    interpreter: Path,
    extracted: Path,
    arguments: list[str],
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    effective = env if env is not None else _CLEAN_ENV
    completed = subprocess.run(
        [str(interpreter), "-m", *arguments],
        cwd=extracted,
        capture_output=True,
        env={**os.environ, "PYTHONPATH": str(extracted)}
        if effective is None
        else effective,
    )
    return (
        completed.returncode,
        completed.stdout.decode("utf-8", "replace"),
        completed.stderr.decode("utf-8", "replace"),
    )


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    parser = argparse.ArgumentParser(description="离线包完整流程验证")
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--output", default=None, help="结果 JSON 输出路径")
    parser.add_argument(
        "--clean-env",
        action="store_true",
        help="模拟干净机器：清空 PATH 中 Python/.NET，清除 PYTHON*，代理指向不可用地址",
    )
    parser.add_argument("--skip-desktop", action="store_true", help="跳过桌面启动检查")
    parser.add_argument(
        "--keep", action="store_true", help="保留解包目录（用于后续界面自动化）"
    )
    args = parser.parse_args(argv)

    bundle = Path(args.bundle)
    bundle = bundle if bundle.is_absolute() else Path.cwd() / bundle
    if not bundle.is_file():
        print(json.dumps({"ok": False, "error": f"分发包不存在：{bundle}"}, ensure_ascii=False))
        return 1

    temporary = Path(tempfile.mkdtemp(prefix="LAITP 离线 验证 "))
    extracted = temporary / "包 目录（含空格）"
    steps: list[dict] = []
    failures: list[str] = []
    try:
        with zipfile.ZipFile(bundle) as archive:
            archive.extractall(extracted)
        steps.append({"step": "解包", "ok": True, "path": str(extracted)})

        python = extracted / "python" / "python.exe"
        if not python.is_file():
            failures.append("包内缺少 python/python.exe")
            raise SystemExit(1)

        child_env = clean_environment(extracted) if args.clean_env else None
        if child_env is not None:
            global _CLEAN_ENV
            _CLEAN_ENV = child_env
            probe = subprocess.run(
                [str(python), "-c", "import sys; print(sys.executable)"],
                cwd=extracted,
                capture_output=True,
                env=child_env,
            )
            reported = probe.stdout.decode("utf-8", "replace").strip()
            inside = Path(reported).resolve().is_relative_to(extracted.resolve())
            steps.append(
                {
                    "step": "净环境：包内 Python",
                    "ok": probe.returncode == 0 and inside,
                    "python": reported,
                    "path": child_env["PATH"],
                    "proxy": child_env["HTTPS_PROXY"],
                }
            )
            if not (probe.returncode == 0 and inside):
                failures.append("净环境下包内 Python 不可用")

        project_root = extracted / "课堂 项目"
        exit_code, stdout, stderr = run(
            python, extracted,
            [
                "backend.project", "create",
                "--root", str(project_root),
                "--name", "离线课堂验证",
                "--classes", *CLASSES,
            ],
            child_env,
        )
        steps.append(
            {"step": "创建项目", "exit": exit_code,
             "ok": exit_code == 0, "stderr": stderr[-300:] if exit_code else ""}
        )
        if exit_code != 0:
            failures.append("创建项目失败")

        source_root = temporary / "图片 来源"
        for class_id, name in enumerate(CLASSES):
            for batch in range(BATCHES):
                color = (
                    (40 + class_id * 70) % 256,
                    (60 + batch * 90) % 256,
                    (200 - class_id * 50) % 256,
                )
                source = source_root / name / f"batch-{batch + 1}"
                _make_images(source, color, TRAIN_PER_BATCH, "train")
                exit_code, _, stderr = run(
                    python, extracted,
                    [
                        "backend.project", "import",
                        "--root", str(project_root),
                        "--class", name,
                        "--source", str(source),
                        "--batch", f"batch-{batch + 1}",
                    ],
                )
                if exit_code != 0:
                    failures.append(f"导入训练图片失败：{name}/{batch + 1}：{stderr[-200:]}")
            test_source = source_root / name / "test"
            _make_images(test_source, (220 - class_id * 60, 30 + class_id * 60, 40), TEST_PER_CLASS, "test")
            exit_code, _, stderr = run(
                python, extracted,
                [
                    "backend.project", "import",
                    "--root", str(project_root),
                    "--class", name,
                    "--source", str(test_source),
                    "--split", "test",
                    "--batch", "batch-test",
                ],
            )
            if exit_code != 0:
                failures.append(f"导入测试图片失败：{name}：{stderr[-200:]}")
        steps.append({"step": "导入图片", "ok": not failures})

        exit_code, stdout, stderr = run(
            python, extracted,
            ["backend.project", "check-dataset", "--root", str(project_root)],
        )
        check = json.loads(stdout) if stdout.strip() else {}
        steps.append(
            {"step": "数据检查", "exit": exit_code, "ok": check.get("ok") is True,
             "counts": check.get("counts", {}).get("splits")}
        )
        if check.get("ok") is not True:
            failures.append("数据检查未通过")

        run_id = "run-offline-0001"
        data = project_root / "data"
        train_args = [
            "backend.runtime.worker", "train",
            "--dataset", str(data / "dataset-manifest.json"),
            "--data-root", str(data),
            "--output", str(project_root / "runs"),
            "--run-id", run_id,
            "--weights-config", str(extracted / "configs/weights.v1.json"),
            "--epochs", "3",
            "--batch-size", "8",
            "--image-size", "64",
            "--request-id", "req-offline-train",
            "--project-id", "proj-offline",
            "--task-id", "task-offline-train",
        ]
        exit_code, stdout, stderr = run(python, extracted, train_args)
        train_messages = []
        for line in stdout.splitlines():
            if line.strip():
                try:
                    train_messages.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        train_result = next(
            (item for item in train_messages if item.get("message_type") == "result"), None
        )
        steps.append(
            {"step": "训练", "exit": exit_code,
             "ok": exit_code == 0 and train_result is not None,
             "artifact": train_result["payload"]["artifact"]["artifact_id"]
             if train_result else None,
             "stderr": stderr[-300:] if exit_code else ""}
        )
        if exit_code != 0 or train_result is None:
            failures.append("训练失败")

        exit_code, stdout, stderr = run(
            python, extracted,
            ["backend.project", "publish-training", "--root", str(project_root),
             "--run", f"runs/{run_id}"],
        )
        published = json.loads(stdout) if stdout.strip() else {}
        steps.append(
            {"step": "发布", "exit": exit_code, "ok": published.get("ok") is True,
             "artifact": published.get("artifact_id")}
        )
        if published.get("ok") is not True:
            failures.append("发布失败")

        exit_code, stdout, stderr = run(
            python, extracted,
            ["backend.classification", "report", "--run",
             str(project_root / "runs" / run_id)],
        )
        report_payload = json.loads(stdout) if stdout.strip() else {}
        accuracy = (
            report_payload.get("report", {}).get("accuracy")
            if report_payload.get("ok") else None
        )
        steps.append({"step": "训练报告", "exit": exit_code, "ok": report_payload.get("ok") is True,
                      "accuracy": accuracy})

        image = source_root / CLASSES[0] / "test" / "test-00.png"
        exit_code, stdout, stderr = run(
            python, extracted,
            [
                "backend.runtime.worker", "predict",
                "--package", str(project_root / "exports" / published["artifact_id"] / "model-package"),
                "--image", str(image),
                "--request-id", "req-offline-predict",
                "--project-id", "proj-offline",
                "--task-id", "task-offline-predict",
            ],
        )
        predict_messages = []
        for line in stdout.splitlines():
            if line.strip():
                try:
                    predict_messages.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        predict_result = next(
            (item for item in predict_messages if item.get("message_type") == "result"), None
        )
        steps.append(
            {"step": "预测", "exit": exit_code,
             "ok": exit_code == 0 and predict_result is not None,
             "top": predict_result["payload"]["predictions"][0]["label"]
             if predict_result else None}
        )
        if exit_code != 0 or predict_result is None:
            failures.append("预测失败")

        exit_code, stdout, stderr = run(
            python, extracted, ["backend.project", "verify", "--root", str(project_root)]
        )
        verified = json.loads(stdout) if stdout.strip() else {}
        steps.append({"step": "项目校验", "exit": exit_code, "ok": verified.get("ok") is True})
        if verified.get("ok") is not True:
            failures.append("项目校验失败")

        if not args.skip_desktop:
            desktop_exe = extracted / "desktop" / "app" / "Laitp.Desktop.exe"
            if desktop_exe.is_file():
                desktop_env = (
                    dict(child_env) if child_env is not None else {**os.environ}
                )
                desktop_env["LAITP_PYTHON"] = str(python)
                process = subprocess.Popen(
                    [str(desktop_exe)],
                    cwd=extracted,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=desktop_env,
                )
                time.sleep(4)
                alive = process.poll() is None
                if alive:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                steps.append(
                    {
                        "step": "桌面启动（包内 Python）",
                        "ok": alive,
                        "clean_env": args.clean_env,
                    }
                )
                if not alive:
                    failures.append("桌面程序启动即退出")
            else:
                steps.append({"step": "桌面启动", "ok": False, "error": "缺少桌面程序"})
                failures.append("包内缺少桌面程序")

            if desktop_exe.is_file():
                self_test_output = extracted / "self-test-result.json"
                selftest_env = (
                    dict(child_env) if child_env is not None else {**os.environ}
                )
                selftest_env["LAITP_PYTHON"] = str(python)
                selftest_env["LAITP_HOME"] = str(extracted)
                completed = subprocess.run(
                    [str(desktop_exe), "--self-test", str(self_test_output)],
                    cwd=extracted,
                    env=selftest_env,
                    capture_output=True,
                    timeout=240,
                )
                if completed.returncode == 0 and self_test_output.is_file():
                    report = json.loads(
                        self_test_output.read_text(encoding="utf-8")
                    )
                    passed = [
                        item["name"] for item in report.get("checks", [])
                        if item.get("ok")
                    ]
                    steps.append(
                        {
                            "step": "桌面 --self-test",
                            "ok": True,
                            "checks": passed,
                            "clean_env": args.clean_env,
                        }
                    )
                else:
                    steps.append(
                        {
                            "step": "桌面 --self-test",
                            "ok": False,
                            "stderr": completed.stderr.decode("utf-8", "replace")[-400:],
                        }
                    )
                    failures.append("桌面 --self-test 未通过")

        summary = {
            "ok": not failures,
            "bundle": str(bundle),
            "bundle_size_bytes": bundle.stat().st_size,
            "extracted_path": str(extracted),
            "steps": steps,
            "failures": failures,
        }
        if args.output:
            output = Path(args.output)
            output = output if output.is_absolute() else Path.cwd() / output
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if not failures else 1
    finally:
        if not args.keep:
            shutil.rmtree(temporary, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
