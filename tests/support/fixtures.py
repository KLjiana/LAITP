"""读取仓库内静态 JSON 样例。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures"


def load_json(relative: str) -> Any:
    path = FIXTURE_ROOT / relative
    return json.loads(path.read_text(encoding="utf-8-sig"))


def manifest_fixture(name: str) -> Any:
    return load_json(f"manifests/{name}")


def envelope_fixture(name: str) -> Any:
    return load_json(f"envelopes/{name}")
