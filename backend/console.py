"""标准输出辅助。

契约要求进程标准输出使用 UTF-8、按行 JSON。Windows 控制台代码页可能是 GBK，
必须直接写字节流，不能依赖 ``sys.stdout`` 的文本编码。
"""

from __future__ import annotations

import json
import sys
from typing import Any


def emit_json(payload: Any) -> None:
    """把对象以 UTF-8 JSON 输出到标准输出并换行。"""
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    data = text.encode("utf-8")
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write(data)
        buffer.flush()
    else:  # pragma: no cover - 只有被替换成无缓冲文本流时使用
        sys.stdout.write(text)
