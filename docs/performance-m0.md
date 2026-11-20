# M0 本机性能与离线验证记录（T08）

编制日期：2026-11-17

状态：已在**本开发机**完成性能测量、离线依赖安装与离线链路运行；目标 Windows 机器、课堂时间预算和真实课堂数据仍未提供，因此目标机断网验收与课堂性能判定**未执行**。
本文数字只描述本机与构造数据，不能作为课堂性能或真实分类效果的证据。

所属计划：[M0-01 分类最小闭环](m0-01-classification-plan.md)。相关文档：[数据与运行基线](data-and-runtime-baseline.md)、[独立推理说明](runtime-inference.md)、[任务协议](task-protocol.md)。

## 1. 测量方法

基准脚本：[benchmarks/m0_benchmark.py](../benchmarks/m0_benchmark.py)。单次运行完成：

```text
生成构造数据 → 建数据清单 → 加载本地权重训练 → 导出 ONNX 包 → 契约校验
→ 加载运行时 → 预热 + 30 次单图预测 → 冷启动子进程预测 → 子进程评估
```

```powershell
# 本机环境
.\.venv\Scripts\python.exe -m benchmarks.m0_benchmark --output artifacts\benchmark-m0

# 仅用本地轮子创建的离线环境
.\.venv-offline\Scripts\python.exe -m benchmarks.m0_benchmark --output artifacts\benchmark-m0-offline
```

参数：3 类、224×224、每类 3 个采集批次 × 10 张开发图片、每类 5 张测试图片、3 轮训练、批量 16、8 线程、30 次延迟测量、预热 3 次。
训练/验证按采集批次划分（60 张训练、30 张验证），测试集不参与训练。

## 2. 环境

| 项目 | 值 |
| --- | --- |
| 操作系统 | Windows 11（10.0.26200） |
| CPU | Intel64 Family 6 Model 154 Stepping 3（10 物理核 / 16 逻辑核） |
| 内存 | 15.8 GB |
| Python | 3.12.1 |
| torch / torchvision | 2.8.0+cpu / 0.23.0+cpu |
| onnxruntime / onnx | 1.23.2 / 1.19.1 |
| Pillow / jsonschema | 11.3.0 / 4.25.1 |

这是开发机配置，不是[路线图](roadmap.md)要求选定的最低目标机房电脑；目标机尚未确定。

## 3. 数据集

| 项目 | 值 |
| --- | --- |
| 类别 | 3（水杯、书本、笔袋） |
| 训练 / 验证 / 测试 | 60 / 30 / 15 |
| 输入尺寸 | 224×224，RGB |
| 图片体积 | 15,873,380 字节（约 15.1 MiB） |
| 数据来源 | Pillow 生成的随机噪声图片，**不是真实课堂数据** |

## 4. 测量结果

### 4.1 训练、导出与校验

| 指标 | 本机在线环境 | 本机离线环境（仅本地轮子） |
| --- | --- | --- |
| 构造数据生成 | 0.64 s | 0.71 s |
| 数据清单构建 + 校验 | 计入训练前准备 | 同左 |
| 训练总计（含特征提取） | 1.13 s | 1.12 s |
| 其中特征提取（90 张） | 0.51 s | 0.49 s |
| 其中分类头训练（3 轮） | 0.013 s | 0.016 s |
| ONNX 导出 + 固定样本比对 | 0.80 s | 0.70 s |
| 产物包契约校验 | 0.043 s | 0.043 s |
| 运行时加载（校验后加载会话） | 0.033 s | 0.036 s |
| 冷启动预测（新进程：导入 + 校验 + 首图） | 0.63 s | 0.67 s |
| 冷启动评估（新进程，15 张测试图） | 0.95 s | 0.98 s |

### 4.2 单图延迟（224×224，预热后 30 次）

| 指标 | 本机在线环境 | 本机离线环境 |
| --- | --- | --- |
| 最小 | 3.09 ms | 2.89 ms |
| 中位数 | 3.58 ms | 3.62 ms |
| P95 | 4.43 ms | 4.55 ms |
| 最大 | 4.66 ms | 4.64 ms |

