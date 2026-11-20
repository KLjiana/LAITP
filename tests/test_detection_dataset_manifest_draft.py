"""检测数据集清单 2.0 草案 Schema 的样例校验与契约隔离测试（P2）。

``schemas/detection/dataset-manifest-2.0-draft.schema.json`` 是**草案、未激活**：
不属于当前分类契约 ``1.0``，没有加入 ``schemas/`` 根目录，也没有被 ``backend/``
的任何生产代码加载。本测试只证明该草案可被 draft 2020-12 校验器加载并按预期
通过/拒绝样例、``schema_version``/``dataset_version`` 固定为 ``2.0-draft``、
样本追溯字段（``sha256``/``width``/``height``/``box_count``）必填与 ``sha256``
格式、``box_count = 0`` 及可选字段行为，以及现有分类契约（模型包与数据集清单）
仍只支持分类；不表示检测数据集清单、标注、训练、导出、推理或转换能力已经
实现或验证通过。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from backend.classification.dataset import (
    DATASET_SCHEMA_NAME,
    DEFAULT_DATASET_POLICY,
)
from backend.contracts import DEFAULT_POLICY, validate_model_package
from backend.contracts import schemas as contract_schemas
from backend.contracts.errors import Code
from tests.support.packages import (
    build_package,
    reopen_manifest,
    runtime_profile,
    save_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DETECTION_SCHEMA_DIR = REPO_ROOT / "schemas" / "detection"
DATASET_SCHEMA = DETECTION_SCHEMA_DIR / "dataset-manifest-2.0-draft.schema.json"
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "detection"
VALID_FIXTURE = FIXTURE_DIR / "dataset-manifest-valid.json"
INVALID_FIXTURE = FIXTURE_DIR / "dataset-manifest-invalid-split.json"
INVALID_SHA_FIXTURE = FIXTURE_DIR / "dataset-manifest-invalid-sha.json"
DETECTION_README = DETECTION_SCHEMA_DIR / "README.md"
DRAFT_DOC = REPO_ROOT / "docs" / "detection-contract-draft.md"
DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
DRAFT_VERSION = "2.0-draft"
UTF8_BOM = b"\xef\xbb\xbf"


def read_json(path: Path) -> Any:
    """按不带 BOM 的 UTF-8 读取 JSON。"""
    raw = path.read_bytes()
    assert not raw.startswith(UTF8_BOM), f"{path} 必须是不带 BOM 的 UTF-8"
    return json.loads(raw.decode("utf-8"))


def validator() -> Draft202012Validator:
    schema = read_json(DATASET_SCHEMA)
    assert schema["$schema"] == DRAFT_2020_12, f"{DATASET_SCHEMA} 必须是 draft 2020-12"
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


# --------------------------------------------------------------------------- #
# 有效/无效样例
# --------------------------------------------------------------------------- #


def test_valid_fixture_passes_draft_schema() -> None:
    manifest = read_json(VALID_FIXTURE)
    validator().validate(manifest)  # 不抛错即通过

    assert manifest["schema_version"] == DRAFT_VERSION
    assert manifest["dataset_version"] == DRAFT_VERSION, (
        "可选 dataset_version 只允许草案标记 2.0-draft"
    )
    assert len(manifest["classes"]) == 1, "草案允许单类检测，与分类清单至少 2 类不同"
    assert set(manifest["splits"]) == {"train", "val", "test"}

    samples = [
        sample for split in manifest["splits"].values() for sample in split["samples"]
    ]
    assert 2 <= len(samples) <= 3, "有效样例应覆盖 2～3 个样本"

    required = {"image", "annotation", "sha256", "width", "height", "box_count"}
    optional = {"capture_batch"}
    assert all(required <= set(sample) for sample in samples), (
        "每个样本都必须带 image/annotation 与 sha256/width/height/box_count 追溯字段"
    )
    assert all(set(sample) - required <= optional for sample in samples), (
        "样本只允许 capture_batch 一个可选字段"
    )
    for sample in samples:
        assert len(sample["sha256"]) == 64
        assert sample["sha256"] == sample["sha256"].lower()
        assert int(sample["sha256"], 16) >= 0
        assert sample["width"] >= 1 and sample["height"] >= 1
        assert sample["box_count"] >= 0


def test_invalid_fixture_is_rejected() -> None:
    invalid = read_json(INVALID_FIXTURE)
    errors = list(validator().iter_errors(invalid))
    locations = {tuple(error.absolute_path) for error in errors}

    assert ("splits", "val") in locations, f"缺少 samples 的划分必须被拒绝，实际定位 {locations}"
    assert ("splits", "train", "samples", 0, "image") in locations, (
        f"绝对路径 image 必须被拒绝，实际定位 {locations}"
    )
    with pytest.raises(ValidationError):
        validator().validate(invalid)

    # 样例之外再确认同类越界与未知字段也被拒绝，不提供宽松模式。
    valid = read_json(VALID_FIXTURE)

    absolute = copy.deepcopy(valid)
    absolute["splits"]["train"]["samples"][0]["image"] = "/data/images/batch-1/001.png"
    with pytest.raises(ValidationError):
        validator().validate(absolute)

    traversal = copy.deepcopy(valid)
    traversal["splits"]["test"]["samples"][0]["annotation"] = (
        "annotations/../batch-3/003.json"
    )
    with pytest.raises(ValidationError):
        validator().validate(traversal)

    unknown = copy.deepcopy(valid)
    unknown["unexpected_field"] = "拼写错误不得被忽略"
    with pytest.raises(ValidationError):
        validator().validate(unknown)

    empty_classes = copy.deepcopy(valid)
    empty_classes["classes"] = []
    with pytest.raises(ValidationError):
        validator().validate(empty_classes)


def test_missing_traceability_fields_are_rejected() -> None:
    """sha256/width/height/box_count 是追溯必需字段，样本缺任一字段都必须被拒绝。"""
    valid = read_json(VALID_FIXTURE)
    for field in ("sha256", "width", "height", "box_count"):
        broken = copy.deepcopy(valid)
        del broken["splits"]["train"]["samples"][0][field]

        errors = list(validator().iter_errors(broken))
        locations = {tuple(error.absolute_path) for error in errors}
        assert any(field in error.message for error in errors), (
            f"缺少 {field} 必须报必填错误，实际错误 {[error.message for error in errors]}"
        )
        assert ("splits", "train", "samples", 0) in locations, (
            f"缺少 {field} 的错误必须定位到样本对象，实际定位 {locations}"
        )
        with pytest.raises(ValidationError):
            validator().validate(broken)


def test_invalid_sha256_fixture_and_uppercase_value_are_rejected() -> None:
    """sha256 必须是 64 位小写十六进制；示例用 63 位值，大写同长度值也被拒。"""
    invalid = read_json(INVALID_SHA_FIXTURE)
    errors = list(validator().iter_errors(invalid))
    locations = {tuple(error.absolute_path) for error in errors}
    assert ("splits", "train", "samples", 0, "sha256") in locations, (
        f"非法 sha256 必须被拒绝，实际定位 {locations}"
    )
    with pytest.raises(ValidationError):
        validator().validate(invalid)

    uppercase = copy.deepcopy(read_json(VALID_FIXTURE))
    sample = uppercase["splits"]["train"]["samples"][0]
    sample["sha256"] = sample["sha256"].upper()
    with pytest.raises(ValidationError):
        validator().validate(uppercase)


def test_zero_box_count_is_allowed_and_negative_is_rejected() -> None:
    """``box_count = 0`` 是空标注的结构表达（Q6 未决），``-1`` 必须被拒绝。"""
    zero = copy.deepcopy(read_json(VALID_FIXTURE))
    zero["splits"]["train"]["samples"][0]["box_count"] = 0
    validator().validate(zero)  # 不抛错即通过

    negative = copy.deepcopy(read_json(VALID_FIXTURE))
    negative["splits"]["train"]["samples"][0]["box_count"] = -1
    with pytest.raises(ValidationError):
        validator().validate(negative)


# --------------------------------------------------------------------------- #
# 可选字段
# --------------------------------------------------------------------------- #


def test_optional_dataset_version_only_accepts_draft_marker() -> None:
    """dataset_version 可选；出现时只能与 schema_version 同为 2.0-draft。"""
    manifest = read_json(VALID_FIXTURE)

    without_version = copy.deepcopy(manifest)
    del without_version["dataset_version"]
    validator().validate(without_version)  # 可选字段，缺省合法

    wrong_version = copy.deepcopy(manifest)
    wrong_version["dataset_version"] = "2.0"
    with pytest.raises(ValidationError) as caught:
        validator().validate(wrong_version)
    parts = [str(part) for part in caught.value.absolute_path]
    assert "dataset_version" in parts


def test_capture_batch_is_optional_but_must_be_non_empty() -> None:
    """capture_batch 可选且待决；一旦出现必须是非空字符串。"""
    manifest = copy.deepcopy(read_json(VALID_FIXTURE))
    for split in manifest["splits"].values():
        for sample in split["samples"]:
            del sample["capture_batch"]
    validator().validate(manifest)  # 可选字段，缺省合法

    empty_batch = copy.deepcopy(read_json(VALID_FIXTURE))
    empty_batch["splits"]["test"]["samples"][0]["capture_batch"] = ""
    with pytest.raises(ValidationError):
        validator().validate(empty_batch)


# --------------------------------------------------------------------------- #
# 版本固定与契约隔离
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "wrong_version",
    ["2.0", "1.0", "2.1-draft", "2.0-draft ", ""],
    ids=[
        "doc-candidate-2.0",
        "classification-1.0",
        "other-draft-minor",
        "trailing-space",
        "empty",
    ],
)
def test_schema_version_is_fixed_to_draft_marker(wrong_version: str) -> None:
    """草案版本固定为 ``2.0-draft``；文档候选值 ``2.0`` 与分类 ``1.0`` 都被拒绝。"""
    schema = read_json(DATASET_SCHEMA)
    assert schema["properties"]["schema_version"]["const"] == DRAFT_VERSION

    manifest = copy.deepcopy(read_json(VALID_FIXTURE))
    manifest["schema_version"] = wrong_version
    with pytest.raises(ValidationError) as caught:
        validator().validate(manifest)
    parts = [str(part) for part in caught.value.absolute_path]
    assert "schema_version" in parts


def test_classification_contracts_remain_isolated(tmp_path: Path) -> None:
    """草案不改变当前分类契约：模型包仍拒绝检测任务，数据清单仍只覆盖分类 1.x。"""
    # 1) backend.contracts 默认策略仍只支持分类 1.0。
    assert (DEFAULT_POLICY.contract_major, DEFAULT_POLICY.contract_minor) == (1, 0)
    assert DEFAULT_POLICY.supported_tasks == ("image_classification",)

    # 2) 真实校验入口仍拒绝检测任务；调用方式同
    #    tests/test_manifest_package.py::test_unimplemented_task_is_rejected。
    package = build_package(tmp_path / "package")
    manifest = reopen_manifest(package)
    manifest["task"] = "object_detection"
    save_manifest(package, manifest, refresh=True)
    report = validate_model_package(package, runtime_profile=runtime_profile())
    assert not report.ok
    assert report.has(Code.TASK_UNSUPPORTED)
    assert report.codes() == (Code.TASK_UNSUPPORTED.value,)

    # 3) 分类数据集清单 1.0 仍是唯一被加载的数据清单 Schema；草案位于
    #    schemas/detection/，不在 backend 的加载路径上。
    assert DATASET_SCHEMA_NAME == "dataset-manifest.schema.json"
    assert (
        DEFAULT_DATASET_POLICY.dataset_major,
        DEFAULT_DATASET_POLICY.dataset_minor,
    ) == (1, 0)
    assert (REPO_ROOT / "schemas" / DATASET_SCHEMA_NAME).is_file()
    assert DATASET_SCHEMA != REPO_ROOT / "schemas" / DATASET_SCHEMA_NAME
    assert contract_schemas.SCHEMA_DIR == REPO_ROOT / "schemas"
    assert contract_schemas.MANIFEST_SCHEMA == "model-manifest.schema.json"
    assert contract_schemas.ENVELOPE_SCHEMA == "message-envelope.schema.json"

    # 4) 草案文档与目录 README 仍把数据集清单 2.0 标为草案/未激活。
    doc_text = DRAFT_DOC.read_text(encoding="utf-8")
    assert "2.0" in doc_text
    assert "数据集清单" in doc_text

    # 5) 草案文档第 3.3 节与草案 Schema 口径一致：注明以 Schema 为准，字段名同步，
    #    旧候选字段名不再出现；契约状态/其它章节不在本测试范围内。
    section_33 = doc_text.split("### 3.3", 1)[1].split("### 3.4", 1)[0]
    assert "以草案 Schema 为准（未激活）" in section_33
    for phrase in (
        "schema_version",
        "2.0-draft",
        "splits",
        "sha256",
        "width",
        "height",
        "box_count",
        "capture_batch",
    ):
        assert phrase in section_33, f"第 3.3 节必须与草案 Schema 同步字段 {phrase!r}"
    for stale_field in ("annotation_path", "annotation_sha256"):
        assert stale_field not in section_33, (
            f"第 3.3 节不应再使用未纳入 Schema 的旧字段名 {stale_field!r}"
        )

    readme = DETECTION_README.read_text(encoding="utf-8")
    for phrase in (
        "dataset-manifest-2.0-draft.schema.json",
        "单类检测",
        "待决",
        "分类数据集清单",
        "dataset-manifest.schema.json",
        "不属于当前契约",
    ):
        assert phrase in readme, f"README 必须说明 {phrase!r}"
