from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

NETWORK_IMPORT_PATTERNS = {
    "requests": re.compile(r"^\s*(?:import requests|from requests)", re.M),
    "urllib": re.compile(r"^\s*(?:import urllib|from urllib)", re.M),
    "http": re.compile(r"^\s*(?:import http|from http)", re.M),
    "socket": re.compile(r"^\s*(?:import socket|from socket)", re.M),
    "aiohttp": re.compile(r"^\s*(?:import aiohttp|from aiohttp)", re.M),
    "websockets": re.compile(r"^\s*(?:import websockets|from websockets)", re.M),
    "ftplib": re.compile(r"^\s*(?:import ftplib|from ftplib)", re.M),
}

NETWORK_CS_PATTERN = re.compile(
    r"\b(HttpClient|WebRequest|WebClient|WebSocket|Socket|Dns\.|System\.Net\.Http)\b"
)


def checked_python_files() -> list[Path]:
    files: list[Path] = []
    for root in (ROOT / "backend", ROOT / "scripts"):
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            files.append(path)
    return files


def test_first_party_python_does_not_import_network_modules() -> None:
    problems: list[str] = []
    for path in checked_python_files():
        text = path.read_text(encoding="utf-8")
        for name, pattern in NETWORK_IMPORT_PATTERNS.items():
            if pattern.search(text):
                problems.append(f"{path.relative_to(ROOT)} 导入了网络模块 {name}")
    assert not problems, "\n".join(problems)


def test_desktop_sources_do_not_use_network_apis() -> None:
    source_root = ROOT / "desktop" / "src"
    problems: list[str] = []
    for path in sorted(source_root.rglob("*.cs")):
        if "obj" in path.parts or "bin" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        match = NETWORK_CS_PATTERN.search(text)
        if match:
            problems.append(f"{path.relative_to(ROOT)} 使用了网络 API {match.group(1)}")
    assert not problems, "\n".join(problems)


def test_backend_runtime_has_no_hardcoded_http_urls() -> None:
    problems: list[str] = []
    for path in (ROOT / "backend").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if "http://" in line or "https://" in line:
                problems.append(f"{path.relative_to(ROOT)}:{line_number}: {line.strip()[:100]}")
    assert not problems, "\n".join(problems)
