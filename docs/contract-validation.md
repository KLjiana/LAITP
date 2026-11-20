# 契约校验说明（T01 / T02）

编制日期：2026-11-17

状态：T01（Schema 与样例）和 T02（产物包校验器）已实现并通过本地测试；T03～T05 见[数据与运行基线](data-and-runtime-baseline.md)，T06 见[独立推理说明](runtime-inference.md)，T07 见[任务协议与父进程](task-protocol.md)，T08 本机部分见[性能记录](performance-m0.md)（目标机待执行）。
本文只描述契约校验能力，不表示训练、导出、推理或板端验证已经可用。

所属计划：[M0-01 分类最小闭环](m0-01-classification-plan.md)。强制约束见[模型接口与产物契约](model-contract.md)。

## 1. 已实现范围

| 内容 | 位置 | 说明 |
| --- | --- | --- |
| 分类模型清单 Schema | `schemas/model-manifest.schema.json` | JSON Schema 2020-12，契约 `1.0` |
| 消息信封 Schema | `schemas/message-envelope.schema.json` | 协议 `1.0`，每行一条 JSON 消息 |
| 产物包校验器 | `backend/contracts/` | 路径、摘要、标签、真实张量、运行时、处理语义 |
| 消息信封校验器 | `backend/contracts/envelope.py` | 单条消息的结构、版本与自洽性 |
| 有效/无效样例 | `tests/fixtures/` | 静态样例与生成式完整产物包 |
| 测试 | `tests/` | 见第 7 节实际执行结果 |
| 开发命令 | `python -m backend.contracts` | 只做校验，不是训练/预测 CLI |

结构约束只在 Schema 中定义。Schema 无法表达的文件、标签、张量、运行时和语义规则由校验器补充；两者都不通过时产物不可用。

## 2. 产物包与检查顺序

```text
model-package/
  manifest.json
  model.onnx
  labels.json
  validation/
    sample.png
    expected.json
```

校验顺序固定为：结构 → 版本/任务 → 路径与文件引用 → 完整性 → 标签 → 张量 → 处理语义 → 运行时 → 来源与转换。
结构校验失败时立即返回，不在不可信数据上继续推断语义。

| 阶段（`stage`） | 检查内容 |
| --- | --- |
| `schema` | JSON 可解析、符合 Schema、契约版本与格式 |
| `paths` | 相对路径规范化、重复、用途、引用完整性、Windows 保留名、末尾空格或点 |
| `integrity` | 文件存在、可读取、大小与 SHA-256 和清单一致、符号链接不越出包外 |
| `labels` | UTF-8 有序字符串数组、无重复、数量与清单及输出类别维一致 |
| `tensors` | 布局与秩、批次维为 1、通道数、类别轴、量化元数据 |
| `artifacts` | 模型实际输入输出名称/形状/类型、opset 与清单一致 |
| `semantics` | 执行方、预处理顺序与布局、softmax 规则、时间戳、来源与转换自洽 |
| `runtime` | 运行时、版本范围、目标平台、所需能力 |

## 3. 稳定错误码

一次校验可以返回多条问题。`location` 使用 `files[2].sha256`、`preprocessing.steps[0]` 形式定位字段或文件；`$` 表示整份文档。
错误码值是稳定契约，界面和日志应据此判断，不要解析 `message` 文本。

### 3.1 产物包

