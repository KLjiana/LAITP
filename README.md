> 注意：不要直接双击 `desktop/src/.../bin/.../Laitp.Desktop.exe`——那是**开发构建**（框架依赖），未安装 .NET Desktop Runtime 时会提示运行时缺失。演示与交付请用 `dist/` 下的离线包（包内桌面为自包含发布，解压后运行 `start-desktop.bat`），或 `dist/desktop-selfcontained/Laitp.Desktop.exe`。

# LAITP 离线 AI 教学平台

面向中小学的离线 AI 教学平台：学生在 Windows x64 电脑上采集和检查图片、训练小模型、用新样本测试并分析误判，适配的模型再部署到 K230 / K210 开发板。目标形态是**解压双击、免注册、断网可用**——桌面端为 WPF（C# / XAML），AI 后端为内置 Python 子进程；设计前提是离线包自带便携 Python 与自包含 .NET 运行时，目标机无需预装 Python 或 .NET（目标机尚未验收）。

当前实现范围：

- **图像分类（M0–M2）**：本机开发环境完成实现与验证，包括模型契约校验、CPU 训练、ONNX 导出与模型包、推理/批量预测/模型对比、项目保存恢复、WPF 主流程、离线分发与包内自检。
- **检测、板端与扩展实验（M3–M5）**：只有规划、契约草案、Schema 草案与决策建议稿，**未实现**，不能当作可用能力。
- 模型与进程通信遵守**模型契约 1.0**（分类链路），详见[模型接口与产物契约](docs/model-contract.md)。

> 本文只是仓库入口，不重复易过期细节：验证结论以[项目状态报告](docs/status-report.md)与[验证证据索引](docs/verification-evidence.md)为准，分发包 SHA-256 / 体积以[离线分发包](docs/offline-bundle.md)为准。**开发机证据不等于目标机验收通过**，验收判定见[目标机离线验收清单](docs/acceptance-checklist.md)。

## 快速开始（开发机）

以下命令均在仓库根目录执行。

### 环境准备

前提：Windows x64、Python 3.12（`pyproject.toml` 要求 `>=3.12`）、.NET SDK 8（本仓库开发环境使用 `.dotnet\` 下的 8.0.428）。

仓库工作目录中的本地环境（均被 `.gitignore` 忽略）：

- `.venv\Scripts\python.exe`：Python 开发环境；
- `.dotnet\dotnet.exe`：构建 WPF 桌面所需的 .NET SDK；
- `vendor\wheels\`：离线 wheel（可选用）。

若 `.venv` 不存在，在仓库根目录重建（没有 `py` 启动器时改用已安装的 `python`）：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

`requirements-dev.txt` 引用 `requirements.txt`：前者含 pytest、psutil 等开发/测试依赖；后者记录运行依赖（torch 2.8.0+cpu、torchvision、onnxruntime、onnx、pillow、jsonschema，torch 走 CPU 源）。受控或离线环境已有 `vendor\wheels` 时，可改用离线安装：

```powershell
.\.venv\Scripts\python.exe -m pip install --no-index --find-links vendor\wheels -r requirements-dev.txt
```

### 桌面构建与测试

```powershell
# 构建 WPF 桌面（desktop/Laitp.sln）
.\.dotnet\dotnet.exe build desktop\Laitp.sln

# Python 后端 / 契约 / 工具链测试
.\.venv\Scripts\python.exe -m pytest -q

