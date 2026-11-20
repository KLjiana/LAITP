"""文件完整性检查。

SHA-256 只用于确认包内文件与清单一致，不证明来源可信，也不校验标签语义。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

CHUNK_SIZE = 1024 * 1024


def sha256_bytes(data: bytes) -> str:
    """计算内存中数据的 SHA-256。"""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    """按块计算文件 SHA-256，返回小写十六进制摘要。"""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()