| 错误码 | 阶段 | 含义 |
| --- | --- | --- |
| `CONTRACT_JSON_INVALID` | schema | `manifest.json` 不是有效 UTF-8 JSON |
| `CONTRACT_SCHEMA_INVALID` | schema | 不符合 Schema（缺少必填字段、未知字段、未知步骤操作、路径格式非法等） |
| `CONTRACT_SCHEMA_RESOURCE_MISSING` | schema | 仓库缺少 Schema 文件，无法执行校验 |
| `CONTRACT_PACKAGE_NOT_FOUND` | artifacts | 产物包目录不存在或不是目录 |
| `CONTRACT_VERSION_UNSUPPORTED_MAJOR` | schema | 契约主版本不受支持 |
| `CONTRACT_VERSION_UNSUPPORTED_MINOR` | schema | 契约次版本高于接收方支持范围 |
| `CONTRACT_TASK_UNSUPPORTED` | semantics | 任务类型未实现（当前仅图像分类） |
| `CONTRACT_EXECUTOR_UNSUPPORTED` | semantics | 处理执行方不是 `host`（当前未验证图内或板端执行） |
| `CONTRACT_PATH_INVALID` | paths | 路径不合法：目录穿越、Windows 保留名、末尾空格或点、超长路径段、符号链接越界 |
| `CONTRACT_PATH_DUPLICATE` | paths | `files` 中重复声明同一路径 |
| `CONTRACT_PATH_REFERENCE_MISSING` | paths | 清单引用的文件未在 `files` 中声明 |
| `CONTRACT_FILE_UNREFERENCED` | paths | `files` 中的文件未被任何字段引用 |
| `CONTRACT_FILE_MANIFEST_LISTED` | paths | 把 `manifest.json` 自身列入 `files` |
| `CONTRACT_FILE_ROLE_MISMATCH` | paths | 文件用途与引用位置不符（例如 `model.path` 指向非 `model` 用途文件） |
| `CONTRACT_FILE_MISSING` | integrity | 声明或引用的文件不存在 |
| `CONTRACT_FILE_UNREADABLE` | integrity | 文件存在但无法读取 |
| `CONTRACT_FILE_SIZE_MISMATCH` | integrity | `size_bytes` 与实际大小不一致 |
| `CONTRACT_FILE_DIGEST_MISMATCH` | integrity | SHA-256 与清单不一致（标签被改、权重被改或文件错误） |
| `CONTRACT_LABELS_INVALID` | labels | 标签文件不是 UTF-8 有序字符串数组，或存在空标签、首尾空白、控制字符 |
| `CONTRACT_LABELS_DUPLICATE` | labels | 标签重复，类别 ID 不唯一 |
| `CONTRACT_LABELS_COUNT_MISMATCH` | labels | 清单声明的类别数与标签文件实际数量不一致 |
| `CONTRACT_LABELS_CLASS_DIM_MISMATCH` | labels | 标签数量与输出类别维不一致，标签顺序会整体错位 |
| `CONTRACT_TENSOR_SHAPE_INVALID` | tensors | 形状维度非法，或 `class_axis` 越界导致类别维无法定位 |
| `CONTRACT_TENSOR_LAYOUT_INVALID` | tensors | 布局与形状维数不匹配 |
| `CONTRACT_TENSOR_BATCH_INVALID` | tensors | 批次维不是 1，或动态批次范围不包含 1 |
| `CONTRACT_TENSOR_CHANNEL_INVALID` | tensors | 通道数与颜色空间不符 |
| `CONTRACT_TENSOR_DTYPE_INVALID` | tensors | 分类输出不是浮点类型 |
| `CONTRACT_TENSOR_QUANTIZATION_INVALID` | tensors | 量化张量缺少 scale/zero_point/轴，或非量化张量声明了量化参数 |
| `CONTRACT_TENSOR_SIGNATURE_MISMATCH` | artifacts | 清单声明的名称、形状或类型与模型实际张量不一致 |
| `CONTRACT_TENSOR_INSPECTION_UNAVAILABLE` | artifacts | 无法读取模型真实张量（缺少依赖或模型损坏），不能跳过校验 |
| `CONTRACT_MODEL_OPSET_MISMATCH` | artifacts | 清单声明的 opset 与模型实际 opset 不一致或模型未声明 |
| `CONTRACT_PREPROCESSING_INVALID` | semantics | 像素范围、颜色空间、`resize` 次数与尺寸、归一化通道顺序、最终布局不一致 |
| `CONTRACT_POSTPROCESSING_INVALID` | semantics | logits 缺少 softmax、概率输出重复 softmax、softmax 轴与类别轴不一致、分类输出缺失 |
| `CONTRACT_RUNTIME_PROFILE_MISSING` | runtime | 未提供当前运行环境，无法确认兼容性 |
| `CONTRACT_RUNTIME_PROFILE_INVALID` | runtime | 当前运行环境版本无法解析 |
| `CONTRACT_RUNTIME_UNSUPPORTED` | runtime | 运行时或目标平台与当前环境不一致或不受支持 |
| `CONTRACT_RUNTIME_VERSION_INCOMPATIBLE` | runtime | 当前运行时版本不满足清单声明的版本范围 |
| `CONTRACT_RUNTIME_CAPABILITY_MISSING` | runtime | 缺少清单要求的能力，或校验器不支持该能力 |
| `CONTRACT_BOARD_UNSUPPORTED` | runtime | 板端平台产物需要实物与固件验证，当前不支持加载 |
| `CONTRACT_PROVENANCE_INVALID` | semantics | 生成时间不是带时区的有效时间，或转换产物沿用来源产物 ID |
| `CONTRACT_CONVERSION_INVALID` | semantics | 量化声明与张量类型矛盾（例如声明未量化但存在 int8/uint8 张量） |

### 3.2 消息信封

| 错误码 | 阶段 | 含义 |
| --- | --- | --- |
| `ENVELOPE_JSON_INVALID` | schema | 消息行不是有效 JSON |
| `ENVELOPE_SCHEMA_INVALID` | schema | 缺少必填字段、未知字段、未知消息类型、载荷结构与消息类型不匹配 |
| `ENVELOPE_VERSION_UNSUPPORTED_MAJOR` | schema | 协议主版本不支持 |
| `ENVELOPE_VERSION_UNSUPPORTED_MINOR` | schema | 协议次版本高于接收方支持范围 |
| `ENVELOPE_MESSAGE_TYPE_UNSUPPORTED` | schema | 接收方策略不支持该消息类型 |
| `ENVELOPE_ARTIFACT_MISMATCH` | semantics | 成功结果未携带产物 ID，或信封与结果引用的产物 ID 不一致 |
| `ENVELOPE_PROGRESS_INVALID` | semantics | 已完成数超过总数 |
| `ENVELOPE_PREDICTION_INVALID` | semantics | 预测结果的类别 ID 重复 |

