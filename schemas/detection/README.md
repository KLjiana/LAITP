# 检测标注、结果与数据集清单 Schema（草案，未激活）

编制日期：2026-11-19

> **状态：草案、未激活。** 本目录中的 JSON Schema 与样例**不属于当前契约 `1.0`**，也没有被 `backend/` 的任何生产代码加载或引用。当前校验器仍按不支持拒绝检测任务：`task` 为 `object_detection` 的清单返回 `CONTRACT_TASK_UNSUPPORTED`。检测训练、导出、电脑推理、转换和板端能力均**未实现、未验证**；不得把本目录或本目录的测试通过当作能力可用。

本目录是 [检测契约扩展与标注/结果格式草案](../../docs/detection-contract-draft.md) 第 3、4 节的机器可读候选，对应 [检测课可行性规划](../../docs/detection-feasibility.md) P2“标注 JSON Schema 草案、有效/无效样例、坐标规则”，并补充数据清单 `2.0` 的结构草案 `dataset-manifest-2.0-draft.schema.json`（对应草案文档第 3.3 节，仍为草案、未激活）。格式与字段尚未评审冻结；正式引入必须按 [模型接口与产物契约](../../docs/model-contract.md) 第 7 节升版，并按第 9 节同步文档、JSON Schema、生产方、消费方和测试。检测的数据集清单 `2.0`、项目格式和消息协议需要各自独立升版，见草案文档第 2.1、5 节。

## 1. 与当前契约的隔离

- 当前活跃契约为分类 `1.0`：`schemas/model-manifest.schema.json`、`schemas/message-envelope.schema.json`、`schemas/dataset-manifest.schema.json`、`schemas/project.schema.json`，校验入口在 `backend/contracts/`。本目录**不在**这些 Schema 的加载路径上；本目录的 Schema、样例和测试没有修改现有契约文件、校验器、默认策略、后端或文档。
- 分类数据集清单 `1.0` 仍是唯一被加载的数据清单 Schema：`backend/classification/dataset.py` 只读取 `schemas/dataset-manifest.schema.json`（`dataset_version` 1.x、`task: image_classification`）。本目录的 `dataset-manifest-2.0-draft.schema.json` 位于 `schemas/detection/` 子目录，不在该加载路径上，其 `schema_version: "2.0-draft"` 与 `splits` 结构不会被现有数据集校验器读取或接受。不得把检测清单改义塞进分类 `1.0`，也不得把分类项目自动“升级”为检测项目。
- 本目录 Schema 的 `$id` 只用于标识草案文件，不表示已发布契约。
- `model-manifest.schema.json` 中预留的 `object_detection` 任务枚举、`raw_detections`/`detections` 输出语义等只是**结构占位**，不表示受支持；任务检查仍会拒绝（见草案文档第 1.2 节）。
- 引入检测前置条件（草案，未完成）：新契约版本、任务专属必填语义、后处理步骤定义、数据集清单版本、项目格式版本和消息协议版本。任何一项缺失时，检测相关格式只能作为草案材料存在。
- 待决问题仍未决定，见草案文档第 5 节：空标注（Q6）、每图版本字段（Q7）、单类检测（Q2）、坐标是否归一化（Q5）、契约用次版本还是主版本（Q1）等。本目录不替这些决策下结论。

## 2. 文件

| 文件 | 内容 |
| --- | --- |
| `annotation.schema.json` | 单图标注文件草案（每图一个 JSON）。 |
| `detection-result.schema.json` | 单图检测结果草案。 |
| `dataset-manifest-2.0-draft.schema.json` | 检测数据集清单 `2.0` 结构草案（按 train/val/test 划分组织样本，样本引用图片与每图标注并记录 `sha256`/尺寸/框数等追溯字段）。 |
| `../../tests/fixtures/detection/annotation-valid.json` | 有效标注样例，2 个框。 |
| `../../tests/fixtures/detection/annotation-invalid-absolute-path.json` | `image` 为绝对路径，Schema 拒绝。 |
| `../../tests/fixtures/detection/annotation-invalid-negative-box.json` | `w` 为负，Schema 拒绝。 |
| `../../tests/fixtures/detection/result-valid.json` | 有效检测结果样例。 |
| `../../tests/fixtures/detection/result-invalid-confidence.json` | `confidence` 大于 1，Schema 拒绝。 |
| `../../tests/fixtures/detection/dataset-manifest-valid.json` | 有效清单样例：1 类、3 个划分、3 个样本；样本含 `image`/`annotation` 与 `sha256`/`width`/`height`/`box_count` 追溯字段及可选 `capture_batch`。 |
| `../../tests/fixtures/detection/dataset-manifest-invalid-split.json` | `val` 划分缺 `samples`，且 `train` 首个样本 `image` 为绝对路径，Schema 拒绝。 |
| `../../tests/fixtures/detection/dataset-manifest-invalid-sha.json` | `train` 首个样本 `sha256` 只有 63 位十六进制，不匹配 `^[0-9a-f]{64}$`，Schema 拒绝。 |
| `../../tests/test_detection_draft_schemas.py` | 标注/结果样例的通过/拒绝断言、本 README 状态断言、分类契约隔离断言。 |
| `../../tests/test_detection_dataset_manifest_draft.py` | 清单草案样例的通过/拒绝断言、追溯字段必填与 `sha256` 格式断言、`box_count = 0` 与可选字段断言、`schema_version` 固定断言、分类契约与数据清单 `1.0` 隔离断言。 |

