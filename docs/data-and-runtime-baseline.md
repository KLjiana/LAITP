# 数据与运行基线（T03）

编制日期：2026-11-17

状态：T03 的数据清单、固定划分与校验，T04 的 CPU 训练，T05 的 ONNX 导出与模型包发布已实现；T06 的独立推理见[独立推理说明](runtime-inference.md)。正式验收配置因缺少目标机器与真实数据**尚未冻结**。
训练与导出验证使用构造样例或短轮次基线，不能代表真实课堂效果。

所属计划：[M0-01 分类最小闭环](m0-01-classification-plan.md)。强制约束见[模型接口与产物契约](model-contract.md)。

## 1. 已实现内容

| 内容 | 位置 | 说明 |
| --- | --- | --- |
| 数据清单 Schema | `schemas/dataset-manifest.schema.json` | 版本 `1.0`，类别表、样本路径、摘要、类别 ID、采集批次、划分 |
| 清单构建与固定划分 | `backend/classification/dataset.py` | 按批次稳定划分训练/验证，输出可复现清单 |
| 数据校验 | 同上 | 路径、摘要、重复内容、批次泄漏、类别覆盖、图片可解码性 |
| CPU 训练 | `backend/classification/training.py` | 冻结特征提取器、训练线性分类头、指标与可重载产物 |
| ONNX 导出与发布 | `backend/classification/export.py` | 生成契约 1.0 模型包、固定样本参考结果与转换验证记录 |
| 预训练权重记录 | `configs/weights.v1.json` | MobileNetV3-Small ImageNet 权重，含来源、许可证、摘要、本地路径 |
| 正式验收配置 | `configs/acceptance.v1.json` | 显式标记 `not_frozen`，列出阻塞项 |
| 测试 | `tests/test_dataset.py`、`tests/test_training.py`、`tests/test_export.py` | 构造图片与随机初始化模型验证规则，不代表真实效果 |

## 2. 数据布局

```text
项目/
  data/
    dataset-manifest.json          # 清单，随项目保存
    images/<类别>/<采集批次>/<图片>       # 训练与验证
    test-images/<类别>/<采集批次>/<图片>  # 独立测试集，冻结后不参与调参
```

- 类别顺序由清单 `classes` 数组决定，下标就是类别 ID；不从目录遍历顺序推断。
- 类别名同时作为目录名，因此必须是非空、首尾无空白、可作相对路径的名称（允许中文）。
- 采集批次名使用字母、数字、`.`、`_`、`-`，长度 1～64。
- 训练与验证必须来自不同采集批次；测试集使用独立目录，且不参与任何调参。

## 3. 固定划分规则

- 每个类别至少需要 2 个采集批次，否则拒绝构建（无法做批次级划分）。
- 验证批次按 `sha256(seed:class_id:batch)` 排序后选取，默认比例约 20%，每类至少保留 1 个训练批次和 1 个验证批次；不追求精确比例。
- 相同目录内容、类别顺序和种子产生完全相同的清单，`created_at` 可显式传入以保证复现。
- 清单按 `(class_id, capture_batch, path)` 排序，避免生成结果抖动。

## 4. 校验规则与错误码

`validate_dataset_manifest` 先按 Schema 校验结构，再做语义与文件检查；结构失败时不再继续。

