"""产物包内的相对路径规则。

契约要求路径以包根目录为基准，禁止绝对路径、盘符、反斜杠、目录穿越，
并保证复制到中文/含空格路径后仍可打开。Schema 只做粗略字符约束，
这里补规范化、保留名、末尾空格或点等跨平台可移植性检查。
"""

from __future__ import annotations

from pathlib import Path

MAX_PATH_LENGTH = 240
MAX_SEGMENT_LENGTH = 200
_FORBIDDEN_CHARS = set('<>:"|?*')
_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(0, 10)),
    *(f"LPT{index}" for index in range(0, 10)),
}


def check_rel_path(raw: object) -> str | None:
    """检查包内相对路径，合法返回 ``None``，否则返回中文原因。"""
    if not isinstance(raw, str):
        return "路径必须是字符串"
    if not raw:
        return "路径不能为空"
    if len(raw) > MAX_PATH_LENGTH:
        return f"路径长度超过 {MAX_PATH_LENGTH} 个字符"
    if any(ord(char) < 32 or ord(char) == 127 for char in raw):
        return "路径包含控制字符"
    if raw.startswith(("/", "\\")):
        return "禁止绝对路径"
    if len(raw) >= 2 and raw[1] == ":" and raw[0].isalpha():
        return "禁止 Windows 盘符路径"
    if "\\" in raw:
        return "路径分隔符必须使用 /"
    if "//" in raw:
        return "路径包含空段"
    if raw.endswith("/"):
        return "路径不能以 / 结尾"

    for segment in raw.split("/"):
        if segment in (".", ".."):
            return "禁止目录穿越或当前目录段"
        if len(segment) > MAX_SEGMENT_LENGTH:
            return f"单个路径段超过 {MAX_SEGMENT_LENGTH} 个字符"
        if segment != segment.strip():
            return f"路径段 {segment!r} 首尾含空白"
        if segment.endswith("."):
            return f"路径段 {segment!r} 以点结尾"
        if any(char in _FORBIDDEN_CHARS for char in segment):
            return f"路径段 {segment!r} 含非法字符"
        if segment.split(".")[0].upper() in _RESERVED_NAMES:
            return f"路径段 {segment!r} 使用 Windows 保留名"
    return None


def resolve_in_package(root: Path, rel: str) -> Path | None:
    """把相对路径解析到包内。

    返回 ``None`` 表示解析结果落在包外（例如符号链接指向外部），
    调用方必须按路径错误处理，不能继续读取文件。
    """
    try:
        base = Path(root).resolve(strict=False)
        candidate = (base / rel).resolve(strict=False)
    except OSError:
        return None
    try:
        candidate.relative_to(base)
    except ValueError:
        return None
    return candidate
