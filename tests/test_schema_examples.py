"""静态样例的结构校验（T01）。

样例文件中的 SHA-256 是占位值，只用于演示结构；文件摘要、标签和真实张量
的检查在 ``test_manifest_package.py`` 中用生成的完整产物包验证。
"""

from __future__ import annotations

import copy

import pytest
from jsonschema import Draft202012Validator

from backend.contracts import schemas
from backend.contracts.errors import Code
from tests.support.fixtures import envelope_fixture, manifest_fixture


@pytest.mark.parametrize(
    "name", [schemas.MANIFEST_SCHEMA, schemas.ENVELOPE_SCHEMA]
)
def test_schema_files_are_valid_draft_2020_12(name: str) -> None:
    Draft202012Validator.check_schema(schemas.load_schema(name))


def test_valid_manifest_fixture_passes_schema() -> None:
    issues = schemas.schema_issues(
        schemas.MANIFEST_SCHEMA, manifest_fixture("valid-classification.json")
    )
    assert issues == []


@pytest.mark.parametrize(
    ("name", "expected_location"),
    [
        ("invalid-missing-runtime.json", "runtime"),
        ("invalid-unknown-op.json", "preprocessing.steps[0]"),
        ("invalid-absolute-path.json", "files[0].path"),
    ],
)
def test_invalid_manifest_fixtures_are_rejected(
    name: str, expected_location: str
) -> None:
    issues = schemas.schema_issues(schemas.MANIFEST_SCHEMA, manifest_fixture(name))
    assert issues, f"{name} 应当被 Schema 拒绝"
    assert all(issue.code is Code.SCHEMA_INVALID for issue in issues)
    assert any(issue.location == expected_location for issue in issues)


def test_traversal_path_is_not_a_schema_concern() -> None:
    """目录穿越在 Schema 中结构合法，必须由路径校验器返回 CONTRACT_PATH_INVALID。"""
    issues = schemas.schema_issues(
        schemas.MANIFEST_SCHEMA, manifest_fixture("invalid-traversal-path.json")
    )
    assert issues == []


def test_schema_is_not_enough_for_version_compatibility() -> None:
    """契约版本格式合法但主版本不受支持，必须由校验器拒绝而不是 Schema。"""
    manifest = manifest_fixture("valid-classification.json")
    manifest["contract_version"] = "2.0"
    assert schemas.schema_issues(schemas.MANIFEST_SCHEMA, manifest) == []


def test_unknown_manifest_field_is_rejected() -> None:
    manifest = copy.deepcopy(manifest_fixture("valid-classification.json"))
    manifest["author"] = "someone"
    issues = schemas.schema_issues(schemas.MANIFEST_SCHEMA, manifest)
    assert [issue.location for issue in issues] == ["author"]


def test_unknown_envelope_field_is_rejected() -> None:
    envelope = copy.deepcopy(envelope_fixture("valid-progress.json"))
    envelope["host_pid"] = 4242
    issues = schemas.schema_issues(schemas.ENVELOPE_SCHEMA, envelope)
    assert [issue.location for issue in issues] == ["host_pid"]


def test_training_manifest_must_not_declare_source() -> None:
    manifest = copy.deepcopy(manifest_fixture("valid-classification.json"))
    manifest["provenance"]["source"] = {
        "artifact_id": "art-20261116-0001",
        "manifest_sha256": "0" * 64,
    }
    issues = schemas.schema_issues(schemas.MANIFEST_SCHEMA, manifest)
    assert [issue.location for issue in issues] == ["provenance.source"]


def test_non_predict_result_must_not_carry_predictions() -> None:
    envelope = copy.deepcopy(envelope_fixture("valid-result-predict.json"))
    envelope["payload"]["operation"] = "train"
    issues = schemas.schema_issues(schemas.ENVELOPE_SCHEMA, envelope)
    assert issues and issues[0].location == "payload.predictions"