| 错误码 | 阶段 | 含义 |
| --- | --- | --- |
| `DATASET_JSON_INVALID` | schema | 清单不是有效 UTF-8 JSON |
| `DATASET_SCHEMA_INVALID` | schema | 不符合 Schema（缺字段、未知字段、类别重复、非法路径字符等） |
| `DATASET_VERSION_UNSUPPORTED_MAJOR` | schema | 数据清单主版本不受支持 |
| `DATASET_VERSION_UNSUPPORTED_MINOR` | schema | 数据清单次版本高于支持范围 |
| `DATASET_CLASS_INVALID` | labels | 构建时类别名为空、重复或不能作为目录名 |
| `DATASET_CLASS_ID_INVALID` | labels | 样本类别 ID 超出类别表范围 |
| `DATASET_EMPTY_CLASS` | semantics | 类别目录缺失 |
| `DATASET_BATCH_INVALID` | semantics | 缺少批次子目录、批次名为空或批次内没有图片 |
| `DATASET_SAMPLE_PATH_INVALID` | paths | 样本路径含目录穿越、绝对路径或符号链接越界 |
| `DATASET_SAMPLE_DUPLICATE` | paths | 同一路径重复出现 |
| `DATASET_CONTENT_DUPLICATE` | semantics | 不同样本内容摘要相同（重复文件或跨划分泄漏） |
| `DATASET_FILE_MISSING` | integrity | 样本文件不存在 |
| `DATASET_FILE_UNREADABLE` | integrity | 样本文件无法读取 |
| `DATASET_DIGEST_MISMATCH` | integrity | 文件摘要与清单不一致 |
| `DATASET_IMAGE_UNDECODABLE` | integrity | 文件无法解码为图片 |
| `DATASET_BATCH_MIXED_SPLITS` | semantics | 同一采集批次同时出现在多个划分 |
| `DATASET_CLASS_MISSING_IN_SPLIT` | semantics | 某类别在 train/val（或已有的 test）中没有样本 |
| `DATASET_CLASS_TOO_FEW_SAMPLES` | semantics | 某类别样本数低于策略下限 |
| `DATASET_TEST_SPLIT_MISSING` | semantics | 要求独立测试集但清单没有 test 样本 |

正式验收时使用加严策略：`require_test_split=True`、按计划第 4 节要求每类 30～50 张开发图片、每类至少 10 张测试图片（通过 `--min-train`、`--min-val`、`--min-test` 传入）。

## 5. 使用命令

```powershell
# 构建清单（类别顺序即类别 ID）
python -m backend.classification.dataset build `
  --root data --classes 水杯 书本 笔袋 `
  --dataset-id ds-20261117-0001 --output data\dataset-manifest.json

# 校验（开发数据）
python -m backend.classification.dataset validate data\dataset-manifest.json --root data

# 正式验收前的加严校验（示例值，按实际数据规模调整）
python -m backend.classification.dataset validate data\dataset-manifest.json --root data `
  --require-test --min-train 30 --min-val 8 --min-test 10
```

退出码 `0` 通过、`1` 存在问题；标准输出为 UTF-8 JSON，包含 `ok`、`counts`（按划分与类别）与 `issues`。

项目内批量导入（自动转 PNG、按内容去重并重建清单）：

```powershell
python -m backend.project import --root 学生项目 --class 水杯 --source D:\照片\水杯
python -m backend.project import --root 学生项目 --class 水杯 --source D:\照片\水杯-第二组 --batch batch-2
python -m backend.project import --root 学生项目 --class 水杯 --source D:\测试照片 --split test
python -m backend.project rebuild-dataset --root 学生项目
```

- 图片统一转为 RGB PNG 后写入 `data/images/<类别>/<批次>/`（测试集为 `data/test-images/...`），按来源内容 SHA-256 去重。
- 批次名省略时使用 `batch-YYYYMMDD-HHMMSS`，同秒冲突追加序号；每次导入使用不同批次才能满足“每类至少 2 个批次”。
- 导入后自动重建 `data/dataset-manifest.json` 并写回 `project.json`；若数据不足（例如某类只有 1 个批次），导入文件保留，命令返回 `manifest_error` 说明原因，而不是静默生成不完整清单。
- `python -m backend.project samples --root 学生项目` 列出样本（类别/存储划分/批次/路径）；`delete-sample --path ...` 删除单个样本、清理空批次目录并重建清单。
- `python -m backend.project check-dataset --root 学生项目` 以项目为入口执行训练前校验（结构、批次、覆盖、文件摘要与解码）；`--require-test` 要求独立测试集且每类至少 1 张；`--min-train/--min-val/--min-test` 可设置严格验收的每类样本下限。
- 类别改名用 `rename-class --old --new`（同步移动 `images/` 与 `test-images/` 目录并按原顺序更新类别表）；样本改名用 `rename-sample --path --name`（保留扩展名，冲突拒绝）。
- `python -m backend.project runs --root 学生项目` 列出训练历史（运行 ID、准确率、是否已登记）；`export-run --run <运行ID>` 从历史运行重新导出模型包并切换当前模型（必要时先登记训练产物）。

## 6. 训练（T04）

训练采用“冻结 MobileNetV3-Small 特征提取器 + 线性分类头”：

- 特征提取在训练开始时执行一次，缓存 576 维池化特征；分类头训练在该缓存上进行，两者耗时分别记录。
- 只读取 `train` 与 `val` 划分；`test` 样本只在指标中记录数量（`unused_test_samples`），不参与训练或调参。
- 随机种子、线程数、批量大小、学习率、权重衰减和输入尺寸写入本次运行配置；相同种子与线程数下重复训练结果一致（本机测试已验证）。
- 默认 30 轮是探索性基线，不是冻结的课堂参数；输入尺寸、轮数等应随真实数据规模调整后重新冻结。

```powershell
python -m backend.classification train `
  --dataset data\dataset-manifest.json --data-root data `
  --output runs --run-id run-20261117-0001 `
  --weights-config configs\weights.v1.json --epochs 30 --threads 8
```