# .NET Core 契约与项目检查
.\.dotnet\dotnet.exe run --project desktop\tests\Laitp.Core.Checks -v quiet
```

### 日常快速验证

```powershell
.\.venv\Scripts\python.exe scripts\verify_all.py --quick
```

快速模式 6 个步骤（约 1–2 分钟）：Python 单元测试、桌面构建、Core 检查、验收证据汇总、文档一致性、交付状态自检。结果写入 `artifacts/verify-quick/verify-quick.json` 与 `.txt`。日常小步改动优先用它。

### 完整 / 阶段验证

```powershell
# 完整本机验证：默认 16 步（约 10 分钟，含离线包校验、净环境流程、课堂演练与界面自动化）
.\.venv\Scripts\python.exe scripts\verify_all.py --ui
```

发布或打包后，还应在解压的离线包内执行“包内一键验收”（见下一节）。`--ui` 与包内验收都只是**开发机 / 解压环境证据**；是否通过以实际输出及[验证证据索引](docs/verification-evidence.md)、[项目状态报告](docs/status-report.md)为准，本文不声称已通过。

> 摄像头自动化测试自 2026-11-18 起按要求停止；默认步骤不含摄像头，不要按旧文档再运行 `--camera`。

## 离线分发包（教师 / 目标机）

`dist\handoff\` 是交接目录（由 `scripts\make_handoff.py` 生成，`dist/` 被 `.gitignore` 忽略）：

- `laitp-offline-lean.zip`：**精简包**（内置便携 Python + 自包含桌面，不含 wheel，依赖已在包内）；
- `laitp-offline-full.zip`：**完整包**（额外包含 wheel，用于目标机首次部署或依赖修复）；
- 两个包的 `.sha256`、`README.md`、`teacher-quickstart.md`、`acceptance-card.md`、`acceptance-checklist.md`、`verification-evidence.md`、`known-limitations.md`、`acceptance-report-sample.md`、`交接说明.txt`、`handoff-manifest.json`。

使用流程（教师 / 目标机）：

1. 将 `laitp-offline-lean.zip` 解压到本机磁盘（可用中文 / 空格路径；不要放在只读目录、U 盘或网络共享盘）。
2. 双击包内的 `start-desktop.bat` 启动。首次启动会自动自检，状态栏显示“就绪（环境自检通过）”后即可使用。
3. 双击 `check-bundle.bat` 做包内自检（清单摘要、推理、训练报告、桌面启动与首次自检）。
4. 在解压目录内执行包内一键验收（11 个环节，约 5–6 分钟，实际耗时随机器变化）：

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\run_acceptance.ps1 -IncludeFlow -IncludeExtended
   ```

   脚本生成 `acceptance-run.json` 与 `acceptance-report.md`。**是否通过以实际输出与验证证据为准，不要预先写成“已通过”。**

5. 目标机首次部署或依赖修复使用完整包 `laitp-offline-full.zip`（含 wheel）；日常课堂分发用精简包。

分发前请阅读 `dist\handoff\交接说明.txt` 与[老师快速上手](docs/teacher-quickstart.md)；目标机逐项验收按[目标机离线验收清单](docs/acceptance-checklist.md)执行。**分发包版本、体积与 SHA-256 会变化，统一以[离线分发包](docs/offline-bundle.md)及同名 `.sha256` 文件为准，本文不写具体值。**

## 仓库结构

- `backend/`：Python 后端。`contracts/` 契约校验与稳定错误码，`classification/` 训练 / 导出 / 报告，`runtime/` 推理、批量预测、模型对比与行 JSON 协议，`project/` 项目文件格式与校验。
- `desktop/`：WPF 桌面（`Laitp.sln`）。`src/Laitp.Core` 核心逻辑、`src/Laitp.Desktop` 界面、`tests/Laitp.Core.Checks` Core 检查、`tests/Laitp.CameraChecks` 摄像头检查。
- `schemas/`：JSON Schema（模型清单、数据集清单、项目、消息信封）；`detection/` 为**未激活**的检测草案，不改变契约 1.0。
- `scripts/`：构建与打包（便携 Python、离线包、交接目录）、验证（`verify_all.py`、`check_docs.py`、`check_state.py`）、界面自动化、数据体检、项目归档等。
- `tests/`：pytest 测试与固定样本（`fixtures/`）。
- `docs/`：路线、契约、验收、分领域说明与交接文档（见下方索引）。
- `dist/`：本地构建产物（离线包、交接目录；被 `.gitignore` 忽略）。
- `benchmarks/`：M0 性能基准（训练、导出、延迟、内存）。
- `configs/`：验收配置（`acceptance.v1.json`，尚未冻结）、数据集来源（`datasets.v1.json`）与预训练权重版本 / 摘要（`weights.v1.json`）。
- 其它本地目录：`.dotnet/`（.NET SDK）、`.venv/`、`.venv-offline/`（Python 环境）、`vendor/`（离线 wheel）、`artifacts/`（验证输出与截图），均被 `.gitignore` 忽略。

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [总体路线与项目大纲](docs/roadmap.md) | 产品目标、功能范围、里程碑与验收要求；规划中的功能不得视为已实现 |
| [仓库开发约定](AGENTS.md) | 契约、离线、路径与验证的强制约定（贡献前必读） |
| [模型接口与产物契约](docs/model-contract.md) | 模型清单 / 标签 / 张量 / 运行时规则与版本兼容，契约 1.0 为强制约束 |
| [项目状态报告](docs/status-report.md) | 已实现能力、本机验证证据、外部阻塞与未验收项 |
| [验证证据索引](docs/verification-evidence.md) | 可复现命令、产物路径、截图与按改动范围选择验证方式 |
| [已知限制与验收边界](docs/known-limitations.md) | 集中说明证据边界、摄像头、离线/长路径、性能、检测草案与数据限制 |
| [目标机验收操作卡](docs/acceptance-card.md) | 一页版现场步骤：准备、自检、11 环节一键验收、记录表与常见失败速查 |
| [目标机离线验收清单](docs/acceptance-checklist.md) | A1–A15 验收项、记录模板与判定规则 |
| [离线分发包](docs/offline-bundle.md) | 构建 / 校验命令、包内容、SHA-256 与体积、限制（易过期数值以本文为准） |
| [老师快速上手](docs/teacher-quickstart.md) | 教师视角的建项目 → 采集 → 检查 → 训练 → 预测与常见问题 |
| [变更记录](docs/changelog.md) | 按 M0–M5 里程碑汇总已交付内容、验证程度与草案边界 |
| [检测课可行性规划](docs/detection-feasibility.md) | M3 检测课的范围、门槛与任务拆分（规划，未实现） |
| [检测契约与标注/结果格式草案](docs/detection-contract-draft.md) | 检测契约扩展与标注 / 结果格式候选文本（草案，未激活） |
| [检测待决问题决策建议](docs/detection-decisions.md) | Q1–Q8 决策建议稿（未决策，检测未实现） |

