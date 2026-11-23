from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "evidence"


def _strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _strings(child)]
    if isinstance(value, list):
        return [item for child in value for item in _strings(child)]
    return []


def load_evidence() -> dict[str, dict]:
    files = sorted(EVIDENCE.glob("*.json"))
    assert files, "docs/evidence 下应存在归档证据 JSON"
    return {path.name: json.loads(path.read_text(encoding="utf-8")) for path in files}


def test_evidence_json_parse_and_have_format() -> None:
    for name, data in load_evidence().items():
        assert isinstance(data, dict), name
        assert str(data.get("format", "")).startswith("laitp-k230"), name


def test_evidence_json_have_no_development_absolute_paths() -> None:
    for name, data in load_evidence().items():
        for text in _strings(data):
            lowered = text.lower()
            assert "c:\\users\\" not in lowered, f"{name} 含开发机用户目录：{text}"
            assert not lowered.startswith("d:\\"), f"{name} 含开发机绝对路径：{text}"


def test_readiness_evidence_consistent_shape() -> None:
    for name, data in load_evidence().items():
        if data.get("format") != "laitp-k230-readiness-1.0":
            continue
        assert data["overall"] in {"blocked", "ready-for-conversion-attempt"}, name
        assert data["checks"], name
        ids = {item["id"] for item in data["checks"]}
        assert {"toolchain-pinned", "nncase-installed", "calibration-data"} <= ids, name
