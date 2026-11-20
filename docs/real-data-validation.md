# 真实公开数据验证（开发期）

编制日期：2026-11-17

状态：使用公开数据集 Fashion-MNIST 的 3 类子集，在本开发机完成“导入 → 数据检查 → 训练 → 发布 → 报告 → 预测 → 项目校验”的完整链路验证。**这是开发期单机验证，不代表课堂真实数据、目标 Windows 机器或离线分发已验收。**

所属路线：[总体路线](roadmap.md) M1 / M0-01 真实数据要求的补充证据。相关文档：[数据与运行基线](data-and-runtime-baseline.md)、[项目文件格式](project-format.md)、[桌面外壳](desktop-shell.md)。

## 1. 数据来源与许可

| 项目 | 内容 |
| --- | --- |
| 数据集 | Fashion-MNIST（Zalando 商品图片，28×28 灰度，10 类） |
| 来源 | https://github.com/zalandoresearch/fashion-mnist |
| 许可 | MIT（https://github.com/zalandoresearch/fashion-mnist/blob/master/LICENSE） |
| 获取方式 | `torchvision.datasets.FashionMNIST(download=True)`，开发机联网一次性下载 |
| 获取日期 | 2026-11-17 |
| 使用范围 | 仅开发验证；**不随产品分发**，原始文件与子集均在 `artifacts/`（已忽略，不提交） |
| 记录 | [configs/datasets.v1.json](../configs/datasets.v1.json) 记录原始文件大小与 SHA-256 |

原始文件摘要（节选）：

| 文件 | 大小 | SHA-256 |
| --- | --- | --- |
| train-images-idx3-ubyte | 47,040,016 | `c59f468a2f672dc815687fe0f83887768d799fd8a3f3276145d20f83aa44d888` |
| train-labels-idx1-ubyte | 60,008 | `bad3541b69d912435c50bb6ba87bec294ff4f6a2e1246121d8633921760443d9` |
| t10k-images-idx3-ubyte | 7,840,016 | `5b4141f0afbad91edebe8549f8fcffe087ea10ca49f1dbef5c9a5cd8815ce37b` |
| t10k-labels-idx1-ubyte | 10,008 | `0402a96d92fd2663957122ceb108a494c5af83dab82d92729df917d7dec38c34` |

## 2. 子集构造

- 类别：Fashion-MNIST 的 0=T-shirt/top、1=Trouser、2=Pullover，项目中使用中文类别名 `T恤 / 裤子 / 外套`（类别顺序即类别 ID）。
- 训练图片：每类 40 张，按 2 个采集批次（`batch-a`、`batch-b`，各 20 张）导入，满足 T03 的批次划分要求。
- 测试图片：每类 10 张，导入 `data/test-images/<类别>/batch-test/`。
- 数据清单自动划分：每类 1 个批次进验证，最终 **训练 60 / 验证 60 / 测试 30（合计 150 张）**。
- 图片统一由导入流程转为 RGB PNG；训练输入缩放到 96×96。

## 3. 复现方式

```powershell
# 首次运行会联网下载 Fashion-MNIST 到 artifacts/datasets（约 30 MB）
.\.venv\Scripts\python.exe scripts\real_data_validation.py
```

脚本按顺序执行：

1. 抽取子集到 `artifacts/real-data/sources/`
2. `backend.project create` 建项目，`import` 逐类逐批导入训练/测试图片
3. `check-dataset` 训练前检查
4. `backend.runtime.worker train`（10 轮、96×96、批量 16、真实 MobileNetV3-Small 权重）
5. `publish_training`：登记训练产物 → 导出 ONNX 模型包 → 切换当前模型
6. `load_training_report`：读取并校验训练报告
7. `backend.runtime.worker predict`：用导出包预测一张测试图片
8. `verify_project`：项目引用与摘要校验

结果写入 `artifacts/real-data/result.json`（含来源摘要、检查结果、训练消息、报告、预测与项目状态）。

## 4. 本机结果（2026-11-17）

补充：该 150 张子集**不满足**严格验收策略（每类 30 训练 / 8 验证 / 10 测试）。以 `check-dataset --require-test --min-train 30 --min-val 8 --min-test 10` 会返回 `DATASET_CLASS_TOO_FEW_SAMPLES`（每类仅 20 训练/20 验证/10 测试），属预期行为；本验证只证明真实图片链路可用，不作为验收数据规模依据。

| 指标 | 结果 |
| --- | --- |
| 数据检查 | 通过（0 个问题） |
| 训练 | 成功；10 轮，最佳轮次 10 |
| 验证准确率 | **0.9167**（55/60） |
| 验证损失 | 0.3166 |
| 每类召回 | T恤 0.75、裤子 1.0、外套 1.0 |
| 混淆矩阵（行=真实，列=预测） | `[[15,1,4],[0,20,0],[0,0,20]]` |
| 训练耗时 | 特征提取 0.55 s + 分类头 0.068 s = 0.73 s |
| 导出 | `art-run-real-0001`，模型包在项目 `exports/` 下 |
| 预测 | 成功；测试样本 Top-1 概率 0.838（T恤） |
| 项目校验 | `verify_project` 通过，当前模型指向导出包 |

训练进度消息包含 `accepted → load → feature_extraction(0..120) → head_training(1..10) → publish`，与任务协议一致。

## 5. 环境

- Windows 11（10.0.26200）、Intel 64 CPU、10 物理核
- Python 3.12.1；torch 2.8.0+cpu、torchvision 0.23.0+cpu、onnxruntime 1.23.2、Pillow 11.3.0
- 预训练权重：MobileNetV3-Small（见 [configs/weights.v1.json](../configs/weights.v1.json)）

