"""消息信封校验测试。"""

from __future__ import annotations

import copy

import pytest

from backend.contracts import validate_envelope
from backend.contracts.envelope import ProtocolPolicy
from backend.contracts.errors import Code
from tests.support.fixtures import envelope_fixture


def test_valid_progress_envelope() -> None:
    report = validate_envelope(envelope_fixture("valid-progress.json"))
    assert report.ok, report.issues


def test_valid_predict_result_envelope() -> None:
    report = validate_envelope(envelope_fixture("valid-result-predict.json"))
    assert report.ok, report.issues


def test_valid_error_envelope() -> None:
    report = validate_envelope(envelope_fixture("valid-error.json"))
    assert report.ok, report.issues


def test_valid_cancelled_envelope() -> None:
    report = validate_envelope(envelope_fixture("valid-cancelled.json"))
    assert report.ok, report.issues


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("invalid-missing-sequence.json", Code.ENVELOPE_SCHEMA_INVALID),
        ("invalid-unknown-message-type.json", Code.ENVELOPE_SCHEMA_INVALID),
        ("invalid-version-2.0.json", Code.ENVELOPE_VERSION_UNSUPPORTED_MAJOR),
        ("invalid-artifact-mismatch.json", Code.ENVELOPE_ARTIFACT_MISMATCH),
        ("invalid-predict-without-predictions.json", Code.ENVELOPE_SCHEMA_INVALID),
    ],
)
def test_invalid_envelopes_are_rejected(name: str, code: Code) -> None:
    report = validate_envelope(envelope_fixture(name))
    assert report.has(code), report.issues


def test_progress_beyond_total_is_rejected() -> None:
    envelope = copy.deepcopy(envelope_fixture("valid-progress.json"))
    envelope["payload"]["completed"] = 61
    report = validate_envelope(envelope)
    assert report.has(Code.ENVELOPE_PROGRESS_INVALID)
    assert report.issues[0].location == "payload.completed"


def test_progress_with_unknown_total_is_allowed() -> None:
    envelope = copy.deepcopy(envelope_fixture("valid-progress.json"))
    envelope["payload"]["total"] = None
    assert validate_envelope(envelope).ok


def test_minor_protocol_version_is_rejected() -> None:
    envelope = copy.deepcopy(envelope_fixture("valid-progress.json"))
    envelope["protocol_version"] = "1.1"
    report = validate_envelope(envelope)
    assert report.has(Code.ENVELOPE_VERSION_UNSUPPORTED_MINOR)


def test_result_requires_artifact_id() -> None:
    envelope = copy.deepcopy(envelope_fixture("valid-result-predict.json"))
    envelope["artifact_id"] = None
    report = validate_envelope(envelope)
    assert report.has(Code.ENVELOPE_ARTIFACT_MISMATCH)


def test_duplicate_prediction_class_is_rejected() -> None:
    envelope = copy.deepcopy(envelope_fixture("valid-result-predict.json"))
    envelope["payload"]["predictions"][1]["class_id"] = 0
    report = validate_envelope(envelope)
    assert report.has(Code.ENVELOPE_PREDICTION_INVALID)


def test_manifest_path_traversal_is_rejected_by_schema() -> None:
    envelope = copy.deepcopy(envelope_fixture("valid-result-predict.json"))
    envelope["payload"]["artifact"]["manifest_path"] = "../manifest.json"
    report = validate_envelope(envelope)
    assert report.has(Code.ENVELOPE_SCHEMA_INVALID)


def test_unsupported_message_type_from_policy() -> None:
    envelope = envelope_fixture("valid-progress.json")
    policy = ProtocolPolicy(supported_message_types=("result", "error"))
    report = validate_envelope(envelope, policy=policy)
    assert report.has(Code.ENVELOPE_MESSAGE_TYPE_UNSUPPORTED)


def test_non_object_envelope_is_rejected() -> None:
    report = validate_envelope(["not", "an", "envelope"])
    assert report.has(Code.ENVELOPE_SCHEMA_INVALID)
