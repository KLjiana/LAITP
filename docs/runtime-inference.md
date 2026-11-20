# 独立推理运行时（T06）

编制日期：2026-11-17

状态：`validate`、`predict`、`evaluate` 三个命令已实现并通过本地测试；T07 的按行 JSON 工作进程与最小父进程见[任务协议与父进程](task-protocol.md)。验证只使用构造数据和短训练模型，不能代表真实分类效果或目标机性能。

所属计划：[M0-01 分类最小闭环](m0-01-classification-plan.md)。强制约束见[模型接口与产物契约](model-contract.md)。
数据、训练与导出基线见[数据与运行基线](data-and-runtime-baseline.md)。

## 1. 运行方式

运行时只依赖模型产物包、ONNX Runtime 与 Pillow，不导入训练框架、不访问训练目录：

```powershell
# 校验模型包并执行固定样本验证
python -m backend.runtime validate --package exports\art-20261117-0001\model-package

# 单张图片预测
python -m backend.runtime predict --package exports\art-20261117-0001\model-package `
  --image 学生项目\data\test-images\水杯\batch-1\001.png

# 在数据清单的指定划分上评估
python -m backend.runtime evaluate --package exports\art-20261117-0001\model-package `
  --manifest 学生项目\data\dataset-manifest.json --data-root 学生项目\data `
  --split test --report 学生项目\validation-runs\eval.json
```

标准输出为 UTF-8 JSON，退出码 `0` 通过、`1` 失败。`--platform` 默认 `windows-x64`，用于与清单 `runtime` 声明比对。

| 命令 | 输出要点 |
| --- | --- |
| `validate` | 契约校验结果、固定样本数、逐样本最大差异、预测一致率 |
| `predict` | 产物 ID、全部类别的 ID/名称/概率（按概率降序）、输入张量形状；`--top-k` 可截断输出 |
| `evaluate` | 产物 ID、数据集 ID、划分、样本/正确/错误数、准确率、各类召回、混淆矩阵、误判清单；`--report` 写文件 |

## 2. 加载与校验顺序

`validate` 与 `predict`/`evaluate` 都先执行[契约校验](contract-validation.md)（结构、摘要、标签、张量、运行时），再加载 ONNX Runtime 会话，然后：

1. 核对会话实际输入输出名称与清单一致；
2. 按清单 `preprocessing.steps` 重新预处理固定样本，与参考结果中的输入张量摘要比对（`RUNTIME_INPUT_MISMATCH`）；
3. 重新推理并与参考结果中的原始输出、预测类别比对（`RUNTIME_FIXED_SAMPLE_MISMATCH`）。

这对应契约第 5 节“电脑加载”的要求：首次在某个运行环境加载时必须执行固定样本验证，不能只比较文件摘要。

## 3. 预处理执行规则

预处理参数全部来自清单，不在运行时硬编码。当前实现：

| 步骤 | 支持范围 |
| --- | --- |
| `resize` | `stretch`，插值 `nearest` / `bilinear` / `bicubic` / `area` |
| `normalize` | 公式 `(pixel * scale - mean) / std`，通道顺序 `RGB` / `BGR` |
| `transpose` | `HWC → CHW` |
| `add_batch_dimension` | 任意轴，通常为 0 |

显式拒绝（`RUNTIME_PREPROCESSING_UNSUPPORTED`）：`letterbox` / `crop` 缩放、`0..1` 等非 `0..255` 像素输入、非 `RGB/BGR` 通道顺序、违反顺序约束的步骤（例如归一化后再缩放）。不会用近似参数代替清单声明。

数值一致性：训练端与运行时都使用 `float32` 按同一公式运算；导出的参考结果保存预处理后输入张量的 SHA-256，运行时重复计算并比对，用于发现两端实现漂移。

## 4. 评估规则

- `evaluate` 读取数据清单并用其 `classes` 顺序映射类别；若与模型包 `labels.json` 顺序不一致，直接拒绝（`RUNTIME_CONFIG_INVALID`），避免指标整体错位。
- 评估时对数据清单采用宽松策略（不要求训练/验证划分），因此可以只提供冻结的测试清单；但样本文件、摘要、类别 ID、批次划分仍会校验。
- `--split` 默认 `test`；该划分没有样本时返回 `RUNTIME_CONFIG_INVALID`。
- 指标定义：准确率 = 正确样本数 / 样本数；各类召回 = 该类对角线 / 该类实际样本数（无样本时为 `null`）；混淆矩阵行是实际类别、列是预测类别；误判清单包含路径、实际/预测类别与预测概率。
- 少量固定样本只用于交接冒烟验证，不能代替代表性测试集上的效果评估。

## 5. 错误码

| 错误码 | 含义 |
| --- | --- |
| `RUNTIME_MODEL_LOAD_FAILED` | 无法读取清单、模型或标签文件 |
| `RUNTIME_IMAGE_INVALID` | 待测图片无法解码 |
| `RUNTIME_PREPROCESSING_UNSUPPORTED` | 清单中的预处理步骤不受当前运行时支持 |
| `RUNTIME_OUTPUT_INVALID` | 模型输入输出数量、名称、类型或参考输出结构不符 |
| `RUNTIME_INPUT_MISMATCH` | 预处理后输入张量摘要与参考结果不一致 |
| `RUNTIME_FIXED_SAMPLE_MISMATCH` | 原始输出差异超阈值或预测类别与参考结果不一致 |
| `RUNTIME_CONFIG_INVALID` | 评估配置或数据清单与模型包不匹配 |

契约校验失败时直接返回 `CONTRACT_*` 错误码，不会继续推理。

## 6. 本机验证记录

环境：Windows 11（10.0.26200）、Python 3.12.1、onnxruntime 1.23.2。构造数据：3 类，训练 18 张、验证 9 张、测试 6 张（32×32 输入、1 轮训练，仅用于流程验证）。

| 检查 | 结果 |
| --- | --- |
| `validate` | 固定样本 3 个，`passed=true`，`max_abs_diff=0.0` |
| `predict` | 返回 3 类概率，和为 1；带产物 ID |
| `evaluate`（test，6 张） | 准确率 0.333、混淆矩阵合计 6、误判清单 4 条（模型只预测到一类，符合构造数据的无信号情况） |
| 中文/含空格路径 | 模型包复制到 `学生 项目\模型 包 v1` 后预测正常 |
| 独立进程 | 在仓库外工作目录、`PYTHONPATH` 指向仓库时，`python -m backend.runtime predict` 正常输出 |

这些数字只证明流程可用，不代表真实分类效果。

## 7. 未验证与限制

- 未使用真实课堂图片与真实训练模型；准确率、召回与混淆矩阵仅验证计算逻辑。
- 未在目标 Windows 电脑上测量加载时间、单图延迟、内存与吞吐；未验证摄像头实时链路。
- 尚未支持 `letterbox`/`crop` 预处理与量化模型的特殊输入输出（量化契约字段尚未在运行时实现）。
- C#/WPF 任务管理已接入（见[桌面外壳](desktop-shell.md)）；命令行与工作进程均为一次性调用，进度粒度与取消时延未在真实界面验证。
- Linux 与其他 ONNX Runtime 版本未验证。