产物写入 `runs/<run_id>/`：先写临时目录，成功后才整体改名发布；已存在的 `run_id` 会被拒绝，不做覆盖。

| 文件 | 内容 |
| --- | --- |
| `config.json` | 本次运行参数、路径、数据与权重摘要、环境版本 |
| `dataset-manifest.json` | 输入数据清单的完整副本，保证训练记录可追溯 |
| `metrics.json` | 训练/验证损失与准确率历史、验证集准确率、各类召回、混淆矩阵、逐样本预测结果、耗时 |
| `model.pt` | 分类头 state_dict、类别表、预处理参数、模型与数据来源摘要 |

`metrics.json` 的 `evaluation.samples` 记录验证样本路径、真实类别 ID 与预测类别 ID，供界面展示误判样本；该字段为可选（旧运行记录仍可读取）。

`python -m backend.classification report --run runs\<id>` 会校验运行文件摘要、重新加载 `model.pt`，再输出准确率、每类召回、混淆矩阵与误判样本的 JSON 摘要；界面显示前使用同一结构。

`load_training_artifact` 可重新加载 `model.pt`（可选校验特征提取器权重摘要），并在同一验证集复现记录中的准确率；该能力由测试覆盖。

| 错误码 | 含义 |
| --- | --- |
| `TRAINING_WEIGHTS_MISSING` | 本地缺少预训练权重文件 |
| `TRAINING_WEIGHTS_DIGEST_MISMATCH` | 权重摘要与配置不一致 |
| `TRAINING_CONFIG_INVALID` | 运行参数非法，或 `run_id` 目录已存在 |
| `TRAINING_ARTIFACT_INVALID` | 训练产物格式错误，或特征提取器摘要与训练记录不符 |

数据清单未通过校验时训练立即终止并返回 `DATASET_*` 错误码，不生成任何产物。

训练产物同时写入 `training-artifact.json`（格式 `laitp-training-record-1.0`）：记录训练产物 ID、运行 ID、数据与权重摘要、类别表、预处理、各文件摘要。该记录是 T05 导出时的来源产物，`provenance.source.manifest_sha256` 指向它的摘要。

## 7. 导出与模型包发布（T05）

```powershell
python -m backend.classification export `
  --run runs\run-20261117-0001 --output exports `
  --artifact-id art-20261117-0001 --project-id proj-classification-demo `
  --weights-config configs\weights.v1.json --platform windows-x64
```

产物布局（先写临时目录，全部检查通过后整体改名发布；`artifact_id` 目录已存在时拒绝，不原地修改）：

```text
exports/<artifact_id>/
  model-package/
    manifest.json
    model.onnx
    labels.json
    validation/
      class-<类别 ID>.png
      expected-class-<类别 ID>.json
      thresholds.json
  conversion-record.json
