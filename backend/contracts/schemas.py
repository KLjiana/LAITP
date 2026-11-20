"""JSON Schema 加载与结构校验。

Schema 文件是结构约束的唯一来源；这里只负责按 Schema 判定，并把
jsonschema 的报错整理成带定位的稳定错误码，不做任何字段含义推断。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from .errors import Code, Issue, Stage

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"
MANIFEST_SCHEMA = "model-manifest.schema.json"
ENVELOPE_SCHEMA = "message-envelope.schema.json"
MAX_REPORTED_ISSUES = 50


@lru_cache(maxsize=None)
def load_schema(name: str) -> dict[str, Any]:
    """读取并缓存 Schema 文件。文件缺失时抛出 ``FileNotFoundError``。"""
    path = SCHEMA_DIR / name
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=None)
def validator_for(name: str) -> Draft202012Validator:
    return Draft202012Validator(load_schema(name))


def render_location(parts: Iterable[Any]) -> str:
    """把 jsonschema 的路径片段渲染成 ``inputs[0].shape[1]`` 形式。"""
    text = ""
    for part in parts:
        if isinstance(part, int):
            text += f"[{part}]"
        else:
            text = f"{text}.{part}" if text else str(part)
    return text or "$"


def _describe(error: ValidationError) -> tuple[list[Any], str]:
    """返回（更精确的定位, 说明）。针对常见校验器补充字段级定位。"""
    parts = list(error.absolute_path)
    message = error.message
    instance = error.instance

    if error.validator == "required" and isinstance(instance, Mapping):
        missing = [name for name in (error.validator_value or []) if name not in instance]
        if missing:
            parts = [*parts, missing[0]]
            message = f"缺少必填字段 {missing[0]!r}"
    elif error.validator == "additionalProperties" and isinstance(instance, Mapping):
        declared = set((error.schema or {}).get("properties", {}))
        extra = [name for name in instance if name not in declared]
        if extra:
            parts = [*parts, extra[0]]
            message = f"出现契约未定义的字段 {extra[0]!r}"
    elif error.validator == "oneOf":
        message = f"结构不符合任何允许的形式（{message}）"
    elif error.validator == "not" and error.schema == {}:
        message = "该字段不允许出现在此产物或消息中（契约未定义或当前版本禁止）"

    if isinstance(instance, Mapping) and isinstance(instance.get("op"), str):
        message = f"op={instance['op']!r} 的步骤无效：{message}"

    return parts, message


def schema_issues(
    schema_name: str,
    document: Any,
    *,
    code: Code = Code.SCHEMA_INVALID,
    stage: Stage = Stage.SCHEMA,
    limit: int = MAX_REPORTED_ISSUES,
) -> list[Issue]:
    """按指定 Schema 校验文档，返回按定位排序的问题列表。"""
    try:
        validator = validator_for(schema_name)
    except FileNotFoundError:
        return [
            Issue(
                code=Code.SCHEMA_RESOURCE_MISSING,
                stage=Stage.SCHEMA,
                location=schema_name,
                message=f"缺少 Schema 文件 {schema_name}，无法执行结构校验",
            )
        ]

    errors = sorted(
        validator.iter_errors(document),
        key=lambda error: (tuple(str(part) for part in error.absolute_path), error.message),
    )
    issues: list[Issue] = []
    for error in errors[:limit]:
        parts, message = _describe(error)
        issues.append(
            Issue(code=code, stage=stage, location=render_location(parts), message=message)
        )
    if len(errors) > limit:
        issues.append(
            Issue(
                code=code,
                stage=stage,
                location="$",
                message=f"结构问题超过 {limit} 条，仅报告前 {limit} 条（共 {len(errors)} 条）",
            )
        )
    return issues


def read_json(path: Path, *, code: Code, location: str) -> tuple[Any, Issue | None]:
    """读取 UTF-8 JSON 文件。失败时返回 ``(None, Issue)``，不抛异常。"""
    try:
        raw = path.read_bytes()
    except OSError as error:
        return None, Issue(
            code=Code.FILE_UNREADABLE,
            stage=Stage.INTEGRITY,
            location=location,
            message=f"无法读取 {path}：{error.strerror or error}",
        )
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        return None, Issue(
            code=code,
            stage=Stage.SCHEMA,
            location=location,
            message=f"文件不是有效 UTF-8：{error.reason}",
        )
    try:
        return json.loads(text), None
    except json.JSONDecodeError as error:
        return None, Issue(
            code=code,
            stage=Stage.SCHEMA,
            location=location,
            message=f"JSON 解析失败：第 {error.lineno} 行第 {error.colno} 列：{error.msg}",
        )
