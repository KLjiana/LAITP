# 项目状态报告（开发期）

本报告汇总当前实现、验证证据与外部阻塞项，用于交接与验收准备。**不构成验收结论**：目标机器、真正断网、普通用户权限、摄像头采集、课堂真实数据与板端部署仍未完成。

最后更新：2026-11-26。

## 1. 已实现能力（按路线图任务）

| 范围 | 内容 | 状态 |
| --- | --- | --- |
| T01/T02 | 模型清单 Schema、标签/张量/路径校验、稳定错误码、统一验证报告 | 已实现并有测试 |
| T03 | 数据集清单、批次划分、类别/批次约束、数据检查策略 | 已实现并有测试 |
| T04 | MobileNetV3-Small 冻结特征 + 线性头训练（torch CPU） | 已实现并有测试 |
| T05 | ONNX 导出、模型包、SHA-256 清单与完整性校验 | 已实现并有测试 |
| T06 | 电脑端加载/预测/训练报告 | 已实现并有测试 |
| T07 | 行 JSON 信封协议、worker/supervisor、进度、取消、超时 | 已实现并有测试 |
| T08 | 本地性能基准、离线 wheel、便携 Python、离线分发包 | 已实现（目标机未验收） |
| M1 | WPF 界面：建项目、导入（逐批/批量/测试集）、数据检查（含严格验收）、训练并发布、预测、样本与类别编辑、训练历史与重新导出、误判样本、环境自检、保存恢复 | 已实现并界面自动化验证 |
| M2 | 离线分发：自包含桌面 + 便携 Python + 启动脚本 + 清单校验 + 首启自检 | 已实现（干净机器/断网未验收） |

部分完成或受阻：摄像头采集（物理设备被禁用，A11 仍为部分完成）、课堂真实数据采集、K230/K210 板端转换与部署。

