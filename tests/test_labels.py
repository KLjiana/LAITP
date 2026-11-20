"""标签文件读取测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.contracts.labels import LabelsError, duplicate_index, load_labels


def _write(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def test_loads_ordered_labels(tmp_path: Path) -> None:
    path = _write(tmp_path / "labels.json", ["水杯", "书本", "笔袋"])
    assert load_labels(path) == ["水杯", "书本", "笔袋"]


def test_order_is_preserved(tmp_path: Path) -> None:
    path = _write(tmp_path / "labels.json", ["笔袋", "水杯"])
    assert load_labels(path) == ["笔袋", "水杯"]


@pytest.mark.parametrize(
    "value",
    [
        {"labels": ["a", "b"]},
        ["only-one"],
        ["水杯", ""],
        ["水杯", " 书本"],
        ["水杯", 7],
    ],
)
def test_invalid_label_files_are_rejected(tmp_path: Path, value: object) -> None:
    path = _write(tmp_path / "labels.json", value)
    with pytest.raises(LabelsError):
        load_labels(path)


def test_non_utf8_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "labels.json"
    path.write_bytes(b"[\xff\xfe]")
    with pytest.raises(LabelsError):
        load_labels(path)


def test_duplicate_index() -> None:
    assert duplicate_index(["水杯", "书本", "水杯"]) == 2
    assert duplicate_index(["水杯", "书本"]) is None
