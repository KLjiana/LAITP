"""包内相对路径规则测试。"""

from __future__ import annotations

import pytest

from backend.contracts import paths


@pytest.mark.parametrize(
    "value",
    [
        "model.onnx",
        "validation/sample.png",
        "学生 项目/模型 包 v1/model.onnx",
        "a.b/c_d-e.json",
    ],
)
def test_portable_paths_are_accepted(value: str) -> None:
    assert paths.check_rel_path(value) is None


@pytest.mark.parametrize(
    "value",
    [
        "",
        "/data/model.onnx",
        "\\\\server\\share\\model.onnx",
        "C:/data/model.onnx",
        "validation\\sample.png",
        "a//b",
        "a/",
        "../model.onnx",
        "a/../../b",
        "a/./b",
        "CON.txt",
        "a/NUL.bin",
        "a/b. ",
        "a/b.",
        "a/<b>.json",
        "a/\x00b",
        " leading/model.onnx",
    ],
)
def test_non_portable_paths_are_rejected(value: str) -> None:
    assert paths.check_rel_path(value) is not None


def test_resolve_inside_package(tmp_path) -> None:
    target = paths.resolve_in_package(tmp_path, "validation/sample.png")
    assert target is not None
    assert target == (tmp_path / "validation" / "sample.png").resolve()


def test_resolve_outside_package_is_rejected(tmp_path) -> None:
    (tmp_path / "pkg").mkdir()
    assert paths.resolve_in_package(tmp_path / "pkg", "../outside.bin") is None
