"""测试用慢速工作进程：持续发送进度直到被父进程终止。"""

from __future__ import annotations

import sys
import time

from backend.runtime.messages import MessageWriter


def main() -> int:
    writer = MessageWriter(
        request_id=sys.argv[1], project_id=sys.argv[2], task_id=sys.argv[3]
    )
    for index in range(1000):
        writer.progress("working", index, None)
        time.sleep(0.05)
    writer.result(
        "validate",
        {
            "artifact_id": "art-slow",
            "manifest_path": "manifest.json",
            "manifest_sha256": "0" * 64,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