A1–A15 的逐项状态、证据与剩余动作（本机待做/目标机待做/硬件阻塞）见[验收清单 §8 当前状态矩阵](acceptance-checklist.md#8-当前状态矩阵截至-2026-11-23)；状态以 `artifacts/acceptance-local.json` 为准，本报告不逐项重复。

## 2. 验证证据（本机，2026-11-18/19/20/23/26）

| 验证 | 命令 | 结果 |
| --- | --- | --- |
| Python 单元测试 | `.venv\Scripts\python.exe -m pytest -q` | **496 passed** |
| 桌面构建 | `.dotnet\dotnet.exe build desktop\Laitp.sln` | 0 警告 0 错误 |
| Core 检查 | `.dotnet\dotnet.exe run --project desktop\tests\Laitp.Core.Checks` | **64 项通过** |
| 一键验证 | `.venv\Scripts\python.exe scripts\verify_all.py --ui` | **16 步通过（摄像头步骤按要求跳过）**（约 10 分钟，`artifacts/verify-all/verify-all.json`） |
| 真实数据 | `scripts/real_data_validation.py` | Fashion-MNIST 3 类子集，验证准确率 0.917 |
| 课堂演练 | `scripts/classroom_rehearsal.py` | 阶段合计约 16.0 s；含 30 张预测约 33.0 s（2026-11-20 复测；单机，数字随负载波动，以 `artifacts/classroom-rehearsal/result.json` 为准）；早前 2026-11-19 约 12.6 s / 29.5 s、2026-11-18 约 12.6 s / 28.1 s；界面路径 20 轮训练+发布 9.3 s、单图预测 0.8 s（含界面轮询开销）；训练阶段 `ok:true`、内部计时 1.087 s，详见[真实数据验证](real-data-validation.md#8-课堂演练与时间预算2026-11-18) |
| T08 基准（复测） | `benchmarks/m0_benchmark.py` | 训练 0.86 s、单图中位 3.50 ms、冷启动预测 0.63 s、RSS 422 MB；离线环境（33 轮子重建）同样通过 |
| 摄像头拍照 | `scripts/ui_camera.ps1`（DroidCam） | 检测到 1 个设备；4 次拍照导入成功（约 19 KB/张，0.27–0.73 s/张）；预览实测约 21 fps、停止正常；连拍 3 张成功 |
| 长时间预览 | `scripts/ui_preview_stability.ps1 -Seconds 60` | 60 秒稳定 20.9 fps（1313 帧），内存 264.5–272.4 MB、句柄约 1200，无增长/掉帧 |
| 净环境界面 | `ui_flow.ps1 -CleanEnv` / `ui_camera.ps1 -CleanEnv` | 最小 PATH（无 Python/.NET）、清除 PYTHON*、不可用代理、包内 Python：打开→检查→训练→预测、设备→预览→连拍→拍照均通过 |
| 最近项目 | `ui_flow.ps1` / `-UseRecent` | 打开后写入 `%LOCALAPPDATA%\Laitp\recent-projects.json`；“打开最近”可恢复项目（UI 截图可见下拉框） |
| 批量预测 | `backend.runtime.batch` + `ui_flow.ps1 -BatchImagesDir` | 30 张真实测试图：准确率 86.7%（T恤 90%、裤子 70%、外套 100%），状态/各类准确率/误判列表显示正常；结果 CSV 与汇总 JSON 写入项目 `runs/`；后端另提供按批次准确率 `per_batch` |
| 模型对比 | `backend.runtime.compare`（CLI，含 `--csv`）+ 界面“模型对比” | 同一测试集对比两个模型包的准确率/一致率/分歧样本；7 项 pytest 覆盖；界面自动化实测 A 76.7% / B 90.0%、一致率 76.7%（30 张）；标签不一致时界面显示不可比警告；逐图对比 CSV 可导出 |
| 项目归档 | 界面“导出存档/从存档导入” + `ui_flow.ps1 -ArchiveDir` + `scripts/project_archive.py` | 4 项 Core 检查覆盖导出/往返/拒绝非空与危险归档；UI 自动化实测导出 284 条目 ZIP 并成功导入打开；导入后执行 `backend.project verify` 校验（失败不切换项目）；CLI 已在解压包内 33 文件往返验证 |
| 另存为 | `ui_flow.ps1 -SaveAsDir <dir>` | 复制项目目录并切换；状态“已另存为：…”，新目录含 project.json/data/exports/runs，数据检查通过 |
| 数据集体检 | `scripts/dataset_report.py`（CLI）+ 界面“数据体检/打开体检报告” | 每类每批次样本、重复/无效图片、尺寸分布与分级风险提示；输出 Markdown + 可选 CSV；4 项 pytest 覆盖；界面自动化实测 150 张样本并生成报告，报告可直接打开 |
| 项目校验 | 界面“校验项目” + `python -m backend.project verify --root <项目目录>` | 只读校验 project.json/Schema、数据清单类别、模型产物摘要；失败列出问题；CLI 正常/异常项目实测通过 |
| 验收证据汇总 | `scripts/acceptance_audit.py` | 生成 `artifacts/acceptance-local.json/md`：A1–A15 中已验证 9、部分 4、未执行 1（A10 课堂数据）、阻塞 1（A15 板端）；逐项矩阵见[验收清单 §8](acceptance-checklist.md#8-当前状态矩阵截至-2026-11-23) |
| 证据索引 | [验证证据索引](verification-evidence.md) | 汇总可复现命令、产物路径、截图与目标机留证建议 |
| M3 准备（规划） | [K230 板端可行性准备](k230-feasibility.md) | 前置条件、未知项、验证门槛与所需外部输入；**未实现、未验证** |
| 文档一致性 | `scripts/check_docs.py` | 核对包 SHA/体积/清单文件数、测试数、Core 数、验证步数、过期缩写 SHA、依赖版本与第三方许可说明一致，以及 Markdown 链接/锚点（本机通过） |
| 交付状态自检 | `scripts/check_state.py` | 11 项一致：包 SHA/体积、轻量 ZIP 结构、交接目录 SHA/文件、最近验证、验收汇总（含 A1–A15 覆盖）、长时间预览稳定性、文档一致性、交接验收报告样例、交接目录文档与仓库一致（README.md 与 teacher-quickstart/acceptance-card/acceptance-checklist/verification-evidence/known-limitations/third-party-notices 七份）（本机通过） |
| 包内一键验收（2026-11-26，正式包，11 环节） | 解压后 `run_acceptance.ps1 -IncludeFlow -IncludeExtended` | **11 个环节全部通过，未使用重试**（自检 23.2 s、窗口 10.2 s、启动 2.5 s、演示数据 0.2 s、新建导入 24.0 s、训练预测 29.0 s、保存恢复 47.0 s、数据体检 0.4 s、批量历史汇总 0.3 s、严格验收（正向）0.5 s、自检幂等性复核 33.7 s）；**中文+空格路径 + CP936 控制台**，非提权进程；包内含“目标机验收操作卡”“已知限制与验收边界”“第三方组件与许可说明”与 `docs/evidence/` K230 证据；三个界面脚本均有内部总超时（540/360/420 s）；报告含“包身份”、CPU/内存/磁盘余量、长路径支持与包目录长度；包内自检含开发机路径扫描与 manifest 环境一致性检查；CLI 脚本在英文 Windows 控制台（cp1252）下也可正常输出中文帮助；训练预测含界面批量预测（4 张/50.0%）与模型对比（A 50.0% / B 0.0%，标签不同出现不可比警告，属预期）；摄像头按要求未测试 |
| 控制台编码兼容（2026-11-19） | `chcp 936` 控制台运行一键验收 | 修复后同一临时包在 CP936 与默认环境均 **11/11 通过**（第 8/9/10 步 JSON 解析正常）；旧版在中文控制台会误报失败 |
| 周期复核（2026-11-18，摄像头关闭后） | `scripts/verify_all.py --ui` + `check_state.py` | **16 步通过**（摄像头步骤按用户要求跳过，不再运行 `--camera`）；状态自检通过（当时 10 项；当前 11 项） |
| 完整一键验证（2026-11-26 复验） | `.\\.venv\\Scripts\\python.exe scripts\\verify_all.py --ui` | **16 步通过（16 PASS + 1 SKIP：界面摄像头拍照导入按用户要求跳过；共 17 条记录）**，约 7 分钟；含 496 项 pytest（含 PowerShell 解析检查）、离线包校验（清单卫生/桌面自包含/启动脚本/check-bundle/开发机路径扫描）、净环境流程、课堂演练、界面闭环/归档/新建/批量/恢复/历史/严格验收；三个界面脚本均启用内部总超时看门狗，本轮无超时或重试 |
| 界面截图 | `ui_smoke.ps1 -Screenshot` / `ui_camera.ps1 -Screenshot` | 窗口截图（`artifacts/ui-screenshots/`）可见标题、摄像头行与状态；摄像头截图见 DroidCam 预览画面与“预览中（21.2 fps，178 帧）”、类别/拍照/连拍控件 |
| 启动耗时 | `scripts/measure_startup.ps1` | 自包含桌面暖启动窗口 1.72 s、自检完成 1.99 s；解包目录暖启动窗口 0.83 s、自检完成 1.59 s（首次窗口 5.11 s） |
| 离线包 | 精简包 `dist/laitp-offline-lean.zip` | 278,933,888 B，SHA-256 `fa7ab099…8daf404cd`；18,176 文件摘要匹配、推理/报告/桌面/自检/摄像头设备选择·拍照·连拍·高帧率预览均验证；包内自带现场自检脚本、`check-bundle.bat` 与老师快速上手文档 |
| 完整包 | `dist/laitp-offline-full.zip` | 950,154,614 B（约 906 MiB），SHA-256 `b5e92d75…bbe867a6fba`；18,210 文件（含 33 个 wheel）摘要匹配、包内 Python 导入/推理/报告/桌面启动/自检均通过 |

补充（2026-11-19）：包内一键验收已扩展为 11 环节，新增第 10 步“严格验收（正向）”与第 11 步“自检幂等性复核”（用包内 Python 对流程项目执行 `backend.project check-dataset --require-test --min-train/val/test`，验证严格验收正向链路；链路验证阈值，非课堂验收门槛）。上表 11 环节为当前状态；扩展前正式包曾实测 9/9 通过（2026-11-19，历史记录），扩展后 11 步正式包已实测 11/11 通过。

一键验证 16 步（默认）：单元测试、桌面构建、Core 检查、验收证据汇总、文档一致性、离线包校验、净环境离线流程、真实数据课堂演练、界面冒烟、界面闭环（打开→检查→训练→预测）、新建+导入、批量导入、保存+恢复、历史导出、界面另存为 + 最近项目、项目编辑+严格验收；`--camera` 开关可追加摄像头拍照导入（共 17 步），但摄像头自动化测试自 2026-11-18 起按要求停止，默认不再运行。

界面闭环与恢复/编辑等在**含中文与空格的解包目录**、使用**包内便携 Python** 下另行验证过（详见[离线分发包](offline-bundle.md)）。

## 3. 外部阻塞与未验收项

| 编号 | 项目 | 现状 |
| --- | --- | --- |
| A11 | 摄像头采集 | 物理 `HD Webcam` 状态 **Error，Code 22（设备已禁用）**（启用需管理员）；底层 WinRT 采集、**设备选择 / 检测刷新 / 拍照 / 连拍 / 高帧率预览**已用 `DroidCam Video` 验证：4 次拍照导入成功（约 19 KB/张，0.27–0.73 s/张），连拍 3 张（新增 1、重复 2），`MediaFrameReader` 预览实测 **约 20–21 fps** 且可正常停止；权限/占用/缺失等错误已映射为可读提示（Core 检查覆盖，真实设备未触发）。静态虚拟画面触发的重复内容校验也按预期拒绝；真实摄像头待验证，详见[摄像头能力](camera.md)。 |
| A10 | 课堂真实图片 | 未采集；仅有公开 Fashion-MNIST 子集验证 |
| A12 | 真正断网 | 仅用不可用代理模拟；未在断网机器验收 |
| A13 | 权限与路径 | 部分：中文+空格路径下“解压→自检→一键验收 11/11→再次自检”全部通过（2026-11-19，非提权进程，路径 54 字符）；普通用户与干净目标机仍待验证 |
| A14 | 课堂时间预算 | 已记录单机数据（2026-11-20 复测：阶段合计约 16.0 s、含 30 张预测约 33.0 s；数字随负载波动，以 `artifacts/classroom-rehearsal/result.json` 为准；早前 2026-11-19 约 12.6 s / 29.5 s、2026-11-18 约 12.6 s / 28.1 s），未含采集时间与课堂环境 |
| A15 | K230/K210 板端 | 未开始（需硬件与转换工具链） |
| — | 目标 Windows 机器 | 未在干净系统验证“解压双击”全流程 |
| — | 摄像头测试（按要求停止） | 2026-11-18 用户要求关闭摄像头并停止测试；后续本机验证不再运行 `--camera` 步骤（默认 16 步套件），摄像头相关结论保留上文历史记录，A11 仍为部分完成。 |

## 4. 复现方式

```powershell
# 环境准备（开发机）
.\.venv\Scripts\python.exe -m pytest -q
.\.dotnet\dotnet.exe build desktop\Laitp.sln
.\.dotnet\dotnet.exe run --project desktop\tests\Laitp.Core.Checks

# 一键验证（含离线包与界面自动化）
.\.venv\Scripts\python.exe scripts\verify_all.py --ui

# 单独构建/校验离线包
.\.venv\Scripts\python.exe scripts\build_portable_python.py
.\.dotnet\dotnet.exe publish desktop\src\Laitp.Desktop\Laitp.Desktop.csproj -c Release -r win-x64 --self-contained true -o dist\desktop-selfcontained
.\.venv\Scripts\python.exe scripts\build_offline_bundle.py --skip-wheels --desktop-dir dist\desktop-selfcontained --python-dir dist\python-portable --output dist\laitp-offline-lean.zip
.\.venv\Scripts\python.exe scripts\verify_offline_bundle.py --bundle dist\laitp-offline-lean.zip
```

目标机验收步骤见[目标机离线验收清单](acceptance-checklist.md)。

> 证据边界与已知限制集中见[已知限制与验收边界](known-limitations.md)。

## 5. 主要文件

- 路线图：[roadmap.md](roadmap.md)；契约：[model-contract.md](model-contract.md)
- 后端：`backend/contracts/`、`backend/classification/`、`backend/runtime/`、`backend/project/`
- 桌面：`desktop/src/Laitp.Core/`、`desktop/src/Laitp.Desktop/`、`desktop/tests/Laitp.Core.Checks/`
- 脚本：`scripts/`（离线包构建/校验、真实数据、课堂演练、一键验证、界面自动化）
- 入口：[README](../README.md)（项目总览与快速开始）
- 目标机操作卡：[验收操作卡](acceptance-card.md)（一页版）
- 文档：[离线分发包](offline-bundle.md)、[真实数据验证](real-data-validation.md)、[桌面程序](desktop-shell.md)、[项目格式](project-format.md)、[任务协议](task-protocol.md)、[性能](performance-m0.md)、[变更记录](changelog.md)、[检测课可行性规划](detection-feasibility.md)（规划，未实现）、[检测契约与格式草案](detection-contract-draft.md)（草案，未激活）、[检测决策建议](detection-decisions.md)（建议稿，未决策）、[剩余工作与解锁条件](remaining-work.md)（外部依赖与解锁清单，截至 2026-11-23；不表示未验证项已通过）

## 6. 后续优先项

1. 具备管理员权限的机器上启用物理摄像头后，验证真实摄像头采集（A11；界面采集已用 DroidCam 虚拟摄像头验证，自动化测试已停止）。
2. 干净 Windows 机器 + 断网 + 普通用户：按验收清单执行 A1–A9、A12、A13。
3. 课堂真实数据采集与时间预算（A10、A14），再补严格验收样本量。
4. K230/K210 转换与实机部署（A15）。
5. 检测课（M3）前置无硬件工作：按[检测课可行性规划](detection-feasibility.md) 的 P1–P5 推进（契约扩展草案、标注格式与合成数据验证），先决定 Q1/Q2/Q3/Q6/Q7。