本目录的 Schema 都是自包含的独立文件，不使用跨文件 `$ref`，可用任意 draft 2020-12 校验器直接加载。所有 JSON 使用不带 BOM 的 UTF-8。

## 3. 标注格式草案（`annotation.schema.json`）

```json
{
  "version": "0.1-draft",
  "image": "images/batch-1/001.png",
  "width": 640,
  "height": 480,
  "boxes": [
    { "class_id": 0, "x": 12, "y": 20, "w": 100, "h": 80 }
  ]
}
```

| 字段 | Schema 约束 | 后续校验器仍需检查 |
| --- | --- | --- |
| `version` | 可选，非空字符串（≤64 字符）。 | 取值格式与是否保留待 Q7 决定。 |
| `image` | 必填，相对路径；结构上禁止绝对路径、盘符、反斜杠、空路径段和 `.`/`..` 段。 | 必须与数据集清单中该样本的 `image` 一致（规范化后）；Windows 保留名、大小写冲突、符号链接由路径校验器补充。 |
| `width` / `height` | 必填，整数且 ≥ 1。 | 必须等于图片实际解码尺寸；不一致直接拒绝，不得静默缩放。 |
| `boxes` | 必填数组；每项字段白名单明确（`additionalProperties: false`）。 | 空数组是否合法待 Q6；数量上限、重复框、最小尺寸规则待 P2。 |
| `boxes[].class_id` | 必填，整数且 ≥ 0。 | 必须小于类别表长度；类别顺序只来自项目类别表/`labels.json`，加载时不得排序或重编号。 |
| `boxes[].x` / `y` | 必填，整数且 ≥ 0。 | 坐标必须在图片内（见第 4 节）。 |
| `boxes[].w` / `h` | 必填，整数且 ≥ 1。 | 坐标必须在图片内（见第 4 节）。 |

字段名与语义来自草案文档第 3.1 节的候选结构，不是生效契约。

## 4. 坐标与合法性规则（JSON Schema 之外，**由后续校验器实现，当前未实现**）

JSON Schema 只能表达单字段结构与数值范围，无法表达“框必须落在图片内”这类跨字段约束。以下规则必须由后续校验器实现，本目录的 Schema 和测试**不能**代替它们：

| 规则 | 草案约定 |
| --- | --- |
| 原点与方向 | 图片左上角为 `(0, 0)`，x 向右、y 向下。 |
| 单位 | 原图像素（图片解码后的实际尺寸），不是模型输入尺寸，也不是归一化坐标。 |
| 边界含义 | 右边界与下边界不包含，必须有 `0 <= x`、`0 <= y`、`w > 0`、`h > 0`、**`x + w ≤ width`**、**`y + h ≤ height`**。 |
| 类型 | `width`、`height`、`class_id`、`x`、`y`、`w`、`h` 必须是整数；布尔值、浮点数、字符串、`NaN`/`Inf` 一律拒绝（JSON Schema 的 `integer` 本身已拒绝布尔值与小数）。 |
| 越界 | 越界、零面积、负值一律拒绝；不得静默 clamp、取整或丢弃。 |
| 取整 | 标注界面按整数像素取整，取整规则固定并写入文档；保存前显示取整后的结果。规则待 P2 冻结。 |
| 最小尺寸 | 过小框的硬性下限待 P2 评审（建议 `w >= 2`、`h >= 2` 像素，未冻结）。 |
| 重复框 | 不按格式错误拒绝；数据检查阶段把同类、IoU 超过约定阈值的框报为“疑似重复”，要求人工确认，不自动删除。 |
| 空标注 | **待决问题 Q6**：本 Schema 不通过 `minItems` 预设结论，`boxes: []` 当前结构上可通过；是否合法由 P2 决定，实现方不得自行选择默认解释。 |
| 图片/标注一致性 | 图片与标注通过数据集清单的路径、图片摘要与标注内容核对绑定；标注文件摘要字段尚未纳入草案 Schema，是否必需待评审。重命名/删除时同步，摘要不一致拒绝。 |