延迟口径包含图片解码、缩放、归一化与 ONNX Runtime 推理（`predict` 单图全流程），不含进程启动。

### 4.3 内存与体积

| 指标 | 值 |
| --- | --- |
| 训练过程 RSS 峰值 | 约 422 MB |
| 模型包总大小 | 4,185,329 字节（约 3.99 MiB） |
| 其中 `model.onnx` | 3,724,130 字节（约 3.55 MiB） |

### 4.4 2026-11-18 复测（当前代码）

重新运行 `benchmarks/m0_benchmark.py`（在线环境与由 `vendor/wheels` 重建的离线环境各一次）：

| 指标 | 在线环境 | 离线环境（仅本地轮子） |
| --- | --- | --- |
| 训练总计（含特征提取） | 0.86 s | 1.06 s |
| 其中特征提取（90 张） | 0.39 s | 0.47 s |
| 分类头训练（3 轮） | 0.014 s | 0.017 s |
| ONNX 导出 + 固定样本比对 | 0.68 s | 0.71 s |
| 冷启动预测（新进程） | 0.63 s | 0.61 s |
| 单图延迟中位数 / P95 | 3.50 / 4.24 ms | 4.20 / 5.05 ms |
| 训练 RSS 峰值 | 422.4 MB | 428.4 MB |
| 验证集准确率 | 0.367 | 0.367 |

与 4.1/4.2 的历史值相比在正常波动范围内（训练 0.86–1.13 s、延迟中位 3.5–4.2 ms）；离线环境由 33 个本地轮子重建后同样完成安装与运行。

### 4.5 一致性与效果

| 指标 | 值 |
| --- | --- |
| 固定样本数 | 3 |
| 最大绝对输出差异 | 4.5×10⁻⁷ |
| 转换记录状态 | passed |
| 验证集准确率 | 0.367 |

构造噪声图片没有可学习信号，0.367 只说明训练与评估链路可运行，**不能代表真实分类效果**。正式效果目标和课堂性能阈值仍未在 `configs/acceptance.v1.json` 中冻结。

## 5. 离线验证

1. 用 `pip download -r requirements-dev.txt -d vendor\wheels` 下载全部直接与传递依赖：**33 个轮子，684,589,564 字节**；本地生成 `vendor\wheels.sha256`（未提交，需随离线包保存）。
2. 新建 `.venv-offline`，在 `--no-index --find-links vendor\wheels` 下安装成功，版本与在线环境一致（torch 2.8.0+cpu、onnxruntime 1.23.2 等）。
3. 在 `.venv-offline` 中执行完整测试：**374 passed**；再执行本基准脚本：结果与在线环境接近（见 4.1～4.4）。
4. 运行期间设置 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY` 指向不可用地址，安装与运行均未请求网络。

训练、导出、加载和预测只读取本地模型包、数据清单、权重文件和已安装依赖；权重按 SHA-256 校验，缺失或摘要不符时立即失败，不自动下载。

限制：本次没有禁用网络适配器或防火墙，代理设置只能发现部分隐式联网；**真正的断网环境需在目标 Windows 机器上重复本流程**。干净机器解压即用、ZIP 分发与首次运行缓存也尚未验证。

## 6. 解释与限制

- 本机为开发机，CPU/内存/系统与目标机房电脑不同；以上数字不代表课堂电脑表现。
- 数据为构造噪声图片，训练时间与效果都不代表真实采集数据；真实数据涉及解码、样本量与标注质量。
- 训练成本主要由冻结特征提取器的一次性前向决定：本机 90 张约 0.5 s，分类头训练可忽略；30 轮训练相对 3 轮只增加数十毫秒。该结论仅适用于本机与 224×224 输入。
- 冷启动约 0.6～0.7 s，包含 Python 导入、契约校验与首图推理；WPF 内嵌场景的冷启动与预热策略未验证。
- 未测物理摄像头采集、多摄像头并发与课堂长时间运行；DroidCam 虚拟摄像头的采集、预览与 60 秒稳定性见第 8 节。
- 未在 K230/K210 上做任何部署或性能测量。
- 目标机、课堂时间预算与真实数据确定后，需在 `configs/acceptance.v1.json` 中填写阈值并重新运行本基准；**不得在看到结果后放宽阈值**。

## 7. 复现

```powershell
# 1. 准备环境
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

