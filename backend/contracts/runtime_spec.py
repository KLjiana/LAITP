"""运行时版本范围解析与目标运行环境描述。

契约要求产物声明目标平台、运行时和版本兼容范围。这里实现清单使用的
最小版本语法（逗号分隔的比较式），不做隐式宽松匹配：不带比较符表示精确版本。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_COMPARATOR_RE = re.compile(r"^(>=|<=|==|=|>|<)?\s*(\d+(?:\.\d+){0,2})$")

Version = tuple[int, int, int]
Comparator = tuple[str, Version]


class VersionSyntaxError(ValueError):
    """版本或版本范围文本不符合约定语法。"""


@dataclass(frozen=True)
class RuntimeProfile:
    """当前运行环境的能力声明，用于校验产物 ``runtime`` 字段。"""

    runtime: str
    version: str
    platform: str
    capabilities: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        parse_version(self.version)


def parse_version(text: str) -> Version:
    """解析 ``1.19``、``1.19.2`` 形式的版本，补零为三段。"""
    if not isinstance(text, str):
        raise VersionSyntaxError("版本必须是字符串")
    parts = text.split(".")
    if not 1 <= len(parts) <= 3 or not all(part.isdigit() for part in parts):
        raise VersionSyntaxError(f"版本 {text!r} 不是 major[.minor[.patch]] 形式")
    numbers = [int(part) for part in parts]
    numbers.extend([0] * (3 - len(numbers)))
    return numbers[0], numbers[1], numbers[2]


def parse_range(text: str) -> tuple[Comparator, ...]:
    """解析 ``>=1.18.0,<2.0.0`` 形式的版本范围。"""
    if not isinstance(text, str) or not text.strip():
        raise VersionSyntaxError("版本范围不能为空")
    comparators: list[Comparator] = []
    for raw in text.split(","):
        match = _COMPARATOR_RE.match(raw.strip())
        if match is None:
            raise VersionSyntaxError(f"无法解析版本条件 {raw.strip()!r}")
        operator = match.group(1) or "=="
        if operator == "=":
            operator = "=="
        comparators.append((operator, parse_version(match.group(2))))
    return tuple(comparators)


def _compare(left: Version, right: Version) -> int:
    return (left > right) - (left < right)


def accepts(comparators: tuple[Comparator, ...], version: Version) -> bool:
    for operator, bound in comparators:
        result = _compare(version, bound)
        if operator == "==" and result != 0:
            return False
        if operator == ">=" and result < 0:
            return False
        if operator == ">" and result <= 0:
            return False
        if operator == "<=" and result > 0:
            return False
        if operator == "<" and result >= 0:
            return False
    return True


def range_accepts(text: str, version: str) -> bool:
    """便捷函数：判断版本是否落在声明范围内。语法错误向上抛出。"""
    return accepts(parse_range(text), parse_version(version))