样例 `annotation-valid.json` 的框都满足上述越界规则，便于将来语义校验器复用；但本目录测试只做结构校验。

## 5. 结果格式草案（`detection-result.schema.json`）

| 字段 | Schema 约束 | 说明 |
| --- | --- | --- |
| `source_image` | 必填，相对路径，规则同标注的 `image`。 | 结果归属的图片；坐标空间必须显式声明（草案约定最终结果为原图像素）。 |
| `detections` | 必填数组；每项 `additionalProperties: false`。 | 成功但无目标时必须为空数组，不得省略字段或写 `null`。 |
| `detections[].class_id` | 必填，整数且 ≥ 0。 | 必须对应 `labels.json`/项目类别表的有效下标；映射只认 `class_id`。 |
| `detections[].label` | 必填，非空字符串（≤128 字符）。 | 显示用冗余字段，必须与 `class_id` 对应，不参与映射。 |
| `detections[].confidence` | 必填，0～1 的数值。 | 口径由产物包清单声明，不同后端不能各自定义。 |
| `detections[].x` / `y` | 必填，数值且 ≥ 0。 | 结果坐标允许小数；标注仍是整数。取整与坐标空间规则待 P2 冻结。 |
| `detections[].w` / `h` | 必填，数值且 > 0。 | 同上。 |

坐标空间、结果排序、NMS 执行方与参数、空结果和固定样本匹配规则不在本 Schema 中定义，见草案文档第 4.2、4.5 节。当前协议 `1.0` 的信封只允许 `predictions`，检测 payload 不在本目录定义，也不能直接复用。

## 6. 数据集清单草案（`dataset-manifest-2.0-draft.schema.json`）

状态：**草案、未激活**，依据草案文档第 3.3 节。与文档候选相比，本 Schema 用固定标记 `schema_version: "2.0-draft"` 和 `splits` 分组表达清单，已纳入样本 `image`/`annotation` 引用与 `sha256`/`width`/`height`/`box_count` 四个追溯必填字段，`capture_batch` 为可选待决字段；顶层可选 `dataset_version` 也只允许 `"2.0-draft"`。**不表示**清单版本、字段或检测数据集能力已经确定：文档候选的正式版本值 `2.0` 仍未激活，正式升版前必须评审必填性、可选字段和版本命名，见草案文档第 5 节 Q1/Q6/Q7。

```json
{
  "schema_version": "2.0-draft",
  "dataset_version": "2.0-draft",
  "dataset_id": "ds-20261119-0001",
  "created_at": "2026-11-19T10:00:00+08:00",
  "classes": ["水杯"],
  "splits": {
    "train": {
      "samples": [
        {
          "image": "images/batch-1/001.png",
          "annotation": "annotations/batch-1/001.json",
          "sha256": "c5e448d067816253e55121d6bc5bf6bccac971231e7eee33bbf06b235c8bf1cc",
          "width": 640,
          "height": 480,
          "box_count": 1,
          "capture_batch": "batch-1"
        }
      ]
    },
    "val": { "samples": [] },
    "test": { "samples": [] }
  }
}
```

> 上面代码块中的空 `samples` 数组与摘要值只用于说明结构，不是可加载清单；完整可校验的样例见 `../../tests/fixtures/detection/dataset-manifest-valid.json`。空划分是否允许、`capture_batch` 是否保留均待 P2/Q7 决定。

