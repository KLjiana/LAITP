"""测试用工作进程：先发送成功结果，再发送一条迟到的重复结果。"""

from __future__ import annotations

import sys

from backend.runtime.messages import MessageWriter


def main() -> int:
    writer = MessageWriter(
        request_id=sys.argv[1], project_id=sys.argv[2], task_id=sys.argv[3]
    )
    reference = {
        "artifact_id": "art-first",
        "manifest_path": "manifest.json",
        "manifest_sha256": "1" * 64,
    }
    writer.result("validate", reference)
    writer.result(
        "validate",
        {
            "artifact_id": "art-second",
            "manifest_path": "manifest.json",
            "manifest_sha256": "2" * 64,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