接手建议阅读顺序：先读本页与[项目状态报告](docs/status-report.md)，再按需查[总体路线与项目大纲](docs/roadmap.md)、[验证证据索引](docs/verification-evidence.md)、[目标机离线验收清单](docs/acceptance-checklist.md)、[离线分发包](docs/offline-bundle.md)与[仓库开发约定](AGENTS.md)。

## 当前状态与限制

以[项目状态报告](docs/status-report.md)为准，关键边界摘录如下：

- **已实现**：图像分类链路，包括契约校验、数据清单、CPU 训练、ONNX 导出与模型包、推理 / 批量预测 / 模型对比、项目保存恢复、WPF 主流程、离线包与包内自检。M0–M2 的成果与验证证据均来自**开发机**。
- **未验收**（不得写成已通过）：
  - 干净 Windows 目标机上的“解压双击”全流程；
  - 普通用户（非管理员）权限；
  - 真正断网环境（现有净环境只是清空 PATH / Python 变量并指向不可用代理的模拟）；
  - 课堂真实图片数据（现有效果数字来自公开 Fashion-MNIST 子集）；
  - 物理摄像头（此前仅用 DroidCam 虚拟摄像头验证，物理设备被禁用，真实摄像头待人工验证）；
  - K230 / K210 板端部署（未开始，缺硬件与转换工具链）。
- **摄像头自动化测试**：自 2026-11-18 起按要求停止；此前摄像头结论仅作历史记录。
- **检测未实现**：M3 检测的标注、训练、导出、电脑测试、转换与板端运行均未实现；相关文档是规划 / 草案 / 建议稿，当前校验器仍拒绝检测任务。
- 开发机证据不等于端到端可用；没有证据时不声称通过。本机验收汇总与逐项证据见[项目状态报告](docs/status-report.md)与[验证证据索引](docs/verification-evidence.md)。

## 贡献与约定

新增功能或文档前先读[仓库开发约定](AGENTS.md)，要点：

- **契约强制**：涉及训练、推理、模型导出、进程通信、项目模型记录或板端部署前，先读[模型接口与产物契约](docs/model-contract.md)。交付完整模型产物包，校验不通过不得标记可用；契约变更必须同步文档、Schema、生产方、消费方与验证，并按契约规则升版。
- **离线优先**：项目和产物使用可移植相对路径，运行时不依赖开发机绝对路径或隐式下载；新增依赖、权重或工具时记录版本、离线获取与分发要求。
- **验证要求**：模型与通信链路改动要运行相关有效验证，并覆盖适合的拒绝错误输入场景（如标签错位、摘要不符、版本不兼容、迟到结果）；Linux 后端检查不能替代 Windows WPF、摄像头与离线分发验收；汇报实际改动、已执行 / 跳过 / 未执行检查及平台限制，不夸大结论。
- **文档改动**：检查链接、示例与规则一致性；规划与草案内容必须标注状态，不得写成已实现。

---

本文只作为仓库入口与现状说明，不改变任何实现或验收状态；具体数字（分发包 SHA-256 / 体积、测试数、验证步数等）以链接文档和实际运行输出为准。
