"""校验离线分发包：检查清单摘要，并在解包目录运行推理与报告冒烟。

用法：
    .venv\\Scripts\\python.exe scripts\\verify_offline_bundle.py --bundle dist\\laitp-offline-<日期>.zip
    python\\python.exe scripts\\verify_offline_bundle.py --extracted .   # 在解压目录内现场自检

说明：验证使用当前解释器（开发机为 .venv；包内为便携 Python），只验证包内容完整与
后端可在解包目录运行；不代表目标机器在无前置依赖下的可用性。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

BUNDLE_FORMAT = "laitp-offline-bundle-1.0"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_start_script(extracted: Path) -> list[str]:
    """校验启动脚本指向包内自包含桌面程序，而不是开发构建 bin 目录。"""
    script = extracted / "start-desktop.bat"
    if not script.is_file():
        return ["缺少启动脚本：start-desktop.bat"]
    try:
        content = script.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        return [f"无法读取 start-desktop.bat：{error}"]
    problems: list[str] = []
    lowered = content.lower().replace("/", "\\")
    if "desktop\\app\\laitp.desktop.exe" not in lowered:
        problems.append(
            "start-desktop.bat 未指向包内 desktop\\app\\Laitp.Desktop.exe"
        )
    if "\\bin\\" in lowered:
        problems.append("start-desktop.bat 指向开发构建 bin 目录，不应随包分发")
    return problems


def check_check_bundle_script(extracted: Path) -> list[str]:
    """校验一键自检脚本调用包内 Python，并切换到 UTF-8 代码页。

    目标机双击 check-bundle.bat 是现场自检入口；若构建或手工替换破坏了内容，
    双击会静默失败，因此这里校验关键命令与开发机绝对路径。
    """
    script = extracted / "check-bundle.bat"
    if not script.is_file():
        return ["缺少自检脚本：check-bundle.bat"]
    try:
        content = script.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        return [f"无法读取 check-bundle.bat：{error}"]
    problems: list[str] = []
    normalized = content.lower().replace("/", "\\")
    required = (
        (
            "python\\python.exe",
            "check-bundle.bat 未调用包内 Python：缺少 python\\python.exe",
        ),
        (
            "scripts\\verify_offline_bundle.py",
            "check-bundle.bat 未调用包内自检脚本："
            "缺少 scripts\\verify_offline_bundle.py",
        ),
        (
            "--extracted",
            "check-bundle.bat 未向自检脚本传入 --extracted 参数",
        ),
        (
            "chcp 65001",
            "check-bundle.bat 未切换 UTF-8 代码页：缺少 chcp 65001",
        ),
    )
    for token, message in required:
        if token not in normalized:
            problems.append(message)
    if "d:\\project" in normalized:
        problems.append(
            "check-bundle.bat 含开发机绝对路径：D:\\project，目标机将无法运行"
        )
    return problems


def check_desktop_self_contained(extracted: Path) -> list[str]:
    """校验包内桌面程序是自包含发布（不依赖目标机 .NET Desktop Runtime）。"""
    problems: list[str] = []
    app_dir = extracted / "desktop" / "app"
    runtimeconfig = app_dir / "Laitp.Desktop.runtimeconfig.json"
    if not runtimeconfig.is_file():
        return [f"缺少桌面运行时配置：{runtimeconfig.relative_to(extracted)}"]
    try:
        config = json.loads(runtimeconfig.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return [f"无法解析桌面运行时配置：{error}"]
    included = (config.get("runtimeOptions") or {}).get("includedFrameworks")
    framework = (config.get("runtimeOptions") or {}).get("framework")
    if not included:
        detail = framework.get("name") if isinstance(framework, dict) else "未知框架"
        problems.append(
            "桌面程序不是自包含发布（runtimeconfig 引用框架 "
            f"{detail}），目标机未安装 .NET Desktop Runtime 时无法启动"
        )
    for name in ("coreclr.dll", "hostfxr.dll"):
        if not (app_dir / name).is_file():
            problems.append(f"桌面程序缺少运行时文件：desktop/app/{name}")
    return problems


def find_manifest_hygiene_issues(files: list[str]) -> list[str]:
    """检查清单路径是否包含缓存或编译产物。

    打包时应排除 __pycache__ 与 .pyc/.pyo；清单若仍列出这些路径，说明包内
    自检会随 Python 首次导入重写缓存文件，导致清单摘要不幂等。命中不区分
    大小写，返回问题描述列表（空列表表示清单干净）。
    """
    issues: list[str] = []
    for path in files:
        normalized = path.lower()
        if "__pycache__" in normalized or normalized.endswith((".pyc", ".pyo")):
            issues.append(f"清单包含缓存/编译产物：{path}")
    return issues


def run_backend(
    extracted: Path, arguments: list[str], interpreter: Path | None = None
) -> tuple[int, list[dict], str]:
    completed = subprocess.run(
        [str(interpreter or sys.executable), "-m", *arguments],
        cwd=extracted,
        capture_output=True,
        env={**os.environ, "PYTHONPATH": str(extracted)},
    )
    text = completed.stdout.decode("utf-8")
    messages: list[dict] = []
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            messages.append(payload)
    except json.JSONDecodeError:
        for line in text.splitlines():
            if line.strip():
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    messages.append(item)
    return completed.returncode, messages, completed.stderr.decode("utf-8", "replace")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验 LAITP 离线分发包")
    parser.add_argument("--bundle", default=None, help="离线包 zip 路径")
    parser.add_argument(
        "--extracted", default=None, help="已解压的离线包目录（现场自检模式）"
    )
    parser.add_argument("--keep", action="store_true", help="保留解包目录")
    args = parser.parse_args(argv)

    if not args.bundle and not args.extracted:
        parser.error("需要 --bundle 或 --extracted")

    checks: list[str] = []
    failures: list[str] = []
    predict_artifact = None
    report_accuracy = None
    temporary = None
    extracted: Path
    bundle: Path | None = None

    if args.extracted:
        extracted = Path(args.extracted)
        extracted = extracted if extracted.is_absolute() else Path.cwd() / extracted
        if not extracted.is_dir():
            print(
                json.dumps(
                    {"ok": False, "error": f"解压目录不存在：{extracted}"},
                    ensure_ascii=False,
                )
            )
            return 1
        checks.append("使用已解压目录")
    else:
        bundle = Path(args.bundle)
        bundle = bundle if bundle.is_absolute() else Path.cwd() / bundle
        if not bundle.is_file():
            print(
                json.dumps(
                    {"ok": False, "error": f"分发包不存在：{bundle}"},
                    ensure_ascii=False,
                )
            )
            return 1
        temporary = tempfile.mkdtemp(prefix="laitp-verify-")
        extracted = Path(temporary) / "laitp"

    try:
        if bundle is not None:
            with zipfile.ZipFile(bundle) as archive:
                archive.extractall(extracted)
            checks.append("解包成功")

        manifest_path = extracted / "manifest.json"
        if not manifest_path.is_file():
            failures.append("缺少 manifest.json")
            raise SystemExit(1)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("format") != BUNDLE_FORMAT:
            failures.append(f"清单格式不是 {BUNDLE_FORMAT}")
        manifest_files = [
            entry["path"]
            for component in manifest.get("components", [])
            for entry in component.get("files", [])
        ]
        hygiene_issues = find_manifest_hygiene_issues(manifest_files)
        failures.extend(hygiene_issues)
        if not hygiene_issues:
            checks.append(
                f"清单卫生检查通过（{len(manifest_files)} 个路径无缓存/编译产物）"
            )
        start_script_issues = check_start_script(extracted)
        failures.extend(start_script_issues)
        if not start_script_issues:
            checks.append("启动脚本指向包内自包含桌面程序")
        check_bundle_issues = check_check_bundle_script(extracted)
        failures.extend(check_bundle_issues)
        if not check_bundle_issues:
            checks.append("自检脚本 check-bundle.bat 内容正确")
        desktop_issues = check_desktop_self_contained(extracted)
        failures.extend(desktop_issues)
        if not desktop_issues:
            checks.append("桌面程序为自包含发布（含 coreclr/hostfxr）")
        verified = 0
        for component in manifest.get("components", []):
            for entry in component.get("files", []):
                target = extracted / entry["path"]
                if not target.is_file():
                    failures.append(f"缺少文件：{entry['path']}")
                    continue
                if target.stat().st_size != entry["size"]:
                    failures.append(f"文件大小不符：{entry['path']}")
                    continue
                if sha256_file(target) != entry["sha256"]:
                    failures.append(f"文件摘要不符：{entry['path']}")
                    continue
                verified += 1
        if not failures:
            checks.append(f"清单文件摘要全部匹配（{verified} 个文件）")

        bundled_python = extracted / "python" / "python.exe"
        interpreter = bundled_python if bundled_python.is_file() else None
        if interpreter is not None:
            checks.append("使用包内便携 Python")
            probe = subprocess.run(
                [
                    str(interpreter), "-c",
                    "import torch, torchvision, onnxruntime; "
                    "print(torch.__version__, onnxruntime.__version__)",
                ],
                cwd=extracted,
                capture_output=True,
            )
            if probe.returncode == 0:
                checks.append(
                    "便携 Python 依赖导入成功："
                    + probe.stdout.decode("utf-8", "replace").strip()
                )
            else:
                failures.append(
                    "便携 Python 依赖导入失败："
                    + probe.stderr.decode("utf-8", "replace")[-800:]
                )

        package = extracted / "demo" / "model-package"
        image = extracted / "demo" / "test.png"
        run_dir = extracted / "demo" / "run"
        if package.is_dir() and image.is_file():
            exit_code, messages, stderr = run_backend(
                extracted,
                [
                    "backend.runtime.worker", "predict",
                    "--package", "demo/model-package",
                    "--image", "demo/test.png",
                    "--request-id", "req-bundle",
                    "--project-id", "proj-bundle",
                    "--task-id", "task-bundle",
                ],
                interpreter,
            )
            terminal = next(
                (item for item in messages if item.get("message_type") == "result"), None
            )
            if exit_code == 0 and terminal is not None:
                predict_artifact = terminal["payload"]["artifact"]["artifact_id"]
                checks.append(f"解包目录推理成功：{predict_artifact}")
            else:
                failures.append(f"解包目录推理失败（exit {exit_code}）：{stderr[-400:]}")
        else:
            checks.append("包内无演示模型，跳过推理冒烟")

        if run_dir.is_dir():
            exit_code, messages, stderr = run_backend(
                extracted, ["backend.classification", "report", "--run", "demo/run"],
                interpreter,
            )
            payload = messages[-1] if messages else None
            if exit_code == 0 and payload and payload.get("ok"):
                report_accuracy = payload["report"]["accuracy"]
                checks.append(f"训练报告校验成功：准确率 {report_accuracy:.3f}")
            else:
                failures.append(f"训练报告校验失败（exit {exit_code}）：{stderr[-400:]}")
        else:
            checks.append("包内无演示训练运行，跳过报告冒烟")

        desktop_exe = extracted / "desktop" / "app" / "Laitp.Desktop.exe"
        if desktop_exe.is_file():
            desktop_env = {**os.environ}
            if bundled_python.is_file():
                desktop_env["LAITP_PYTHON"] = str(bundled_python)
            launcher = extracted / "start-desktop.bat"
            if launcher.is_file():
                checks.append("存在启动脚本 start-desktop.bat")
            process = subprocess.Popen(
                [str(desktop_exe)],
                cwd=extracted,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=desktop_env,
            )
            time.sleep(4)
            if process.poll() is None:
                checks.append("解包目录桌面程序启动成功（存活 4 秒）")
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
            else:
                failures.append(
                    f"解包目录桌面程序启动即退出（退出码 {process.returncode}）"
                )
        else:
            checks.append("包内无桌面程序，跳过启动冒烟")

        if desktop_exe.is_file():
            self_test_output = extracted / "self-test-result.json"
            selftest_env = {**os.environ}
            if bundled_python.is_file():
                selftest_env["LAITP_PYTHON"] = str(bundled_python)
            selftest_env["LAITP_HOME"] = str(extracted)
            completed = subprocess.run(
                [str(desktop_exe), "--self-test", str(self_test_output)],
                cwd=extracted,
                env=selftest_env,
                capture_output=True,
                timeout=240,
            )
            if completed.returncode == 0 and self_test_output.is_file():
                report = json.loads(self_test_output.read_text(encoding="utf-8"))
                names = [
                    item["name"] for item in report.get("checks", [])
                    if item.get("ok")
                ]
                checks.append("首次运行自检通过：" + ", ".join(names))

                bad_env = {**selftest_env}
                bad_env["LAITP_PYTHON"] = str(extracted / "missing-python.exe")
                bad_output = extracted / "self-test-negative.json"
                negative = subprocess.run(
                    [str(desktop_exe), "--self-test", str(bad_output)],
                    cwd=extracted,
                    env=bad_env,
                    capture_output=True,
                    timeout=240,
                )
                if negative.returncode != 0 and bad_output.is_file():
                    negative_report = json.loads(
                        bad_output.read_text(encoding="utf-8")
                    )
                    python_check = next(
                        (
                            item for item in negative_report.get("checks", [])
                            if item.get("name") == "python"
                        ),
                        None,
                    )
                    if (
                        negative_report.get("ok") is False
                        and python_check is not None
                        and python_check.get("ok") is False
                    ):
                        checks.append("自检失败场景识别正常（错误 Python 路径）")
                    else:
                        failures.append("自检失败场景未标记 Python 检查失败")
                else:
                    failures.append(
                        "自检失败场景未返回失败（exit "
                        f"{negative.returncode}）"
                    )
            else:
                failures.append(
                    "首次运行自检失败（exit "
                    f"{completed.returncode}）："
                    + completed.stderr.decode("utf-8", "replace")[-500:]
                )
    finally:
        if temporary is not None and not args.keep:
            import shutil

            shutil.rmtree(temporary, ignore_errors=True)

    summary = {
        "ok": not failures,
        "bundle": str(bundle) if bundle is not None else None,
        "extracted": str(extracted),
        "size_bytes": bundle.stat().st_size if bundle is not None else None,
        "checks": checks,
        "failures": failures,
        "predict_artifact": predict_artifact,
        "report_accuracy": report_accuracy,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