| 字段 | Schema 约束 | 后续校验器仍需检查 |
| --- | --- | --- |
| `schema_version` | 必填，`const` 固定为 `"2.0-draft"`。 | 该标记只用于草案隔离；正式版本号如何命名、是否沿用文档的 `dataset_version: "2.0"` 由 Q1/P2 决定，决定前不得改写为已发布版本。 |
| `dataset_version` | 可选，出现时 `const` 只允许 `"2.0-draft"`；与 `schema_version` 是同一个草案标记，不能写成 `"2.0"`。 | 两者是否保留、合并或改名待 Q1/P2 决定；正式升版时必须只保留一个权威版本字段，接收方不得同时接受两个不同值。 |
| `dataset_id` | 必填，与分类清单相同的可移植标识符规则（字母或数字开头，≤128 字符）。 | 唯一性与追溯登记。 |
| `created_at` | 必填，带时区的 ISO 8601 时间戳。 | 时区与真实生成时间。 |
| `classes` | 必填数组，至少 1 项、唯一，类别名规则同分类清单；下标即 `class_id`。 | 与项目类别表、`labels.json` 和标注中的 `class_id` 上界一致；加载时不得排序或重编号。**单类检测待决（Q2）**：本草案按 `minItems: 1` 允许单类，分类数据集清单 `1.0` 仍要求至少 2 类；是否正式允许 1 类未冻结，实现方不得自行决定。 |
| `splits` | 必填对象，只允许 `train`/`val`/`test` 三个键，且三个键都必填。 | 划分由清单决定，不从目录名推断；同一采集批次不得跨划分、`test` 冻结、同一图片的所有框跟随图片进入同一划分。 |
| `splits.<name>.samples` | 必填数组，元素为样本对象。本 Schema 不设 `minItems`，空数组是否允许待 P2/后续校验器决定。 | 每个划分的最小样本数、类别覆盖、样本总数上限。 |
| `splits.<name>.samples[].image` | 必填，相对于项目 `data/` 数据根的相对路径；结构上禁止绝对路径、盘符、反斜杠、空路径段和 `.`/`..` 段。 | 文件存在、可解码、摘要；与标注文件中的 `image` 规范化后一致。 |
| `splits.<name>.samples[].annotation` | 必填，每图标注 JSON 的相对路径，路径规则同上。 | 文件存在、可解析；标注中的 `image`/`width`/`height`/`box_count` 必须与样本字段及图片实际内容核对。标注文件摘要字段尚未纳入本 Schema，是否必需待评审。 |
| `splits.<name>.samples[].sha256` | 必填，64 位小写十六进制字符串（`^[0-9a-f]{64}$`）。 | 必须等于图片文件实际内容的 SHA-256；只证明文件与清单一致，不证明来源可信。 |
| `splits.<name>.samples[].width` / `height` | 必填，整数且 ≥ 1。 | 必须等于图片实际解码尺寸与标注中的 `width`/`height`；不一致直接拒绝，不得静默缩放。 |
| `splits.<name>.samples[].box_count` | 必填，整数且 ≥ 0；`0` 是空标注的结构表达。 | 必须与标注 `boxes` 数量一致；`box_count = 0` 是否允许作为负样本仍待 Q6，本 Schema 只保证结构可表达。 |
| `splits.<name>.samples[].capture_batch` | 可选，非空字符串（≤128 字符）。 | 采集批次命名、唯一性和“同一批次不跨划分”规则待 Q7/P2；不写该字段时无法做批次追溯检查。 |

`additionalProperties: false` 在顶层、`splits`、每个划分和每个样本上都启用，未知字段不提供静默忽略模式；三个划分键全部必填，缺任一划分或划分缺 `samples` 都被拒绝。

无法用本 Schema 表达、当前未实现且必须由后续校验器完成的规则至少包括：标注文件与图片实际存在、图片可解码、`sha256`/`width`/`height` 与图片实际内容/尺寸一致、标注可解析且其 `image` 与样本 `image` 一致、每个 `class_id` 小于 `classes` 长度、`box_count` 与标注框数一致、`capture_batch` 不跨划分、`test` 冻结、路径大小写与 Windows 保留名冲突。标注文件摘要字段尚未纳入本 Schema，是否必需待评审。样例 `dataset-manifest-valid.json` 只用于结构校验，**通过 Schema 不等于数据集可用**。

### 与分类数据集清单 `1.0` 的隔离

- 分类数据集清单 `1.0`（`schemas/dataset-manifest.schema.json`）的字段、`dataset_version` 1.x、类别数下限（至少 2）和校验器 `backend/classification/dataset.py` 均不因本草案改变；现有分类数据仍按 [数据与运行基线](../../docs/data-and-runtime-baseline.md) 的布局与流程处理。
- 本 Schema 只存在于 `schemas/detection/` 草案目录，未加入 `schemas/` 根目录，不在 `backend/contracts` 和 `backend/classification` 的 Schema 加载路径上；`task: object_detection` 的模型包仍被 `backend.contracts.validate_model_package` 拒绝为 `CONTRACT_TASK_UNSUPPORTED`。
- 禁止同一项目混用分类 `1.0` 与检测 `2.0` 清单、禁止把分类清单改义存框、禁止自动把分类项目升级为检测项目；检测清单要成为可加载产物，必须先完成 Q1/Q2 等决策、契约升版和校验器实现。