## 6. 限制与未验证

- 子集很小（150 张）且只训练 10 轮，准确率不代表课堂真实数据表现；未做超参搜索与多种子重复。
- 仅 3 类、单次运行；未覆盖类别不平衡、模糊图片、错误标签等课堂问题。
- 数据为公开商品图片，不是学生采集的课堂数据；采集流程与摄像头未验证。
- 仅本开发机；未在目标 Windows 机器、断网环境或离线 ZIP 中复验。
- 数据集按 MIT 许可使用但**不随产品分发**；正式产品不内置该数据，仅保留此开发验证记录。
- 未验证板端部署与 K230/K210 转换。

## 7. 结论

真实图片可以走通现有完整链路：导入与数据检查、按项目类别训练、自动发布模型包、报告与预测、项目校验均通过。该结果支持“真实数据可用”的方向判断，但正式验收仍需目标机器 + 课堂数据 + 断网环境。

## 8. 课堂演练与时间预算（2026-11-18）

下表以 **2026-11-20 最新复测**（`artifacts/classroom-rehearsal/result.json`，生成时间 2026-11-20 03:26）为准，并列出 2026-11-19（修正训练阶段判定后）与早前 2026-11-18 的记录作对比；单机耗时随系统负载波动，具体数字以 `result.json` 为准：

| 阶段 | 方式 | 2026-11-20 复测（最新） | 2026-11-19 复测 | 早前（2026-11-18） |
| --- | --- | --- | --- | --- |
| 创建项目 | 3 类 | 0.34 s | 0.21 s | 0.23 s |
| 批量导入（训练） | `import-tree`，3 类 × 2 批 × 20 张 | 1.14 s | 1.31 s | 1.15 s |
| 批量导入（测试） | `import-tree --split test`，3 类 × 10 张 | 1.22 s | 0.98 s | 1.29 s |
| 数据检查 | `check-dataset` | 0.56 s | 0.55 s | 0.60 s |
| 训练 | 20 轮、96×96、batch 16（CPU） | 6.21 s（整段墙钟；内部计时 1.087 s） | 3.50 s（整段墙钟；内部计时 0.339 s） | 3.28 s |
| 发布（导出 ONNX） | `publish-training` | 3.56 s | 3.28 s | 3.21 s |
| 训练报告 | 重新加载模型并计算 | 2.94 s | 2.74 s | 2.80 s |
| 逐张预测 | 30 张测试图 | 17.03 s（中位 0.569 s/张） | 16.96 s（中位 0.569 s/张） | 15.58 s（中位约 0.51 s/张） |
| **合计（不含逐张预测）** | | **约 16.0 s** | 约 12.6 s | 约 12.6 s |
| **合计（含 30 张预测）** | | **约 33.0 s** | 约 29.5 s | 约 28.1 s |

2026-11-20 复测训练结果与 3 类基线接近：验证准确率 0.917、loss 0.248、best epoch 20/20。按此单机数据，课堂 40 分钟内完成“建项目 → 导入 → 检查 → 训练 → 发布 → 逐张预测”在时间上可行；但该数据为公开商品图、非学生采集，且未含摄像头采集时间，不能替代课堂时间预算验收（**A14 仍为“部分”**）。

2026-11-20 复测阶段合计约 16.0 s（`stage_seconds_total` = 15.977 s），含 30 张预测约 33.0 s（合计 33.006 s）；数字随负载波动，以 `artifacts/classroom-rehearsal/result.json` 为准。早前（2026-11-18）约 12.6 s / 28.1 s，2026-11-19 修正后复测约 12.6 s / 29.5 s（阶段合计 / 含 30 张预测）。

口径说明：`stage_seconds_total` = 15.977 s（2026-11-20 复测），是创建项目、两次批量导入、数据检查、训练、发布、训练报告 7 段子进程耗时之和，不含逐张预测；逐张预测为 30 次独立子进程调用（合计 17.029 s，中位 0.569 s/张），单张耗时主要来自 Python 启动、产物校验与模型加载（本机冷启动预测约 0.63–0.67 s，见[性能记录](performance-m0.md)），不等于预热后的单图推理延迟（约 3.5 ms）；两者相加即含预测合计约 33.0 s。“训练”阶段 6.21 s 是整段子进程耗时（含启动、权重加载与特征提取），该次运行 `result.json` 记录训练内部计时 1.087 s；2026-11-19 复测对应“训练”阶段 3.50 s、内部总计 0.3393 s（项目 `runs/rehearsal-0001/metrics.json` 的 `timings_seconds`）。

波动说明：单机耗时受系统负载影响较大。2026-11-19 10:56 另有一次性重跑（系统同时在跑其他任务）记录阶段合计 16.4 s、30 张预测 20.7 s（约 37.1 s），明显高于当日 09:05 复测；2026-11-20 03:26 最新复测阶段合计 16.0 s、30 张预测 17.0 s（约 33.0 s，已并入上表）。课堂时间预算仍应以目标机实测为准。

记录说明：此前该演练脚本把训练阶段成功与否取为 worker 结果信封顶层 `ok`（该信封没有此字段），导致真实成功的训练被记录为 `ok:false`、`train_seconds:0`。现已在 `scripts/classroom_rehearsal.py` 中改为“退出码 + `message_type=result` + payload 非空”判定，并从 `runs/<run_id>/metrics.json` 读取训练内部计时；修正后复测“训练”阶段 `ok:true`、`train_seconds=0.339`。

界面路径补充测量（`scripts/ui_flow.ps1 -TrainPredict -Epochs 20`，真实数据 120 张训练图）：训练并发布 **9.3 s**、单图预测 **0.8 s**（含界面轮询开销）。
