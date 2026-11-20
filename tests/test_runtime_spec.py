"""版本范围与运行环境描述测试。"""

from __future__ import annotations

import pytest

from backend.contracts.runtime_spec import (
    RuntimeProfile,
    VersionSyntaxError,
    parse_range,
    parse_version,
    range_accepts,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1.19.2", (1, 19, 2)),
        ("1.19", (1, 19, 0)),
        ("2", (2, 0, 0)),
    ],
)
def test_parse_version(text: str, expected: tuple[int, int, int]) -> None:
    assert parse_version(text) == expected


@pytest.mark.parametrize("text", ["", "1.2.3.4", "a.b", "1..2", "-1.0"])
def test_parse_version_rejects_invalid_input(text: str) -> None:
    with pytest.raises(VersionSyntaxError):
        parse_version(text)


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("1.19.2", True),
        ("1.18.0", True),
        ("2.0.0", False),
        ("1.17.9", False),
    ],
)
def test_range_accepts(version: str, expected: bool) -> None:
    assert range_accepts(">=1.18.0,<2.0.0", version) is expected


def test_exact_version_means_exact_patch() -> None:
    assert range_accepts("1.19.2", "1.19.2") is True
    assert range_accepts("1.19.2", "1.19.3") is False


def test_invalid_range_is_rejected() -> None:
    with pytest.raises(VersionSyntaxError):
        parse_range(">=1.18,<two")


def test_runtime_profile_validates_version() -> None:
    RuntimeProfile(runtime="onnxruntime", version="1.19.2", platform="windows-x64")
    with pytest.raises(VersionSyntaxError):
        RuntimeProfile(runtime="onnxruntime", version="latest", platform="windows-x64")