# 2. 准备本地权重（摘要见 configs/weights.v1.json）
#    artifacts\weights\mobilenet_v3_small-047dcff4.pth

# 3. 本机基准
.\.venv\Scripts\python.exe -m benchmarks.m0_benchmark --output artifacts\benchmark-m0

# 4. 离线依赖（可选，首次需联网下载）
.\.venv\Scripts\python.exe -m pip download -r requirements-dev.txt -d vendor\wheels
py -3.12 -m venv .venv-offline
.\.venv-offline\Scripts\python.exe -m pip install --no-index --find-links vendor\wheels -r requirements-dev.txt
.\.venv-offline\Scripts\python.exe -m pytest
```

结果 JSON 默认写入 `artifacts/benchmark-m0/m0-benchmark.json`（`artifacts/` 不提交到仓库）。目标机验收时应保留原始 JSON、机器信息与运行日志。

## 8. 桌面与摄像头耗时（2026-11-18）

| 项目 | 测量 | 结果 |
| --- | --- | --- |
| 自包含桌面启动（开发机仓库） | `scripts/measure_startup.ps1` 对 `dist/desktop-selfcontained/Laitp.Desktop.exe` | 暖启动：窗口 1.72 s、自动自检完成 1.99 s（此前一次为窗口 2.63 s / 自检 2.90 s） |
| 解包目录启动（离线包，包内便携 Python） | 同一脚本加 `-LaitpHome/-LaitpPython` | **首次**：窗口 5.11 s；**暖启动**：窗口 0.83 s、自动自检完成 1.59 s |
| 摄像头单张拍照（DroidCam Video） | 界面“摄像头拍照”状态文本 | 0.27–0.73 s/张（19 KB PNG） |
| 摄像头连续预览（DroidCam Video） | 界面“开始/停止预览”状态文本 | **约 20–21 fps**（1280×720，8 秒约 160–170 帧；`MediaFrameReader` + JPEG 编码） |
| 摄像头设备检测 | 界面“检测/刷新” | “摄像头：DroidCam Video（1 个可用）”；设备下拉框存在 |
| 摄像头长时间预览（60 秒） | `scripts/ui_preview_stability.ps1 -Seconds 60` | 稳定 **20.9 fps / 1313 帧**；内存 264.5–272.4 MB（首末 −0.6 MB）、句柄约 1200，无增长或掉帧 |
| 界面路径训练（真实数据，20 轮） | `ui_flow.ps1 -TrainPredict -Epochs 20`（120 张训练图、3 类） | 训练并发布 **9.3 s**；单图预测 **0.8 s**（界面操作时间，含按钮/轮询开销） |
| 启动优化实验（ReadyToRun） | 自包含发布加 `-p:PublishReadyToRun=true`，各 3 次暖启动 | 中位窗口 0.84 s / 自检 1.10 s，与基线 0.84 s / 1.12 s 无实质差异；发布体积 226.4 MB vs 193.4 MB（+33 MB）→ **不采用** |

上述为开发机测量；首次启动含系统组件初始化，暖启动反映后续课堂使用。未含目标机冷启动、杀毒软件与课堂并发影响。ReadyToRun 实验说明当前启动瓶颈不在 JIT；后续如需优化应拆解首次启动（WinRT/WPF 组件初始化）而不是加体积。

## 9. 结论

- M0-01 的 T01～T07 已实现并通过本机测试；本机性能与离线依赖链路已完成测量。
- T08 的**目标 Windows 机器断网运行、课堂时间预算和真实数据验收未执行**；据此不能宣布 M0 或 M0-01 完成。
- 下一步仍依赖外部条件：确定目标机器与课堂预算（路线图第 10 节第 1 项）、采集真实数据，并在目标机重复本基准与离线流程。
