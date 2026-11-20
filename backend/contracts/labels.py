"""标签文件读取。

``labels.json`` 必须是 UTF-8 有序字符串数组，数组下标就是类别 ID；
加载时不得排序或重新编号。这里只读取并做基本清洗，数量与类别轴对应关系
由清单校验器负责。
"""

from __future__ import annotations

import json
from pathlib import Path


class LabelsError(Exception):
    """标签文件不符合契约。``reason`` 是面向用户的中文说明。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def load_labels(path: Path) -> list[str]:
    """读取标签数组。文件不存在时抛出 ``FileNotFoundError``。"""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raise
    except OSError as error:
        raise LabelsError(f"无法读取标签文件：{error.strerror or error}") from error

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise LabelsError(f"标签文件不是有效 UTF-8：{error.reason}") from error

    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise LabelsError(
            f"标签文件 JSON 解析失败：第 {error.lineno} 行第 {error.colno} 列：{error.msg}"
        ) from error

    if not isinstance(data, list):
        raise LabelsError("标签文件必须是字符串数组")
    if len(data) < 2:
        raise LabelsError("标签数量至少为 2")

    labels: list[str] = []
    for index, item in enumerate(data):
        if not isinstance(item, str):
            raise LabelsError(f"标签 [{index}] 必须是字符串")
        if not item:
            raise LabelsError(f"标签 [{index}] 不能为空")
        if item != item.strip():
            raise LabelsError(f"标签 [{index}] 首尾含空白字符")
        if any(ord(char) < 32 or ord(char) == 127 for char in item):
            raise LabelsError(f"标签 [{index}] 含控制字符")
        if len(item) > 128:
            raise LabelsError(f"标签 [{index}] 超过 128 个字符")
        labels.append(item)
    return labels


def duplicate_index(labels: list[str]) -> int | None:
    """返回第一个重复标签的下标，没有重复时返回 ``None``。"""
    seen: set[str] = set()
    for index, label in enumerate(labels):
        if label in seen:
            return index
        seen.add(label)
    return None
