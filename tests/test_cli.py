"""校验命令行冒烟测试（开发入口，不是 T06 的正式 CLI）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.contracts.cli import main
from tests.support.packages import build_package, reopen_manifest, save_manifest
from tests.support.fixtures import FIXTURE_ROOT


def _package_args(package: Path) -> list[str]:
    return [
        "package",
        str(package),
        "--runtime",
        "onnxruntime",
        "--runtime-version",
        "1.19.2",
        "--platform",
        "windows-x64",
        "--capability",
        "onnxruntime-cpu",
    ]


def test_cli_reports_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    package = build_package(tmp_path / "pkg")
    exit_code = main(_package_args(package))
    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["ok"] is True
    assert output["issues"] == []


def test_cli_reports_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    package = build_package(tmp_path / "pkg")
    manifest = reopen_manifest(package)
    manifest["model"]["opset"] = 13
    save_manifest(package, manifest)
    exit_code = main(_package_args(package))
    output = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert output["ok"] is False
    assert output["issues"][0]["code"] == "CONTRACT_MODEL_OPSET_MISMATCH"


def test_cli_reports_missing_runtime_profile(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    package = build_package(tmp_path / "pkg")
    exit_code = main(["package", str(package)])
    output = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert [issue["code"] for issue in output["issues"]] == [
        "CONTRACT_RUNTIME_PROFILE_MISSING"
    ]


def test_cli_envelope_fixture(capsys: pytest.CaptureFixture[str]) -> None:
    path = FIXTURE_ROOT / "envelopes" / "valid-result-predict.json"
    exit_code = main(["envelope", str(path)])
    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["ok"] is True


def test_cli_rejects_invalid_envelope_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    exit_code = main(["envelope", str(path)])
    output = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert output["issues"][0]["code"] == "ENVELOPE_JSON_INVALID"


def test_cli_requires_version_with_runtime(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    package = build_package(tmp_path / "pkg")
    with pytest.raises(SystemExit):
        main(["package", str(package), "--runtime", "onnxruntime"])
