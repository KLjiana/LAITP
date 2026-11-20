"""模型产物包校验（T02）。

校验顺序：结构 → 版本/任务 → 路径与文件 → 完整性 → 标签 → 张量 → 处理语义
→ 运行时 → 来源与转换。任何阶段失败都返回稳定错误码与定位，不静默跳过；
结构校验失败时不再继续语义检查，避免在不可信数据上推断。

本模块只判定“包是否满足契约”，不执行模型推理；固定样本比对属于后续任务。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from . import integrity, labels as labels_module, paths, schemas, tensors
from .errors import Code, Report, Stage
from .onnx_signature import (
    IntrospectionError,
    ModelSignature,
    TensorIntrospector,
    default_introspector,
)
from .runtime_spec import (
    RuntimeProfile,
    VersionSyntaxError,
    accepts,
    parse_range,
    parse_version,
)

MANIFEST_NAME = "manifest.json"
CLASSIFICATION_TASK = "image_classification"
BOARD_PLATFORMS = ("k230", "k210")


@dataclass(frozen=True)
class ContractPolicy:
    """接收方声明的契约支持范围。

    默认值就是契约 ``1.0`` 的落地范围。超出范围的能力必须显式拒绝，
    不能因为“看起来能跑”而放行。
    """

    contract_major: int = 1
    contract_minor: int = 0
    supported_tasks: tuple[str, ...] = (CLASSIFICATION_TASK,)
    supported_executors: tuple[str, ...] = ("host",)
    supported_color_spaces: tuple[str, ...] = ("RGB", "BGR")
    supported_runtimes: tuple[str, ...] = ("onnxruntime",)
    supported_platforms: tuple[str, ...] = ("windows-x64", "linux-x64")
    supported_capabilities: tuple[str, ...] = ("onnxruntime-cpu",)


DEFAULT_POLICY = ContractPolicy()


def validate_model_package(
    package_dir: str | Path,
    *,
    runtime_profile: RuntimeProfile | None,
    policy: ContractPolicy = DEFAULT_POLICY,
    introspector: TensorIntrospector | None = None,
) -> Report:
    """校验一个模型产物包目录。

    ``runtime_profile`` 是执行加载的当前运行环境；缺失时返回
    ``CONTRACT_RUNTIME_PROFILE_MISSING``，不会假定兼容。
    ``introspector`` 为 ``None`` 时使用真实 ONNX 读取器；依赖缺失会显式失败。
    """
    report = Report()
    root = Path(package_dir)
    if not root.is_dir():
        report.add(
            Code.PACKAGE_NOT_FOUND,
            Stage.ARTIFACTS,
            str(root),
            "产物包目录不存在或不是目录",
        )
        return report

    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        report.add(Code.FILE_MISSING, Stage.PATHS, MANIFEST_NAME, "产物包缺少 manifest.json")
        return report

    data, json_issue = schemas.read_json(
        manifest_path, code=Code.JSON_INVALID, location=MANIFEST_NAME
    )
    if json_issue is not None:
        report.extend([json_issue])
        return report
    if not isinstance(data, dict):
        report.add(Code.SCHEMA_INVALID, Stage.SCHEMA, MANIFEST_NAME, "清单顶层必须是 JSON 对象")
        return report

    structure = schemas.schema_issues(schemas.MANIFEST_SCHEMA, data)
    if structure:
        report.extend(structure)
        return report

    if not _check_versions(report, data["contract_version"], policy):
        return report
    if not _check_task(report, data, policy):
        return report
    _check_executors(report, data, policy)

    files = _check_paths(report, data)
    if files is None:
        return report
    _check_integrity(report, root, data, files)

    _check_labels(report, root, data)
    _check_tensors(report, data, policy, introspector, root)
    _check_preprocessing(report, data)
    _check_postprocessing(report, data)
    _check_runtime(report, data, runtime_profile, policy)
    _check_provenance(report, data)
    _check_conversion(report, data)
    return report


# --------------------------------------------------------------------------- #
# 版本、任务与执行方
# --------------------------------------------------------------------------- #


def _check_versions(report: Report, version_text: str, policy: ContractPolicy) -> bool:
    try:
        major, minor, _ = parse_version(version_text)
    except VersionSyntaxError:
        report.add(
            Code.SCHEMA_INVALID,
            Stage.SCHEMA,
            "contract_version",
            f"契约版本 {version_text!r} 不符合 major.minor 格式",
        )
        return False
    if major != policy.contract_major:
        report.add(
            Code.VERSION_UNSUPPORTED_MAJOR,
            Stage.SCHEMA,
            "contract_version",
            f"契约主版本 {major} 不受支持（当前仅支持 {policy.contract_major}.x）",
        )
        return False
    if minor > policy.contract_minor:
        report.add(
            Code.VERSION_UNSUPPORTED_MINOR,
            Stage.SCHEMA,
            "contract_version",
            f"契约次版本 {version_text} 高于当前支持的 {policy.contract_major}.{policy.contract_minor}",
        )
        return False
    return True


def _check_task(report: Report, data: dict[str, Any], policy: ContractPolicy) -> bool:
    task = data["task"]
    if task not in policy.supported_tasks:
        report.add(
            Code.TASK_UNSUPPORTED,
            Stage.SEMANTICS,
            "task",
            f"任务 {task!r} 尚未由当前校验器支持（支持：{', '.join(policy.supported_tasks)}）",
        )
        return False
    return True


def _check_executors(report: Report, data: dict[str, Any], policy: ContractPolicy) -> None:
    for section in ("preprocessing", "postprocessing"):
        executor = data[section]["executor"]
        if executor not in policy.supported_executors:
            report.add(
                Code.EXECUTOR_UNSUPPORTED,
                Stage.SEMANTICS,
                f"{section}.executor",
                f"执行方 {executor!r} 尚未由当前校验器支持（支持：{', '.join(policy.supported_executors)}）",
            )


# --------------------------------------------------------------------------- #
# 路径与文件
# --------------------------------------------------------------------------- #


def _references(data: dict[str, Any]) -> list[tuple[str, str, str]]:
    """清单中所有载荷文件引用：``(相对路径, 用途, 字段定位)``。"""
    references: list[tuple[str, str, str]] = [
        (data["model"]["path"], "model", "model.path"),
    ]
    for index, rel in enumerate(data["model"]["external_data"]):
        references.append((rel, "external_data", f"model.external_data[{index}]"))
    references.append((data["labels"]["path"], "labels", "labels.path"))
    for index, sample in enumerate(data["validation"]["samples"]):
        references.append((sample["path"], "validation_sample", f"validation.samples[{index}].path"))
        references.append(
            (
                sample["reference_output"],
                "reference_output",
                f"validation.samples[{index}].reference_output",
            )
        )
    thresholds = data["validation"].get("thresholds")
    if thresholds is not None:
        references.append((thresholds["path"], "thresholds", "validation.thresholds.path"))
    conversion = data.get("conversion")
    if conversion is not None:
        calibration = conversion["quantization"].get("calibration_manifest_path")
        if calibration is not None:
            references.append(
                (
                    calibration,
                    "calibration",
                    "conversion.quantization.calibration_manifest_path",
                )
            )
    return references


def _check_paths(report: Report, data: dict[str, Any]) -> dict[str, dict[str, Any]] | None:
    """检查文件路径与引用关系。路径非法或重复时返回 ``None``，停止后续检查。"""
    entries = data["files"]
    by_path: dict[str, dict[str, Any]] = {}
    valid = True

    for index, entry in enumerate(entries):
        rel = entry["path"]
        reason = paths.check_rel_path(rel)
        if reason is not None:
            report.add(Code.PATH_INVALID, Stage.PATHS, f"files[{index}].path", f"{rel!r}：{reason}")
            valid = False
            continue
        if rel == MANIFEST_NAME:
            report.add(
                Code.FILE_MANIFEST_LISTED,
                Stage.PATHS,
                f"files[{index}].path",
                "清单自身不得列入 files，避免循环摘要",
            )
            valid = False
            continue
        if rel in by_path:
            report.add(
                Code.PATH_DUPLICATE,
                Stage.PATHS,
                f"files[{index}].path",
                f"路径 {rel!r} 重复声明",
            )
            valid = False
            continue
        by_path[rel] = entry

    if not valid:
        return None

    referenced: set[str] = set()
    for rel, role, location in _references(data):
        reason = paths.check_rel_path(rel)
        if reason is not None:
            report.add(Code.PATH_INVALID, Stage.PATHS, location, f"{rel!r}：{reason}")
            continue
        referenced.add(rel)
        entry = by_path.get(rel)
        if entry is None:
            report.add(
                Code.PATH_REFERENCE_MISSING,
                Stage.PATHS,
                location,
                f"引用文件 {rel!r} 未在 files 中声明",
            )
        elif entry["role"] != role:
            report.add(
                Code.FILE_ROLE_MISMATCH,
                Stage.PATHS,
                location,
                f"文件 {rel!r} 的用途应为 {role!r}，清单声明为 {entry['role']!r}",
            )

    for index, entry in enumerate(entries):
        rel = entry["path"]
        if rel not in referenced:
            report.add(
                Code.FILE_UNREFERENCED,
                Stage.PATHS,
                f"files[{index}].path",
                f"文件 {rel!r} 未被清单任何字段引用",
            )
    return by_path


def _check_integrity(
    report: Report,
    root: Path,
    data: dict[str, Any],
    files: dict[str, dict[str, Any]],
) -> None:
    for index, entry in enumerate(data["files"]):
        rel = entry["path"]
        if rel not in files:
            continue
        target = paths.resolve_in_package(root, rel)
        if target is None:
            report.add(
                Code.PATH_INVALID,
                Stage.PATHS,
                f"files[{index}].path",
                f"文件 {rel!r} 解析后位于产物包之外（疑似符号链接），拒绝读取",
            )
            continue
        if not target.is_file():
            report.add(
                Code.FILE_MISSING,
                Stage.INTEGRITY,
                f"files[{index}].path",
                f"文件 {rel!r} 不存在",
            )
            continue
        try:
            actual_size = target.stat().st_size
            digest = integrity.sha256_file(target)
        except OSError as error:
            report.add(
                Code.FILE_UNREADABLE,
                Stage.INTEGRITY,
                f"files[{index}].path",
                f"无法读取 {rel!r}：{error.strerror or error}",
            )
            continue
        if "size_bytes" in entry and entry["size_bytes"] != actual_size:
            report.add(
                Code.FILE_SIZE_MISMATCH,
                Stage.INTEGRITY,
                f"files[{index}].size_bytes",
                f"文件 {rel!r} 实际 {actual_size} 字节，与清单声明 {entry['size_bytes']} 不一致",
            )
        if digest != entry["sha256"]:
            report.add(
                Code.FILE_DIGEST_MISMATCH,
                Stage.INTEGRITY,
                f"files[{index}].sha256",
                f"文件 {rel!r} 实际摘要为 {digest}，与清单不一致",
            )


# --------------------------------------------------------------------------- #
# 标签
# --------------------------------------------------------------------------- #


def _check_labels(report: Report, root: Path, data: dict[str, Any]) -> int | None:
    labels_rel = data["labels"]["path"]
    target = paths.resolve_in_package(root, labels_rel)
    if target is None or not target.is_file():
        return None  # 路径与完整性检查已报告

    try:
        loaded = labels_module.load_labels(target)
    except labels_module.LabelsError as error:
        report.add(
            Code.LABELS_INVALID,
            Stage.LABELS,
            "labels.path",
            f"{labels_rel!r}：{error.reason}",
        )
        return None

    duplicate = labels_module.duplicate_index(loaded)
    if duplicate is not None:
        report.add(
            Code.LABELS_DUPLICATE,
            Stage.LABELS,
            "labels.path",
            f"标签 {loaded[duplicate]!r} 重复（下标 {duplicate}），类别 ID 必须唯一",
        )

    declared_count = data["labels"]["count"]
    if len(loaded) != declared_count:
        report.add(
            Code.LABELS_COUNT_MISMATCH,
            Stage.LABELS,
            "labels.count",
            f"清单声明 {declared_count} 个类别，标签文件实际 {len(loaded)} 个",
        )

    class_outputs = [
        output for output in data["outputs"] if output["meaning"] in tensors.CLASS_MEANINGS
    ]
    if not class_outputs:
        report.add(
            Code.POSTPROCESSING_INVALID,
            Stage.SEMANTICS,
            "outputs",
            "分类任务的输出必须声明 class_logits 或 class_probabilities",
        )
        return len(loaded)
    if len(class_outputs) > 1:
        report.add(
            Code.POSTPROCESSING_INVALID,
            Stage.SEMANTICS,
            "outputs",
            "v1.0 校验器仅支持单一分类输出张量",
        )
        return len(loaded)

    dim = tensors.class_dim_of(class_outputs[0])
    if dim is None:
        report.add(
            Code.TENSOR_SHAPE_INVALID,
            Stage.TENSORS,
            "outputs",
            "无法根据 class_axis 定位类别维，检查轴序号是否越界",
        )
        return len(loaded)

    fixed, minimum, maximum = dim
    if fixed is not None:
        if fixed != len(loaded):
            report.add(
                Code.LABELS_CLASS_DIM_MISMATCH,
                Stage.LABELS,
                "outputs",
                f"标签数量 {len(loaded)} 与输出类别维 {fixed} 不一致，标签顺序会整体错位",
            )
    elif minimum is not None and maximum is not None:
        if not minimum <= len(loaded) <= maximum:
            report.add(
                Code.LABELS_CLASS_DIM_MISMATCH,
                Stage.LABELS,
                "outputs",
                f"标签数量 {len(loaded)} 不在输出类别维声明范围 [{minimum}, {maximum}] 内",
            )
    return len(loaded)


# --------------------------------------------------------------------------- #
# 张量
# --------------------------------------------------------------------------- #


def _dim_accepts(dim: int | dict[str, Any], value: int) -> bool:
    fixed, minimum, maximum = tensors.declared_dim(dim)
    if fixed is not None:
        return fixed == value
    if minimum is None or maximum is None:
        return False
    return minimum <= value <= maximum


def _check_tensors(
    report: Report,
    data: dict[str, Any],
    policy: ContractPolicy,
    introspector: TensorIntrospector | None,
    root: Path,
) -> None:
    inputs = data["inputs"]
    if len(inputs) != 1:
        report.add(
            Code.PREPROCESSING_INVALID,
            Stage.SEMANTICS,
            "inputs",
            "v1.0 校验器仅支持单图像输入分类模型",
        )
    for index, spec in enumerate(inputs):
        _check_input_tensor(report, index, spec, policy)
    for index, spec in enumerate(data["outputs"]):
        _check_output_tensor(report, index, spec)
    _check_quantization(report, data)
    _check_signature(report, data, introspector, root)


def _check_input_tensor(
    report: Report,
    index: int,
    spec: dict[str, Any],
    policy: ContractPolicy,
) -> None:
    layout = spec["layout"]
    shape = spec["shape"]
    expected_rank = tensors.layout_rank(layout)
    if len(shape) != expected_rank:
        report.add(
            Code.TENSOR_LAYOUT_INVALID,
            Stage.TENSORS,
            f"inputs[{index}].shape",
            f"布局 {layout} 需要 {expected_rank} 个维度，实际 {len(shape)} 个",
        )
        return

    batch_dim = shape[tensors.dim_index(layout, "N")]
    fixed, minimum, maximum = tensors.declared_dim(batch_dim)
    if fixed is not None and fixed != 1:
        report.add(
            Code.TENSOR_BATCH_INVALID,
            Stage.TENSORS,
            f"inputs[{index}].shape",
            f"批次维必须为 1，实际声明 {fixed}",
        )
    elif fixed is None and not (minimum <= 1 <= maximum):
        report.add(
            Code.TENSOR_BATCH_INVALID,
            Stage.TENSORS,
            f"inputs[{index}].shape",
            f"动态批次维范围 [{minimum}, {maximum}] 必须包含 1",
        )

    color_space = spec["color_space"]
    if color_space not in policy.supported_color_spaces:
        report.add(
            Code.PREPROCESSING_INVALID,
            Stage.SEMANTICS,
            f"inputs[{index}].color_space",
            f"颜色空间 {color_space!r} 尚未由当前校验器支持（支持：{', '.join(policy.supported_color_spaces)}）",
        )
        return

    expected_channels = 3
    channel_dim = shape[tensors.dim_index(layout, "C")]
    fixed, minimum, maximum = tensors.declared_dim(channel_dim)
    if fixed is not None and fixed != expected_channels:
        report.add(
            Code.TENSOR_CHANNEL_INVALID,
            Stage.TENSORS,
            f"inputs[{index}].shape",
            f"{color_space} 输入需要 {expected_channels} 个通道，实际声明 {fixed}",
        )
    elif fixed is None and not (minimum <= expected_channels <= maximum):
        report.add(
            Code.TENSOR_CHANNEL_INVALID,
            Stage.TENSORS,
            f"inputs[{index}].shape",
            f"动态通道维范围 [{minimum}, {maximum}] 必须包含 {expected_channels}",
        )


def _check_output_tensor(report: Report, index: int, spec: dict[str, Any]) -> None:
    meaning = spec["meaning"]
    if meaning not in tensors.CLASS_MEANINGS:
        report.add(
            Code.POSTPROCESSING_INVALID,
            Stage.SEMANTICS,
            f"outputs[{index}].meaning",
            f"分类任务的输出语义 {meaning!r} 尚未由当前校验器支持",
        )
        return
    if spec["dtype"] not in ("float32", "float16"):
        report.add(
            Code.TENSOR_DTYPE_INVALID,
            Stage.TENSORS,
            f"outputs[{index}].dtype",
            f"分类输出必须是浮点点数（float32/float16），实际 {spec['dtype']!r}",
        )
    rank = len(spec["shape"])
    resolved = tensors.normalize_axis(int(spec["class_axis"]), rank)
    if resolved is None:
        report.add(
            Code.TENSOR_SHAPE_INVALID,
            Stage.TENSORS,
            f"outputs[{index}].class_axis",
            f"类别轴 {spec['class_axis']} 超出输出秩 {rank} 的范围",
        )


def _check_quantization(report: Report, data: dict[str, Any]) -> None:
    for section in ("inputs", "outputs"):
        for index, spec in enumerate(data[section]):
            quantized = spec["dtype"] in tensors.QUANTIZED_DTYPES
            meta = spec.get("quantization")
            location = f"{section}[{index}]"
            if quantized and meta is None:
                report.add(
                    Code.TENSOR_QUANTIZATION_INVALID,
                    Stage.TENSORS,
                    location,
                    f"{spec['dtype']} 张量必须声明 scale、zero_point 及量化方案",
                )
            if meta is not None and not quantized:
                report.add(
                    Code.TENSOR_QUANTIZATION_INVALID,
                    Stage.TENSORS,
                    f"{location}.quantization",
                    f"非量化张量（{spec['dtype']}）不应声明量化参数",
                )
            if meta is None:
                continue
            if meta["scheme"] == "per_channel" and "axis" not in meta:
                report.add(
                    Code.TENSOR_QUANTIZATION_INVALID,
                    Stage.TENSORS,
                    f"{location}.quantization.axis",
                    "逐通道量化必须声明量化轴",
                )
            if spec["dtype"] == "int8" and not -128 <= meta["zero_point"] <= 127:
                report.add(
                    Code.TENSOR_QUANTIZATION_INVALID,
                    Stage.TENSORS,
                    f"{location}.quantization.zero_point",
                    f"int8 的 zero_point 必须在 [-128, 127]，实际 {meta['zero_point']}",
                )
            if spec["dtype"] == "uint8" and not 0 <= meta["zero_point"] <= 255:
                report.add(
                    Code.TENSOR_QUANTIZATION_INVALID,
                    Stage.TENSORS,
                    f"{location}.quantization.zero_point",
                    f"uint8 的 zero_point 必须在 [0, 255]，实际 {meta['zero_point']}",
                )


def _shape_mismatch(declared: list[Any], actual: tuple[int | None, ...]) -> str | None:
    if len(declared) != len(actual):
        return f"维度数不一致：清单 {len(declared)}，模型 {len(actual)}"
    for index, (dim, actual_dim) in enumerate(zip(declared, actual)):
        fixed, minimum, maximum = tensors.declared_dim(dim)
        if fixed is not None:
            if actual_dim is None:
                return f"第 {index} 维：模型为动态维度，清单声明固定 {fixed}"
            if actual_dim != fixed:
                return f"第 {index} 维：清单声明 {fixed}，模型实际 {actual_dim}"
        else:
            if actual_dim is not None and not (minimum <= actual_dim <= maximum):
                return (
                    f"第 {index} 维：模型实际 {actual_dim} 不在声明范围 "
                    f"[{minimum}, {maximum}] 内"
                )
    return None


def _compare_tensors(
    report: Report,
    section: str,
    declared: list[dict[str, Any]],
    actual: tuple[tensors.TensorSignature, ...],
) -> None:
    if len(declared) != len(actual):
        report.add(
            Code.TENSOR_SIGNATURE_MISMATCH,
            Stage.ARTIFACTS,
            section,
            f"清单声明 {len(declared)} 个张量，模型实际 {len(actual)} 个",
        )
        return

    by_name = {item.name: item for item in actual}
    match_by_name = len(by_name) == len(actual) and all(
        spec["name"] in by_name for spec in declared
    )
    for index, spec in enumerate(declared):
        counterpart = by_name[spec["name"]] if match_by_name else actual[index]
        location = f"{section}[{index}]"
        if counterpart.name != spec["name"]:
            report.add(
                Code.TENSOR_SIGNATURE_MISMATCH,
                Stage.ARTIFACTS,
                f"{location}.name",
                f"清单声明张量名 {spec['name']!r}，模型实际 {counterpart.name!r}",
            )
        if counterpart.dtype != spec["dtype"]:
            report.add(
                Code.TENSOR_SIGNATURE_MISMATCH,
                Stage.ARTIFACTS,
                f"{location}.dtype",
                f"清单声明 {spec['dtype']!r}，模型实际 {counterpart.dtype!r}",
            )
        reason = _shape_mismatch(spec["shape"], counterpart.shape)
        if reason is not None:
            report.add(
                Code.TENSOR_SIGNATURE_MISMATCH,
                Stage.ARTIFACTS,
                f"{location}.shape",
                reason,
            )


def _check_signature(
    report: Report,
    data: dict[str, Any],
    introspector: TensorIntrospector | None,
    root: Path,
) -> None:
    model_rel = data["model"]["path"]
    target = paths.resolve_in_package(root, model_rel)
    if target is None or not target.is_file():
        return  # 路径与完整性检查已报告

    reader = introspector if introspector is not None else default_introspector()
    if reader is None:
        report.add(
            Code.TENSOR_INSPECTION_UNAVAILABLE,
            Stage.ARTIFACTS,
            "model.path",
            "当前环境无法读取模型真实张量（未安装 onnx）；不能跳过张量校验",
        )
        return

    try:
        signature: ModelSignature = reader.inspect(target)
    except IntrospectionError as error:
        report.add(
            Code.TENSOR_INSPECTION_UNAVAILABLE,
            Stage.ARTIFACTS,
            "model.path",
            f"{reader.name} 无法读取模型签名：{error.reason}",
        )
        return

    _compare_tensors(report, "inputs", data["inputs"], signature.inputs)
    _compare_tensors(report, "outputs", data["outputs"], signature.outputs)

    declared_opset = data["model"]["opset"]
    if signature.opset is None:
        report.add(
            Code.MODEL_OPSET_MISMATCH,
            Stage.ARTIFACTS,
            "model.opset",
            "模型文件未声明 opset，无法确认导出兼容性",
        )
    elif signature.opset != declared_opset:
        report.add(
            Code.MODEL_OPSET_MISMATCH,
            Stage.ARTIFACTS,
            "model.opset",
            f"清单声明 opset {declared_opset}，模型实际 {signature.opset}",
        )


# --------------------------------------------------------------------------- #
# 处理语义
# --------------------------------------------------------------------------- #


def _check_preprocessing(report: Report, data: dict[str, Any]) -> None:
    preprocessing = data["preprocessing"]
    pixel_range = preprocessing["source_pixel_range"]
    if pixel_range[0] >= pixel_range[1]:
        report.add(
            Code.PREPROCESSING_INVALID,
            Stage.SEMANTICS,
            "preprocessing.source_pixel_range",
            f"像素取值范围必须递增，实际 {pixel_range}",
        )

    inputs = data["inputs"]
    if len(inputs) != 1:
        return
    spec = inputs[0]
    layout = spec["layout"]
    shape = spec["shape"]
    if len(shape) != tensors.layout_rank(layout):
        return

    steps = preprocessing["steps"]
    resize_indexes = [index for index, step in enumerate(steps) if step["op"] == "resize"]
    if len(resize_indexes) != 1:
        report.add(
            Code.PREPROCESSING_INVALID,
            Stage.SEMANTICS,
            "preprocessing.steps",
            f"必须且只能声明一次 resize，实际 {len(resize_indexes)} 次",
        )

    current = ["H", "W", "C"]
    for index, step in enumerate(steps):
        op = step["op"]
        if op == "normalize":
            if step["channel_order"] != spec["color_space"]:
                report.add(
                    Code.PREPROCESSING_INVALID,
                    Stage.SEMANTICS,
                    f"preprocessing.steps[{index}].channel_order",
                    f"归一化通道顺序 {step['channel_order']} 与输入颜色空间 {spec['color_space']} 不一致",
                )
        elif op == "transpose":
            if current != ["H", "W", "C"]:
                report.add(
                    Code.PREPROCESSING_INVALID,
                    Stage.SEMANTICS,
                    f"preprocessing.steps[{index}]",
                    f"仅支持从 HWC 转换到 CHW，当前布局为 {''.join(current)}",
                )
            current = ["C", "H", "W"]
        elif op == "add_batch_dimension":
            if step["axis"] != 0:
                report.add(
                    Code.PREPROCESSING_INVALID,
                    Stage.SEMANTICS,
                    f"preprocessing.steps[{index}].axis",
                    f"批次维只能添加在轴 0，实际 {step['axis']}",
                )
            if "N" in current:
                report.add(
                    Code.PREPROCESSING_INVALID,
                    Stage.SEMANTICS,
                    f"preprocessing.steps[{index}]",
                    "重复添加批次维",
                )
            current = ["N", *current]

    if "".join(current) != layout:
        report.add(
            Code.PREPROCESSING_INVALID,
            Stage.SEMANTICS,
            "preprocessing.steps",
            f"按顺序执行后布局为 {''.join(current)}，与输入布局 {layout} 不一致",
        )

    if len(resize_indexes) == 1:
        step = steps[resize_indexes[0]]
        height_dim = shape[tensors.dim_index(layout, "H")]
        width_dim = shape[tensors.dim_index(layout, "W")]
        if not _dim_accepts(height_dim, step["height"]):
            report.add(
                Code.PREPROCESSING_INVALID,
                Stage.SEMANTICS,
                f"preprocessing.steps[{resize_indexes[0]}].height",
                f"缩放高度 {step['height']} 与输入 H 维声明不一致",
            )
        if not _dim_accepts(width_dim, step["width"]):
            report.add(
                Code.PREPROCESSING_INVALID,
                Stage.SEMANTICS,
                f"preprocessing.steps[{resize_indexes[0]}].width",
                f"缩放宽度 {step['width']} 与输入 W 维声明不一致",
            )


def _check_postprocessing(report: Report, data: dict[str, Any]) -> None:
    outputs = [
        output for output in data["outputs"] if output["meaning"] in tensors.CLASS_MEANINGS
    ]
    if len(outputs) != 1:
        return
    output = outputs[0]
    steps = data["postprocessing"]["steps"]
    softmax_steps = [(index, step) for index, step in enumerate(steps) if step["op"] == "softmax"]
    meaning = output["meaning"]

    if meaning == "class_logits":
        if not softmax_steps:
            report.add(
                Code.POSTPROCESSING_INVALID,
                Stage.SEMANTICS,
                "postprocessing.steps",
                "输出为 logits，必须在 postprocessing 中声明 softmax，否则概率无意义",
            )
    elif softmax_steps:
        report.add(
            Code.POSTPROCESSING_INVALID,
            Stage.SEMANTICS,
            f"postprocessing.steps[{softmax_steps[0][0]}]",
            "输出已声明为 class_probabilities，不得再次执行 softmax",
        )

    if len(softmax_steps) > 1:
        report.add(
            Code.POSTPROCESSING_INVALID,
            Stage.SEMANTICS,
            "postprocessing.steps",
            f"softmax 只能声明一次，实际 {len(softmax_steps)} 次",
        )

    rank = len(output["shape"])
    class_axis = tensors.normalize_axis(int(output["class_axis"]), rank)
    for index, step in softmax_steps:
        resolved = tensors.normalize_axis(int(step["axis"]), rank)
        if resolved is None:
            report.add(
                Code.POSTPROCESSING_INVALID,
                Stage.SEMANTICS,
                f"postprocessing.steps[{index}].axis",
                f"softmax 轴 {step['axis']} 超出输出秩 {rank} 的范围",
            )
        elif class_axis is not None and resolved != class_axis:
            report.add(
                Code.POSTPROCESSING_INVALID,
                Stage.SEMANTICS,
                f"postprocessing.steps[{index}].axis",
                f"softmax 轴 {step['axis']} 与类别轴 {output['class_axis']} 不一致",
            )


# --------------------------------------------------------------------------- #
# 运行时、来源与转换
# --------------------------------------------------------------------------- #


def _check_runtime(
    report: Report,
    data: dict[str, Any],
    profile: RuntimeProfile | None,
    policy: ContractPolicy,
) -> None:
    runtime = data["runtime"]
    platform = runtime["platform"]
    if platform in BOARD_PLATFORMS:
        report.add(
            Code.BOARD_UNSUPPORTED,
            Stage.RUNTIME,
            "runtime.platform",
            f"板端平台 {platform!r} 需要实物、固件和板端运行时验证，v1.0 校验器不支持",
        )
        return

    if runtime["runtime"] not in policy.supported_runtimes:
        report.add(
            Code.RUNTIME_UNSUPPORTED,
            Stage.RUNTIME,
            "runtime.runtime",
            f"运行时 {runtime['runtime']!r} 尚未由当前校验器支持（支持：{', '.join(policy.supported_runtimes)}）",
        )
    if platform not in policy.supported_platforms:
        report.add(
            Code.RUNTIME_UNSUPPORTED,
            Stage.RUNTIME,
            "runtime.platform",
            f"目标平台 {platform!r} 尚未由当前校验器支持（支持：{', '.join(policy.supported_platforms)}）",
        )

    if profile is None:
        report.add(
            Code.RUNTIME_PROFILE_MISSING,
            Stage.RUNTIME,
            "runtime",
            "未提供目标运行环境，无法确认运行时兼容性",
        )
        return

    if profile.runtime != runtime["runtime"]:
        report.add(
            Code.RUNTIME_UNSUPPORTED,
            Stage.RUNTIME,
            "runtime.runtime",
            f"产物要求运行时 {runtime['runtime']!r}，当前环境为 {profile.runtime!r}",
        )
    if profile.platform != platform:
        report.add(
            Code.RUNTIME_UNSUPPORTED,
            Stage.RUNTIME,
            "runtime.platform",
            f"产物目标平台 {platform!r} 与当前运行环境 {profile.platform!r} 不一致",
        )

    try:
        comparators = parse_range(runtime["version_range"])
    except VersionSyntaxError as error:
        report.add(
            Code.SCHEMA_INVALID,
            Stage.RUNTIME,
            "runtime.version_range",
            f"版本范围无法解析：{error}",
        )
        return
    try:
        version = parse_version(profile.version)
    except VersionSyntaxError as error:
        report.add(
            Code.RUNTIME_PROFILE_INVALID,
            Stage.RUNTIME,
            "runtime_profile.version",
            f"当前运行时版本无法解析：{error}",
        )
        return
    if not accepts(comparators, version):
        report.add(
            Code.RUNTIME_VERSION_INCOMPATIBLE,
            Stage.RUNTIME,
            "runtime.version_range",
            f"当前运行时版本 {profile.version} 不满足产物要求 {runtime['version_range']}",
        )

    required = set(runtime["required_capabilities"])
    unknown = required - set(policy.supported_capabilities)
    if unknown:
        report.add(
            Code.RUNTIME_CAPABILITY_MISSING,
            Stage.RUNTIME,
            "runtime.required_capabilities",
            f"校验器不支持能力 {', '.join(sorted(unknown))}",
        )
    missing = required - set(profile.capabilities)
    if missing:
        report.add(
            Code.RUNTIME_CAPABILITY_MISSING,
            Stage.RUNTIME,
            "runtime.required_capabilities",
            f"当前运行环境缺少能力 {', '.join(sorted(missing))}",
        )


def _parse_timestamp(text: str) -> datetime:
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("时间戳缺少时区")
    return parsed


def _check_provenance(report: Report, data: dict[str, Any]) -> None:
    provenance = data["provenance"]
    try:
        _parse_timestamp(provenance["created_at"])
    except ValueError:
        report.add(
            Code.PROVENANCE_INVALID,
            Stage.SEMANTICS,
            "provenance.created_at",
            f"生成时间 {provenance['created_at']!r} 不是带时区的 RFC 3339 时间",
        )
    source = provenance.get("source")
    if source is not None and source["artifact_id"] == data["artifact_id"]:
        report.add(
            Code.PROVENANCE_INVALID,
            Stage.SEMANTICS,
            "provenance.source.artifact_id",
            "来源产物 ID 不能与当前产物 ID 相同，转换必须产生新产物",
        )


def _check_conversion(report: Report, data: dict[str, Any]) -> None:
    conversion = data.get("conversion")
    if conversion is None:
        return
    mode = conversion["quantization"]["mode"]
    quantized = [
        f"{section}[{index}]"
        for section in ("inputs", "outputs")
        for index, spec in enumerate(data[section])
        if spec["dtype"] in tensors.QUANTIZED_DTYPES
    ]
    if mode == "none" and quantized:
        report.add(
            Code.CONVERSION_INVALID,
            Stage.SEMANTICS,
            "conversion.quantization.mode",
            f"声明未量化，但存在 int8/uint8 张量：{', '.join(quantized)}",
        )