```

导出与发布检查：

1. 读取 `training-artifact.json` 并核对其中列出的文件摘要，`model.pt` 不符即拒绝。
2. 校验权重摘要（提供 `--weights-config` 时）、预处理参数和类别表与训练记录一致。
3. 导出 ONNX 后执行 `onnx.checker`，重新读取实际 opset 与输入输出形状。
4. 用 ONNX Runtime 对固定样本重新推理，生成参考结果；比较 PyTorch 与 ONNX Runtime 的原始 logits 和预测。
5. 用 T02 产物包校验器校验 manifest、摘要、标签、张量和运行时；任何一步失败都不发布。

| 阈值（探索性默认，写入 `validation/thresholds.json`） | 值 |
| --- | --- |
| `logit_abs_tolerance` | `1e-3` |
| `logit_rel_tolerance` | `1e-3`（相对最大 logit 幅值） |
| `prediction_agreement` | `1.0` |

这些阈值只用于导出一致性，不是课堂效果目标；正式验收前应按任务、精度与设备冻结，不得在看到失败结果后放宽。本机 3 类构造样例（96×96）实测 `max_abs_diff ≈ 3.3e-6`、相对差 `≈ 1.8e-5`、预测一致率 `1.0`，只能说明当前实现一致。

`conversion-record.json` 绑定产物 ID、清单摘要、来源训练产物 ID 与摘要、转换器与运行时版本、opset、固定样本检查结果和阈值文件摘要；它独立于模型包保存，便于后续追加验证而不修改已发布产物。

| 错误码 | 含义 |
| --- | --- |
| `EXPORT_CONFIG_INVALID` | 参数非法（ID、opset、平台、容差）或导出目录已存在 |
| `EXPORT_SOURCE_INVALID` | 训练记录、模型文件、权重、预处理或类别表不一致 |
| `EXPORT_SAMPLE_MISSING` | 固定样本缺失或数量不足 |
| `EXPORT_ONNX_FAILED` | `torch.onnx.export` 或 `onnx.checker` 失败 |
| `EXPORT_VERIFICATION_FAILED` | opset、实际张量形状或数值比对超出阈值 |
| `EXPORT_PACKAGE_REJECTED` | 发布前未通过 T02 契约校验，包不会发布 |

已发布包可随时用契约校验器复检：

```powershell
python -m backend.contracts package exports\art-20261117-0001\model-package `
  --runtime onnxruntime --runtime-version 1.23.2 --platform windows-x64 `
  --capability onnxruntime-cpu
```

## 8. 依赖版本

本机验证环境：Windows 11（10.0.26200）、Python 3.12.1 x64。

| 组件 | 版本 | 用途 | 离线要求 |
| --- | --- | --- | --- |
| Python | 3.12.1 | 后端运行时 | 随离线包提供 |
| jsonschema | 4.25.1 | 契约与数据清单结构校验 | 纯 Python 轮子，可随包 |
| onnx | 1.19.1 | 读取模型真实张量签名 | 平台相关二进制，需按目标机准备 |
| numpy | 2.5.5 | onnx 依赖 | 同上 |
| Pillow | 11.3.0 | 图片解码校验 | 平台相关二进制，需按目标机准备 |
| pytest | 8.4.2 | 开发测试，不随产品分发 | 仅开发环境 |
| torch | 2.8.0+cpu | 特征提取与分类头训练、推理 | 已安装；CPU 轮子来自 pytorch 官方索引，需随离线包准备 |
| torchvision | 0.23.0+cpu | MobileNetV3 结构与预训练权重 | 已安装；同上 |
| onnxruntime | 1.23.2 | 部署端推理与导出一致性验证 | 已安装；平台相关二进制，需按目标机准备 |
| .NET SDK | 8.0.428 | 构建 WPF 桌面程序与检查项目 | 开发机本地 `.dotnet/`；不随产品分发 |
| .NET Desktop Runtime | 自包含发布（8.0） | 运行桌面程序 | 自包含发布已含运行时，无需目标机预装 |
| Windows SDK 投影 | `net8.0-windows10.0.19041.0` | 摄像头 WinRT（MediaCapture）调用 | 随自包含发布复制，需 Windows 10 1809+ |

离线准备：

```powershell
.\.venv\Scripts\python.exe -m pip download -r requirements-dev.txt -d vendor\wheels
.\.venv\Scripts\python.exe -m pip install --no-index --find-links vendor\wheels -r requirements-dev.txt
```

`requirements.txt` 已声明 `--extra-index-url https://download.pytorch.org/whl/cpu` 以获取 `+cpu` 轮子；离线准备时需确认该索引的轮子也已下载到 `vendor\wheels`。

