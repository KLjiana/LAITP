"""检测标注/结果草案 Schema 的结构校验与契约隔离测试（P2）。

``schemas/detection/`` 是**草案、未激活**，不属于当前分类契约 ``1.0``，也没有
接入 ``backend.contracts`` 的加载路径。本测试只证明草案文件可被 draft 2020-12
校验器加载并按预期通过/拒绝样例，以及现有分类契约仍拒绝 ``object_detection``；
不表示检测标注、训练、导出、推理或转换能力已经实现或验证通过。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from backend.contracts import DEFAULT_POLICY, validate_model_package
from backend.contracts import schemas as contract_schemas
from backend.contracts.errors import Code, Stage
from tests.support.fixtures import manifest_fixture

REPO_ROOT = Path(__file__).resolve().parents[1]
DETECTION_SCHEMA_DIR = REPO_ROOT / "schemas" / "detection"
DETECTION_FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "detection"
DETECTION_README = DETECTION_SCHEMA_DIR / "README.md"
ANNOTATION_SCHEMA = DETECTION_SCHEMA_DIR / "annotation.schema.json"
RESULT_SCHEMA = DETECTION_SCHEMA_DIR / "detection-result.schema.json"
DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
UTF8_BOM = b"\xef\xbb\xbf"


def read_json(path: Path) -> Any:
    """按不带 BOM 的 UTF-8 读取 JSON。"""
    raw = path.read_bytes()
    assert not raw.startswith(UTF8_BOM), f"{path} 必须是不带 BOM 的 UTF-8"
    return json.loads(raw.decode("utf-8"))


def fixture(name: str) -> Any:
    return read_json(DETECTION_FIXTURE_DIR / name)


def validator(schema_path: Path) -> Draft202012Validator:
    schema = read_json(schema_path)
    assert schema["$schema"] == DRAFT_2020_12, f"{schema_path} 必须是 draft 2020-12"
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


# --------------------------------------------------------------------------- #
# 有效/无效样例
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("schema_path", "fixture_name"),
    [
        (ANNOTATION_SCHEMA, "annotation-valid.json"),
        (RESULT_SCHEMA, "result-valid.json"),
    ],
    ids=["annotation", "detection-result"],
)
def test_valid_fixtures_pass(schema_path: Path, fixture_name: str) -> None:
    validator(schema_path).validate(fixture(fixture_name))


@pytest.mark.parametrize(
    ("schema_path", "fixture_name", "location"),
    [
        (ANNOTATION_SCHEMA, "annotation-invalid-absolute-path.json", "image"),
        (ANNOTATION_SCHEMA, "annotation-invalid-negative-box.json", "w"),
        (RESULT_SCHEMA, "result-invalid-confidence.json", "confidence"),
    ],
    ids=["absolute-path", "negative-box", "confidence-above-one"],
)
def test_invalid_fixtures_are_rejected(
    schema_path: Path, fixture_name: str, location: str
) -> None:
    with pytest.raises(ValidationError) as caught:
        validator(schema_path).validate(fixture(fixture_name))
    parts = [str(part) for part in caught.value.absolute_path]
    assert location in parts, f"{fixture_name} 应在 {location!r} 处被拒绝，实际路径 {parts}"


def test_traversal_image_path_is_rejected() -> None:
    """README 规则：``image`` 禁止 ``..``；结构上由 Schema 直接拒绝。"""
    annotation = copy.deepcopy(fixture("annotation-valid.json"))
    annotation["image"] = "images/../batch-1/001.png"
    with pytest.raises(ValidationError):
        validator(ANNOTATION_SCHEMA).validate(annotation)

    result = copy.deepcopy(fixture("result-valid.json"))
    result["source_image"] = "../batch-1/001.png"
    with pytest.raises(ValidationError):
        validator(RESULT_SCHEMA).validate(result)


def test_unknown_fields_are_rejected() -> None:
    """未知字段按 Schema 拒绝，不提供静默忽略的宽松模式。"""
    annotation = copy.deepcopy(fixture("annotation-valid.json"))
    annotation["unexpected"] = "拼写错误不得被忽略"
    with pytest.raises(ValidationError):
        validator(ANNOTATION_SCHEMA).validate(annotation)

    annotation = copy.deepcopy(fixture("annotation-valid.json"))
    annotation["boxes"][0]["label"] = "标注只存 class_id，不存类别名"
    with pytest.raises(ValidationError):
        validator(ANNOTATION_SCHEMA).validate(annotation)

    result = copy.deepcopy(fixture("result-valid.json"))
    result["detections"][0]["score"] = 0.93
    with pytest.raises(ValidationError):
        validator(RESULT_SCHEMA).validate(result)


# --------------------------------------------------------------------------- #
# 草案状态与契约隔离
# --------------------------------------------------------------------------- #


def test_detection_draft_is_documented_as_inactive() -> None:
    assert DETECTION_SCHEMA_DIR.is_dir(), "草案目录 schemas/detection 必须存在"
    assert ANNOTATION_SCHEMA.is_file()
    assert RESULT_SCHEMA.is_file()
    assert DETECTION_README.is_file(), "草案目录必须有 README.md 说明状态"

    raw = DETECTION_README.read_bytes()
    assert not raw.startswith(UTF8_BOM), "README.md 必须是不带 BOM 的 UTF-8"
    text = raw.decode("utf-8")
    for phrase in (
        "草案",
        "未激活",
        "不属于当前契约",
        "object_detection",
        "CONTRACT_TASK_UNSUPPORTED",
        "升版",
    ):
        assert phrase in text, f"README 必须明确标注/说明 {phrase!r}"

    # 越界检查无法用纯 JSON Schema 表达，README 必须记录由后续校验器实现。
    for rule in ("x + w ≤ width", "y + h ≤ height"):
        assert rule in text, f"README 必须记录 Schema 无法表达的越界规则 {rule!r}"
    assert "tests/test_detection_draft_schemas.py" in text


def test_classification_contract_still_rejects_object_detection(tmp_path: Path) -> None:
    """草案不改变当前分类契约：检测任务仍被校验器拒绝。"""
    manifest = manifest_fixture("valid-classification.json")

    # 1) 现有分类清单样例仍通过当前活跃 Schema，默认契约没有被放宽。
    assert (
        contract_schemas.schema_issues(contract_schemas.MANIFEST_SCHEMA, manifest) == []
    )

    # 2) object_detection 在清单 Schema 中只是预留枚举，结构合法不等于受支持。
    detection_manifest = copy.deepcopy(manifest)
    detection_manifest["task"] = "object_detection"
    assert (
        contract_schemas.schema_issues(
            contract_schemas.MANIFEST_SCHEMA, detection_manifest
        )
        == []
    )

    # 3) 走真实校验入口：版本与结构通过后，任务检查仍返回稳定拒绝错误码。
    package = tmp_path / "object-detection-package"
    package.mkdir()
    (package / "manifest.json").write_text(
        json.dumps(detection_manifest, ensure_ascii=False), encoding="utf-8"
    )
    report = validate_model_package(package, runtime_profile=None)

    assert not report.ok
    assert report.has(Code.TASK_UNSUPPORTED)
    assert report.codes() == (Code.TASK_UNSUPPORTED.value,)
    assert report.issues[0].stage is Stage.SEMANTICS
    assert report.issues[0].location == "task"

    # 4) 默认策略与活跃 Schema 加载点仍只覆盖分类 1.0。
    assert (DEFAULT_POLICY.contract_major, DEFAULT_POLICY.contract_minor) == (1, 0)
    assert DEFAULT_POLICY.supported_tasks == ("image_classification",)
    active_names = {
        contract_schemas.MANIFEST_SCHEMA,
        contract_schemas.ENVELOPE_SCHEMA,
    }
    assert all(not name.startswith("detection/") for name in active_names)
    assert contract_schemas.SCHEMA_DIR == REPO_ROOT / "schemas"