## 4. 已实现的支持范围

| 项目 | 支持范围 | 超出范围时 |
| --- | --- | --- |
| 契约版本 | `1.0`（次版本 `0`） | 主/次版本不支持错误 |
| 协议版本 | `1.0` | 主/次版本不支持错误 |
| 任务 | `image_classification` | `CONTRACT_TASK_UNSUPPORTED` |
| 模型格式 | ONNX，opset 7～21 | Schema 拒绝 |
| 运行时 | `onnxruntime`，平台 `windows-x64` / `linux-x64`，能力 `onnxruntime-cpu` | 运行时或能力错误 |
| 处理执行方 | `host` | `CONTRACT_EXECUTOR_UNSUPPORTED` |
| 颜色空间 | `RGB`、`BGR` | `CONTRACT_PREPROCESSING_INVALID` |
| 输入/输出数量 | 单输入、单分类输出 | `CONTRACT_PREPROCESSING_INVALID` / `CONTRACT_POSTPROCESSING_INVALID` |
| 预处理步骤 | `resize`、`normalize`、`transpose`、`add_batch_dimension` | Schema 拒绝 |
| 后处理步骤 | `softmax` | Schema 拒绝 |
| 板端平台 | 不校验、不加载 | `CONTRACT_BOARD_UNSUPPORTED` |
| 消息类型 | `progress`、`result`、`error`、`cancelled` | Schema 拒绝 |

## 5. 已知限制（未实现，不能视为通过）

- 不执行模型推理，也不比较固定样本输入张量、原始输出或预测结果；这些属于 T05/T06。
- 不验证转换产物的来源包内容，只检查 `provenance.source` 的字段与自洽性；来源清单摘要需要在转换流程中对照源包核对。
- 不读取校准清单内容，只检查其路径已在 `files` 中声明且摘要一致。
- SHA-256 只能证明文件与清单一致，不能证明标签语义正确或来源可信；标签顺序仍需由固定样本和训练记录共同确认。
- 不检查任务归属、序号递增、重复与迟到消息；这些由 T07 的任务状态机负责。
- 未验证 ONNX Runtime 实际加载、CPU 推理性能、Windows 目标机离线链路和板端部署。
- 未实现训练、导出、评估、取消和进度上报。

## 6. 使用方法

`validate_model_package` 是库入口，`python -m backend.contracts` 是开发与验收用的命令行入口。

```powershell
# 产物包校验（必须提供目标运行环境）
python -m backend.contracts package .\runs\<run-id>\model-package `
  --runtime onnxruntime --runtime-version 1.19.2 --platform windows-x64 `
  --capability onnxruntime-cpu

# 单条消息校验
python -m backend.contracts envelope .\message.json
```

标准输出为 JSON：`{"target": ..., "ok": true|false, "issues": [...]}`；退出码 `0` 表示通过，`1` 表示存在问题。
未提供 `--runtime` 等目标环境参数时返回 `CONTRACT_RUNTIME_PROFILE_MISSING`，不会假定兼容。

```python
from pathlib import Path

from backend.contracts import RuntimeProfile, validate_model_package

report = validate_model_package(
    Path("model-package"),
    runtime_profile=RuntimeProfile(
        runtime="onnxruntime",
        version="1.19.2",
        platform="windows-x64",
        capabilities=frozenset({"onnxruntime-cpu"}),
    ),
)
if not report.ok:
    for issue in report.issues:
        print(issue.code.value, issue.location, issue.message)
```

## 7. 复现与环境

已执行环境：Windows 11（10.0.26200）、Python 3.12.1 x64、jsonschema 4.25.1、onnx 1.19.1、pytest 8.4.2。

```powershell
# 在仓库根目录创建隔离环境
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
```

测试覆盖：Schema 有效/无效样例、目录穿越与保留名、文件摘要、标签顺序与数量、真实 ONNX 张量比对、opset、预处理与 softmax 语义、运行时版本与能力、转换来源、消息信封归属与版本。

离线准备（正式断网验收前执行，记录下载摘要）：

```powershell
.\.venv\Scripts\python.exe -m pip download -r requirements-dev.txt -d vendor\wheels
.\.venv\Scripts\python.exe -m pip install --no-index --find-links vendor\wheels -r requirements-dev.txt
```

ONNX 与 jsonschema 的部分依赖为平台相关二进制包，需要按目标 Windows x64 与 Python 版本分别准备；当前仅验证过本机 Windows x64，Linux 与干净机器未验证。