## 9. 预训练权重记录

| 字段 | 值 |
| --- | --- |
| 权重 ID | `mobilenet_v3_small-imagenet` |
| 架构 | `mobilenet_v3_small` |
| 来源 | torchvision 0.23.0 预训练权重 |
| 下载地址 | `https://download.pytorch.org/models/mobilenet_v3_small-047dcff4.pth` |
| 许可证 | BSD-3-Clause |
| 大小 | 10,306,551 字节 |
| SHA-256 | `047dcff4addef86ea5bc2eff13c9614dc11f47ab1160d0a71a25e7db994f4e1f` |
| 本地路径 | `artifacts/weights/mobilenet_v3_small-047dcff4.pth`（不提交到仓库） |

获取与核对：

```powershell
New-Item -ItemType Directory -Force artifacts\weights | Out-Null
Invoke-WebRequest -Uri https://download.pytorch.org/models/mobilenet_v3_small-047dcff4.pth `
  -OutFile artifacts\weights\mobilenet_v3_small-047dcff4.pth
(Get-FileHash -Algorithm SHA256 artifacts\weights\mobilenet_v3_small-047dcff4.pth).Hash.ToLower()
```

摘要必须与 `configs/weights.v1.json` 一致（文件名前缀 `047dcff4` 与完整摘要前 8 位相同，可作快速核对）。权重缺失或摘要不符时，训练必须立即报错，不得自动下载。

## 10. 正式验收配置状态

`configs/acceptance.v1.json` 当前为 `not_frozen`，尚缺：

1. 目标 Windows 电脑的 CPU、内存、系统版本和课堂训练时间预算。
2. 真实课堂数据与冻结的数据集摘要、类别划分。
3. 目标机上的训练、导出与推理链路复验（开发机已实现并验证）、有效效果阈值与数值容差。

在上述信息齐全并写入阈值后，将 `status` 改为 `frozen` 并填写 `frozen_at`。阈值必须在正式验收运行前确定，不得根据失败结果事后放宽；未冻结时只能报告测量结果，不能判定课堂性能达标。

## 11. 未验证与限制

- 测试使用 Pillow 生成的构造图片，只验证清单、划分、训练流程与完整性规则，**不能**代表真实分类效果或课堂可行性。
- 训练指标来自短轮次、构造数据或随机初始化模型，只用于流程验证；未在真实课堂数据上训练，未确定收敛轮数与效果目标。
- 未采集真实物品照片，未确定目标机器，未执行 Windows 目标机性能、内存与离线链路测量。
- Linux 与干净 Windows 机器未验证；onnx、Pillow、torch 等平台相关依赖需在目标机重新准备并记录摘要。
- 数据清单只证明文件与记录一致，不证明类别标注语义正确；标注质量仍需人工抽查与固定交接样本。
- 导出与固定样本比对只覆盖构造数据与短训练模型；未在真实课堂模型上验证数值一致性和误差。
- 独立推理已实现（T06），任务协议与最小父进程已实现（T07），见[任务协议与父进程](task-protocol.md)；本机性能与离线依赖记录见[本机性能与离线验证记录](performance-m0.md)。目标 Windows 机器断网性能验收（T08 剩余部分）尚未执行。