## 7. 有效/无效样例的预期行为

| 样例 | 预期 |
| --- | --- |
| `annotation-valid.json` | 通过 `annotation.schema.json`。 |
| `annotation-invalid-absolute-path.json` | 被拒绝：`image` 为 Windows 盘符绝对路径，不匹配相对路径规则。 |
| `annotation-invalid-negative-box.json` | 被拒绝：`w` 为负，不满足 `minimum: 1`。 |
| `result-valid.json` | 通过 `detection-result.schema.json`。 |
| `result-invalid-confidence.json` | 被拒绝：`confidence = 1.25` 超出 `maximum: 1`。 |
| `dataset-manifest-valid.json` | 通过 `dataset-manifest-2.0-draft.schema.json`：1 类、3 个划分、3 个样本，每个样本含 `image`/`annotation`/`sha256`/`width`/`height`/`box_count` 与可选 `capture_batch`。 |
| `dataset-manifest-invalid-split.json` | 被拒绝：`splits.val` 缺 `samples`；同时 `splits.train.samples[0].image` 为 Windows 盘符绝对路径。该样例有意同时破坏两个条件，测试分别断言两处定位。 |
| `dataset-manifest-invalid-sha.json` | 被拒绝：`splits.train.samples[0].sha256` 只有 63 位，不匹配 `^[0-9a-f]{64}$`。 |

测试还用有效样例派生出若干拒绝/允许场景：缺 `sha256`/`width`/`height`/`box_count` 被拒、64 位但大写的 `sha256` 被拒、`box_count = -1` 被拒、空字符串 `capture_batch` 被拒、`dataset_version` 写成 `"2.0"` 被拒；`box_count = 0`、缺省 `capture_batch`、缺省 `dataset_version` 结构上被接受（空标注合法性与字段去留仍待 Q6/Q7/Q1）。

`annotation-invalid-negative-box.json` 只破坏一个条件（`w`）；`w = 0` 同样会被 `minimum: 1` 拒绝，`h` 规则相同。样例只做结构校验：通过 Schema **不等于**标注语义合法，更不等于检测能力可用。

## 8. 校验方式

```powershell
.venv\Scripts\python.exe -m pytest tests/test_detection_draft_schemas.py tests/test_detection_dataset_manifest_draft.py -q
.venv\Scripts\python.exe scripts/check_docs.py  # 仅在修改 docs/ 后需要
```

这两组测试同时断言：

1. 本目录 Schema（标注、结果、数据集清单 `2.0` 草案）都是合法的 draft 2020-12，有效样例通过、无效样例（含非法 `sha256`）被 `jsonschema.exceptions.ValidationError` 拒绝，未知字段被拒绝；
2. 本目录存在且本 README 明确标注“草案/未激活/不属于当前契约”，并记录 Schema 无法表达的越界规则；
3. 活跃分类契约未被修改或放宽：现有分类清单样例仍通过 `schemas/model-manifest.schema.json`，仅把 `task` 换成 `object_detection` 后仍被 `backend.contracts.validate_model_package` 拒绝为 `CONTRACT_TASK_UNSUPPORTED`，`ContractPolicy` 默认值仍只支持 `image_classification` 与契约 `1.0`；
4. 数据集清单 `2.0` 草案与分类数据清单隔离：有效样例（1 类、3 个划分、3 个样本，含追溯字段）通过，无效样例被拒（`val` 缺 `samples`、`image` 为绝对路径、`sha256` 仅 63 位），样本缺 `sha256`/`width`/`height`/`box_count` 被拒、大写或长度不符的 `sha256` 被拒、`box_count = 0` 结构允许而 `-1` 被拒、可选 `dataset_version` 只接受 `2.0-draft` 且缺省合法、可选 `capture_batch` 缺省合法但空字符串被拒，`schema_version` 固定为 `2.0-draft`（`2.0`、`1.0` 等错误版本被拒），`backend/classification/dataset.py` 仍只加载 `schemas/dataset-manifest.schema.json` 的 `1.x` 分类清单；
5. 草案文档第 3.3 节与草案 Schema 口径一致：该节注明“以草案 Schema 为准（未激活）”，并出现 `splits` 与 `sha256`/`width`/`height`/`box_count`/`capture_batch` 等字段名；旧候选名 `annotation_path`/`annotation_sha256` 不再出现在该节。

这些断言只证明草案文件与当前契约隔离。分类 `1.0` 的完整回归以 `tests/test_manifest_package.py` 等现有测试为准；检测能力的任何结论都需要评审通过、契约升版和实际实现与验证，当前均未发生。
