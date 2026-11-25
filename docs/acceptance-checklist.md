# 目标机离线验收清单

本清单用于在**目标 Windows 机器**（干净系统、普通用户、真正断网）上执行 M2 离线分发与课堂流程验收。当前仓库只有开发机证据，未执行本清单，不构成验收通过。

关联文档：[总体路线与项目大纲](roadmap.md)、[离线分发包](offline-bundle.md)、[验证证据索引](verification-evidence.md)、[真实公开数据验证](real-data-validation.md)、[桌面程序骨架](desktop-shell.md)、[模型接口与产物契约](model-contract.md)。

## 1. 环境与前置条件

- Windows x64 目标机；建议记录：系统版本、内存、磁盘、屏幕分辨率、是否域账号。
- 不预装 Python、不预装 .NET Desktop Runtime、无网络（断网卡/拔网线/防火墙全部阻断）。
- 普通用户账号（非管理员）运行；安装/解压目录包含中文与空格（如 `D:\课堂 软件\LAITP 离线包`）。
- 分发包：`dist/laitp-offline-lean.zip`（约 266 MiB，含包内 Python 与自包含桌面）或完整包 `laitp-offline-full.zip`（含 wheel，可修复依赖）。

## 2. 目标机验收准备清单（交给老师/管理员）

执行本清单前，请先准备并确认：

- **机器**：干净 Windows 10/11 x64，内存 ≥ 8 GB，解压盘 ≥ 2 GB 可用空间，屏幕 ≥ 1024×768。
- **账号**：用普通用户（非管理员）执行 A2–A12；如需启用物理摄像头、安装驱动，由管理员单独完成后再回到普通用户验收。
- **网络**：拔掉网线并关闭 Wi-Fi（或防火墙全部阻断），同时清除系统代理；验收期间不得联网。
- **数据**：每个类别准备 ≥ 30 张训练图片与 ≥ 10 张测试图片，按 `类别/批次/*.png` 组织；建议用 3 个类别。
- **时间**：预留 60–90 分钟；记录训练轮数、训练耗时、单图预测耗时与总流程耗时。
- **交付物**：离线 ZIP、SHA-256 校验值、本清单、包内 `docs/teacher-quickstart.md`。
- **留证**：每一步保留截图或日志；A1 保留 `check-bundle.bat` 输出，A7/A8 保留产物 ID 与 `verify-all.json` 等记录。

## 3. 本机一键验证

在开发机可先运行一键验证，覆盖单元测试、构建、Core 检查、离线包校验、净环境离线流程与界面自动化：

```powershell
.\.venv\Scripts\python.exe scripts\verify_all.py --ui
```

结果写入 `artifacts/verify-all/verify-all.json`（含每步状态与耗时）与 `verify-all.txt`。默认 16 步（含“验收证据汇总”）；摄像头自动化测试自 2026-11-18 起按要求停止，默认步骤不含摄像头，最近一次 **16 步通过（摄像头步骤按要求跳过）**（约 10 分钟）。

本机一键验证只代表开发机证据，不替代下列目标机验收项。摄像头拍照导入步骤需可用摄像头；相关自动化测试已于 2026-11-18 按要求停止，不再随一键验证执行。

本机验收证据汇总可重新生成：

```powershell
.\.venv\Scripts\python.exe scripts\acceptance_audit.py
```

输出 `artifacts/acceptance-local.json` 与 `acceptance-local.md`（对照 A1–A15 标注已验证/部分/未执行/阻塞，并引用现有证据文件）。最近一次汇总：**已验证 9 项、部分 4 项、未执行 1 项（A10）、阻塞 1 项（A15）**。逐项状态、证据与剩余动作见第 8 节当前状态矩阵。

## 4. 验收项

| 编号 | 检查项 | 操作 | 期望 | 当前状态 |
| --- | --- | --- | --- | --- |
| A1 | 包完整性 | 解压后运行 `scripts/verify_offline_bundle.py --bundle <zip>`，或包内双击 `check-bundle.bat` / `python\python.exe scripts\verify_offline_bundle.py --extracted .` | 全部文件 SHA-256 匹配；推理/报告/桌面/自检通过 | 开发机已验证（18,176 文件；含包内现场自检通过） |
| A2 | 解压与启动 | 双击 `start-desktop.bat` | 桌面窗口出现，状态栏“就绪（环境自检通过）” | 开发机 + UIAutomation 已验证；可用 `ui_smoke.ps1 -Screenshot` 留证（截图见 `artifacts/ui-screenshots/`）；目标机待执行 |
| A3 | 首次自检 | 点击“环境自检”，或运行 `desktop\app\Laitp.Desktop.exe --self-test self-test.json` | 4 项检查通过；缺 Python 场景能显示失败与提示 | 开发机正向/负向均验证；目标机待执行 |
| A4 | 新建项目 | 界面填写项目目录/名称/类别，点击“新建并打开” | 状态“已创建并打开项目”，类别显示正确 | 开发机 UIAutomation 已验证；目标机待执行 |
| A5 | 导入图片 | 逐类逐批导入（每类至少 2 个批次） | 状态“导入完成”，数据清单合计正确 | 开发机 UIAutomation 已验证；目标机待执行 |
| A6 | 检查数据 | 点击“检查数据”（勾选严格验收）；目标机一键验收将执行严格验收正向链路：第 10 步“严格验收（正向）”用包内 Python 对一键验收生成的流程项目运行 `backend.project check-dataset --require-test --min-train/val/test`，仅验证链路，所用阈值不作为课堂验收门槛 | “数据检查通过”；缺测试集/样本不足时给出明确错误 | 开发机已验证基础检查、严格验收拒绝路径（样本不足显示“数据检查未通过（3 个问题）”）与**正向通过路径**（真实子集 20/20/10 阈值，显示“严格验收检查通过”）；目标机待用每类 ≥30 训练 / ≥10 测试复验 |
| A7 | 训练与发布 | 设置轮数，点击“训练并发布” | 状态“训练与导出完成”，模型包路径自动填入 | 开发机 UIAutomation（1 轮）验证；目标机待执行并记录耗时 |
| A8 | 预测 | 选择课堂图片，点击“预测”；可选批量预测测试目录 | 状态“成功”，显示类别概率与产物 ID；批量预测显示准确率、误判与 CSV | 开发机 UIAutomation 验证（单图 + 批量，30 张准确率 86.7%、CSV 导出）；目标机待执行 |
| A9 | 项目保存恢复 | 关闭程序后重新打开项目 | 项目、类别、当前模型、训练历史均可恢复 | 开发机 UIAutomation 与解包目录（包内 Python）均已验证；目标机待执行 |
| A10 | 真实课堂图片 | 用真实课堂采集图片重跑 A5–A8 | 全流程可用；记录每类样本数、训练轮数、耗时与准确率 | **未执行**（需课堂数据） |
| A11 | 摄像头采集 | 打开摄像头采集并保存图片 | 画面预览、拍照、保存到类别目录 | **部分完成**：应用内“设备选择 / 检测刷新 / 拍照 / 连拍 / 开始-停止预览”已实现并在 `DroidCam Video` 验证（拍照 4 次成功，连拍 3 张，预览约 20–21 fps）；权限/占用/缺失错误已映射为提示。物理摄像头被禁用（Code 22）与真实摄像头待验证；界面截图见 `artifacts/ui-screenshots/`（含预览画面与 fps）。 |
| A12 | 断网验证 | 真正断网后执行 A2–A9 | 无任何网络访问仍可完成全流程 | **部分模拟**：净环境（不可用代理 + 清空 PATH/Python 变量）下已完成命令行与界面自动化全流程；未在真正断网/防火墙阻断环境执行 |
| A13 | 权限与路径 | 普通用户 + 中文/空格路径 | 全流程可用，无写入失败 | 中文/空格路径下“解压→自检→一键验收 11/11→再次自检”全部通过（2026-11-19，非提权进程）；普通用户待执行 |
| A14 | 课堂时间预算 | 40 分钟课堂内完成建项目 → 采集/导入 → 训练 → 预测 | 记录各阶段耗时，满足课堂节奏 | 开发机真实数据演练已记录（阶段合计约 16.0 s、含 30 张预测约 33.0 s，2026-11-20 复测；数字随负载波动，以 `artifacts/classroom-rehearsal/result.json` 为准；早前 2026-11-19 约 12.6 s / 29.5 s、2026-11-18 约 12.6 s / 28.1 s，见[真实数据验证](real-data-validation.md#8-课堂演练与时间预算2026-11-18)），未含真实摄像头采集时间与课堂环境 |
| A15 | 板端部署 | K230/K210 模型转换与实机运行 | 转换产物在实物板端完成推理并通过校验 | **未开始**（需硬件） |

## 5. 目标机记录模板

| 字段 | 记录 |
| --- | --- |
| 日期 / 执行人 | |
| 机器型号 / 系统版本 / 内存 | |
| 是否域账号 / 管理员 | |
| 安装路径 | |
| 分发包 SHA-256 | |
| A1–A9 结果（逐项） | |
| A10 数据与准确率 | |
| A12 断网方式 | |
| 失败项与日志 | |

## 6. 判定规则

- A1–A9、A12、A13 全部通过，且失败项有明确错误提示与可恢复方式，才可认为离线分发达到课堂试用条件。
- A10、A11、A14 涉及真实课堂与摄像头，需在真实教学环境补充；A15 需板端硬件。
- 任一检查未执行或环境不满足时，不得在汇报中写成“已通过验收”。

## 7. 附录：包内现场自动化脚本

解压离线包后，可直接用包内桌面与包内 Python 运行自动化脚本复验（无需开发环境）。通用参数：

```text
-Exe desktop\app\Laitp.Desktop.exe -LaitpHome . -LaitpPython python\python.exe
```

| 脚本 | 用途 | 备注 |
| --- | --- | --- |
| scripts/run_acceptance.ps1 | 一键验收：包内摘要自检 + 窗口自检 + 启动耗时；可选全流程 | 解压目录内执行（脚本会自动把控制台输出编码设为 UTF-8，兼容中文 Windows 默认 CP936 控制台）；生成 acceptance-run.json 与 acceptance-report.md（环境+步骤记录，可直接粘贴到第 5 节模板）；-SkipMeasure 跳过耗时项；-IncludeFlow 追加演示数据、新建导入与训练预测，其中“训练与预测”环节将执行界面批量预测，并在包内存在示例模型包（`demo/model-package`）时执行模型对比；再加 -IncludeExtended 追加保存与恢复流程（训练→关闭重开→恢复→数据检查）、数据体检（scripts/dataset_report.py）与批量历史汇总（scripts/batch_history_export.py），其中“批量历史汇总”将优先基于流程项目的非空批量历史，取不到时回退保存恢复项目；新增的脚本检查步骤在包内直接用包内 Python（python\python.exe）运行；-IncludeExtended 需与 -IncludeFlow 同用，单独指定时保存恢复与新增检查步骤均记为跳过；两个开关同用时，新增第 10 步“严格验收（正向）”与第 11 步“自检幂等性复核”后为 11 个步骤：第 10 步用包内 Python 对流程项目执行 `backend.project check-dataset --require-test --min-train/val/test`，验证严格验收正向链路（阈值仅用于链路验证，不作为课堂验收门槛）；正式包已实测 11/11 通过（2026-11-19） |
| check-bundle.bat | 清单摘要 + 推理 + 报告 + 桌面启动 + 首次自检 | 双击即可，需包内 Python |
| scripts/ui_smoke.ps1 | 窗口定位、自动自检、按钮点击 | -BrokenPython 可验证失败提示 |
| scripts/ui_flow.ps1 | 打开→检查→训练→预测；可选批量预测、另存为、最近项目、归档导出/导入、模型对比、数据体检、项目校验与批量历史汇总 | -ProjectPath <project.json>（必填）；-TrainPredict、-Epochs 20、-ImagePath <png>；-BatchImagesDir <dir>；-SaveAsDir <dir>；-UseRecent；-ArchiveDir <dir>（导出 flow-archive.zip 后再导入并打开）；-ComparePackage <dir>（需同时指定 -TrainPredict 与 -BatchImagesDir，对比当前训练产物与指定模型包）；-DataReport（数据体检，报告写入项目 runs/dataset-report.md）；-PostChecks（校验项目；若同时配合 -TrainPredict 与 -BatchImagesDir 跑完批量预测，再导出批量历史汇总到 runs/batch-history.md 与 runs/batch-history.csv；只做项目校验时不要加 -BatchImagesDir） |
| scripts/ui_create_import.ps1 | 新建项目 + 逐批导入 + 测试集导入 + 检查 | -SourceRoot <dir> -ProjectParent <dir> [-TestSource <dir>] [-TreeSource <dir>] |
| scripts/ui_restore.ps1 | 创建/训练/关闭重开/恢复 | -SourceRoot <dir> -ProjectParent <dir> |
| scripts/ui_export_history.ps1 | 训练历史重新导出 | -ProjectPath <project.json> |
| scripts/ui_edit.ps1 | 项目编辑 + 严格验收 | -ProjectPath <project.json>；`-MinTrain/-MinVal/-MinTest` 设置阈值、`-ExpectStrictPass` 验证严格验收正向通过 |
| scripts/ui_camera.ps1 | 摄像头检测/预览/连拍/拍照导入 | 需可用摄像头；-Screenshot 留图 |
| scripts/ui_preview_stability.ps1 | 长时间预览稳定性 | -Seconds 60 |
| scripts/measure_startup.ps1 | 启动耗时 | -Exe <exe>（可选 -LaitpHome/-LaitpPython） |
| scripts/batch_history_export.py | 批量预测历史汇总（命令行）：汇总项目 runs/ 下的多次批量预测；可选导出最近一次运行的类别/批次明细 | python\python.exe scripts\batch_history_export.py --project <项目目录或 project.json> [--markdown <md>] [--csv <csv>] [--details-csv <明细.csv>]；只读项目与 runs/batch-predict-*.json，不重新预测；`--details-csv` 输出最近一次运行的类别/批次明细表（表头 类型、名称、总数、正确数、准确率，UTF-8 BOM，Excel 可直接打开；无可用历史时不生成文件，输出 JSON 的 details_csv 为 null 并在 warnings 中提示）；无历史时仍成功并在输出 warnings 中提示，损坏记录计入 skipped |
| scripts/dataset_report.py | 数据体检报告（命令行）：每类每批次样本、重复/无效图片、尺寸分布与分级风险提示 | python\python.exe scripts\dataset_report.py --project <项目目录或 project.json> [--output <md>] [--csv <csv>]；默认写入 <项目目录>/dataset-report.md；报告含数据风险时退出码仍为 0（风险写入报告与输出 JSON 的 warnings），仅项目不可读/图片目录缺失等错误才返回 1 |

示例（在解压目录内执行）：

```powershell
powershell -File scripts\ui_smoke.ps1 -Exe desktop\app\Laitp.Desktop.exe -LaitpHome . -LaitpPython python\python.exe
powershell -File scripts\ui_create_import.ps1 -SourceRoot <图片目录> -ProjectParent <项目父目录> -Exe desktop\app\Laitp.Desktop.exe -LaitpHome . -LaitpPython python\python.exe
powershell -File scripts\ui_flow.ps1 -ProjectPath <project.json> -ImagePath <png> -TrainPredict -Epochs 3 -BatchImagesDir <测试图片目录> -DataReport -ArchiveDir <归档目录> -ComparePackage <历史模型包目录> -PostChecks -LaitpHome . -LaitpPython python\python.exe
python\python.exe scripts\batch_history_export.py --project <项目目录> --markdown runs\batch-history.md --csv runs\batch-history.csv --details-csv runs\batch-history-details.csv
python\python.exe scripts\dataset_report.py --project <项目目录>
```

说明：`ui_flow.ps1` 示例中的 `-ComparePackage` 需要项目已有可对比的历史模型包；没有时去掉该参数，并在记录中如实注明该项未执行。`-ArchiveDir` 会在指定目录（不存在时自动创建）生成 `flow-archive.zip` 并再导入打开。

### 建议执行顺序（目标机）

1. 解压 `laitp-offline-lean.zip` 到本地磁盘（可含中文/空格路径），核对 SHA-256 与交接说明一致。
2. 双击 `check-bundle.bat` 完成包清单摘要、解包推理、训练报告、桌面启动与首次自检，保留输出（对应 A1 的现场自检证据）。
2.5（可选）先在解压目录执行 `python\python.exe scripts\preflight_target.py --root .` 做只读环境预检（路径/磁盘/权限/长路径/包文件；不代表验收通过）；
3. 在解压目录执行 `powershell -ExecutionPolicy Bypass -File scripts\run_acceptance.ps1 -IncludeFlow -IncludeExtended`，生成 `acceptance-run.json` 与 `acceptance-report.md`（环境+步骤+结论）；如需跳过启动耗时项可加 `-SkipMeasure`。两个开关同用时 `acceptance-run.json` 的 `steps` 为 11 个（基础 3 步 + 流程 3 步 + 保存恢复 1 步 + 数据体检 1 步 + 批量历史汇总 1 步 + 第 10 步“严格验收（正向）” + 第 11 步“自检幂等性复核”）；新增步骤用包内 Python 对流程项目执行 `backend.project check-dataset --require-test --min-train/val/test`，验证严格验收正向链路，所用阈值仅用于链路验证、不作为课堂验收门槛。其中“训练与预测”环节将执行界面批量预测，并在包内存在示例模型包（`demo/model-package`）时执行模型对比；“批量历史汇总”将优先基于流程项目（该项目已有批量预测历史，汇总非空）执行，取不到流程项目或历史为空时回退到保存恢复项目。扩展前的 9 步覆盖已在正式包实测 9/9 通过（2026-11-19）；新增第 10/11 步后正式包已实测 11/11 通过（2026-11-19）；详见[项目状态报告](status-report.md)，仍需在目标机按本节记录逐项留证。
4. 按需补充界面采样（仍用包内桌面与包内 Python；项目路径可用第 3 步生成的项目，例如 `acceptance-demo\项目父目录\界面 项目\project.json`）：
   - 数据体检与项目校验：`... -DataReport -PostChecks`（仅校验项目、不导出批量历史）。
   - 归档往返：`... -ArchiveDir <归档目录>`。
   - 批量预测后再导出历史汇总 / 模型对比：`... -ImagePath <png> -TrainPredict -Epochs 3 -BatchImagesDir <测试图片目录> -PostChecks`；一键验收已用包内 `demo/model-package` 覆盖模型对比，如需与自己的历史模型包对比，再加 `-ComparePackage <历史模型包目录>`；没有历史模型包时省略该参数，并记录该手动补充项未执行。
5. 将 `acceptance-report.md`、`artifacts\ui-flow.json`、项目 `runs/dataset-report.md`、`runs/batch-history.md` 与截图/错误信息整理后填入第 5 节记录模板。任一脚本退出码非 0 或界面状态文案不符合预期时按第 6 节判定；脚本执行完成不等于验收通过，未执行项（如包内无示例模型包时的模型对比、或手动补充的历史模型包对比）须如实记录。

### 常见失败与排查

以下条目均来自本机解包目录的验证过程与历史构建问题记录，用于目标机排查；目标机尚未执行本清单，**不代表目标机已验证或必然复现**。步骤编号对应 `acceptance-run.json` 中 `steps` 的顺序（以 `-IncludeFlow -IncludeExtended` 的 11 个步骤为准；只运行基础项或单个开关时后续步骤不存在）：1 包内自检、2 窗口自检、3 启动耗时、4 演示数据生成、5 新项目与导入、6 训练与预测、7 保存与恢复、8 数据体检、9 批量历史汇总、10 严格验收（正向）、11 自检幂等性复核。每条按“现象 → 可能原因 → 处理方式”组织；排查后仍失败时按[第 6 节](#6-判定规则)记录为失败或未执行，不得改写为通过。

**1. 第 1 步“包内自检”报“文件大小不符 / 文件摘要不符”（先 `check-bundle` 再一键验收时）**

- **现象**：`acceptance-run.json` 的「包内自检」`status` 为 `fail`；该步骤的控制台输出（或单独重跑自检的 `failures`）含 `文件大小不符：backend/__pycache__/…pyc` 或 `文件摘要不符：…`。典型触发顺序是先双击 `check-bundle.bat`，再运行一键验收。
- **可能原因**：旧构建把包内 `backend/__pycache__` 的 pyc 计入 `manifest.json`；首次自检运行包内 Python 时这些 pyc 被重写（时间戳或内容变化），大小/摘要与清单不再一致。当前构建已在打包时排除第一方 `__pycache__`/`*.pyc`，并增加清单卫生检查与第 11 步幂等复核；本机复验见[离线分发包 §3.7](offline-bundle.md#37-自检幂等性复验与修复2026-11-19)。
- **处理方式**：
  1. 检查包内清单是否含缓存/编译产物（有输出说明是旧构建或手工改包）：
     ```powershell
     python\python.exe -c "import json; m=json.load(open('manifest.json',encoding='utf-8-sig')); paths=[f['path'] for c in m.get('components',[]) for f in c.get('files',[])]; bad=[p for p in paths if '__pycache__' in p.lower() or p.lower().endswith(('.pyc','.pyo'))]; print('清单文件数：', len(paths)); print('缓存/编译产物：', len(bad)); print('\n'.join(bad[:10]))"
     ```
     输出“缓存/编译产物”为 0 说明清单干净（新构建应如此）；大于 0 说明是旧构建或手工改包。也可运行 `python\python.exe scripts\verify_offline_bundle.py --extracted .`，新版会输出“清单卫生检查通过（… 个路径无缓存/编译产物）”。
  2. 换用新构建的包：重新解压到**全新目录**（不要覆盖旧目录），先 `check-bundle.bat` 再运行一键验收；由构建方按[离线分发包 §1](offline-bundle.md#1-构建与校验命令)重新构建。不要手工删除/补齐解压目录里的 pyc 或修改 `manifest.json`（手工删 pyc 会变成“缺少文件”）。
  3. 新构建若仍报大小/摘要不符，先核对包身份与解压完整性：`Get-FileHash .\laitp-offline-lean.zip -Algorithm SHA256` 与随包 `.sha256` 一致，再全新解压；并确认解压目录可写（见第 2 条处理方式第 3 点）。

**2. 第 11 步“自检幂等性复核”失败（验收后第二次自检与清单不一致）**

- **现象**：前 10 个步骤通过，第 11 步 `status` 为 `fail`；`acceptance-run.json` 该步 `detail` 提示“验收后自检失败（第 2 次 verify_offline_bundle --extracted . 退出码 …）”；`artifacts\verify-bundle-idempotent.stderr.txt` 记录该次自检的 stderr（该步骤把 stdout 丢弃，`failures` 明细需按下面命令重跑查看）。
- **可能原因**（按顺序排查）：
  1. **清单仍含 pyc/缓存**：旧构建或后改的包把 `__pycache__`/`*.pyc` 列入清单，运行后缓存被重写，第二次校验大小/摘要不符；**新版自检会直接报“清单包含缓存/编译产物”**。
  2. **在只读目录运行**：解压目录（或运行账号）不可写时，自检需要写 `self-test-result.json` 等输出、Python 运行缓存也无法写入，校验可能失败或时好时坏。
  3. 验收期间包内清单涉及的文件被改写：手工覆盖、同步盘或杀毒软件回写、并发运行另一个自检或桌面进程等。
- **处理方式**：
  1. 检查清单是否含 pyc/缓存：用第 1 条的清单命令，或直接重跑自检看 `failures`：
     ```powershell
     python\python.exe scripts\verify_offline_bundle.py --extracted .
     ```
  2. 提示“清单包含缓存/编译产物”或清单里查到 pyc → 该包不是最新构建，**重新构建包**（构建方按[离线分发包 §1](offline-bundle.md#1-构建与校验命令)构建，打包时排除 `__pycache__`/`*.pyc`），重新分发后全新解压再验收；不要只手工删除 pyc（清单会报“缺少文件”）。
  3. 确认解压目录可写，且不是只读共享或受控目录（不要放 U 盘、网络共享、`Program Files` 或只读挂载点，也不要在 ZIP 内直接运行）：
     ```powershell
     $probe = Join-Path (Get-Location) '.write-test'; New-Item -ItemType File -Path $probe -Force | Out-Null; Remove-Item $probe; '目录可写'
     (Get-Item .).Attributes
     ```
     命令报错或 `Attributes` 含 `ReadOnly` 时，移到本地可写目录并全新解压。
  4. 排除干扰后，用同一新包按“`check-bundle` → 一键验收 → 再次 `check-bundle`”重跑，确认第 1、11 步都通过。

**3. 第 2 步“窗口自检”失败，或第 1 步桌面程序启动即退出（锁屏/无交互桌面）**

- **现象**：`artifacts\ui-smoke-acceptance.json` 的 `error` 为“未找到桌面窗口（进程 …）”“未找到环境自检按钮”或“点击后未观察到自检状态或消息变化”；第 1 步可能同时报“解包目录桌面程序启动即退出”。锁屏、远程桌面断开、从计划任务/服务后台运行、无显示会话（session 0）时常见。
- **可能原因**：自检与窗口自检需要**已解锁的可交互桌面**（窗口自检使用 Windows UI Automation）；锁屏或无交互会话中窗口不可见/不可操作，不是包损坏或界面功能问题。
- **处理方式**：
  1. 在目标机本地登录并保持解锁（屏幕不锁、程序窗口可显示），重新运行一键验收：
     ```powershell
     powershell -ExecutionPolicy Bypass -File scripts\run_acceptance.ps1 -IncludeFlow -IncludeExtended
     ```
  2. 若用远程桌面，先确认会话已连接且桌面未锁（`quser` 中状态为 `Disc` 表示已断开）：
     ```powershell
     quser
     ```
  3. 只有在无法提供交互桌面时才可使用 `-SkipSmoke`（窗口自检记为 `skip`），但**不能据此认为 A2 通过**，也无法消除第 1 步的桌面启动/首次自检；须在记录中注明“窗口自检未执行”，改到可交互桌面补跑并留证。

**4. 中文/空格路径或路径过长（MAX_PATH）导致解压、自检或项目写入失败**

- **现象**：解压、自检、新建项目或保存时报“路径过长”“文件名或扩展名太长”“找不到路径”或写入失败；同一步骤时好时坏，换浅目录后恢复。
- **可能原因**：部分 Windows 组件与脚本仍受 260 字符传统路径限制（MAX_PATH）。解压目录较深（如 `C:\Users\<用户名>\Downloads\…`）再叠加中文项目名、批次名、带时间戳文件名后接近或超过上限；中文/空格本身可用，但会加长路径并增加引号/编码出错概率。
- **处理方式**：
  1. 解压到本地磁盘上的**短路径**（A13 要覆盖中文+空格时，用 `D:\课堂 软件\LAITP` 这类短目录）；不要放 U 盘、网络共享或只读目录，也不要直接在 ZIP 内运行。
  2. 检查解压树最长路径（数值小于 260 较稳妥，需留余量）：
     ```powershell
     Get-ChildItem -Recurse -Force | ForEach-Object { $_.FullName.Length } | Measure-Object -Maximum
     Get-ChildItem -Recurse -Force | Sort-Object { $_.FullName.Length } -Descending | Select-Object -First 3 FullName, @{n='Length';e={$_.FullName.Length}}
     ```
  3. 命令中的中文/空格路径统一用单引号包裹（如 `cd 'D:\课堂 软件\LAITP 离线包'`）；如确需长路径支持，可由管理员启用系统长路径策略后重启，但普通用户验收优先缩短路径。

**5. `acceptance-report.md` 显示“管理员：否”不是失败**

- **现象**：报告头部显示“用户：xxx（管理员：否）”；执行人误以为权限不足，或想“以管理员身份重跑”。
- **可能原因**：本清单要求普通用户（非管理员）执行 A2–A12，脚本如实记录当前进程令牌是否为管理员；普通用户显示“否”是预期结果，与步骤通过与否无关。
- **处理方式**：
  1. 以 `acceptance-run.json` 的 `ok` 与 `steps[].status` 判定，并结合[第 4 节](#4-验收项)人工核对 A2–A9；不要为了显示“管理员：是”而提权重跑，否则记录不再是普通用户场景，A13 结论会失真。
  2. 确认当前是否为管理员（普通用户应返回 `False`）：
     ```powershell
     ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
     ```
  3. 确需管理员的动作（启用摄像头、加杀毒排除、改系统策略）按第 2 节由管理员单独完成，再回到普通用户会话验收。

**6. 断网/联网与包内自检结果无关，A12 仍需单独验证**

- **现象**：不确定“联网时自检通过是否不算数”，或断网后自检/验收失败就归因于断网。
- **可能原因**：包内自检（清单摘要、包内 Python 导入、推理、报告、桌面启动、首次自检）只读本地文件，**不访问网络**，联网与否不改变自检结果；A12 要求的是真正断网环境下执行 A2–A9，属于独立验收条件，不能用联网结果或净环境模拟代替。
- **处理方式**：
  1. 按第 2 节真正断网（拔网线/关闭 Wi-Fi/防火墙全部阻断并清除系统代理）后，重新执行 A2–A9 与一键验收，并在[第 5 节](#5-目标机记录模板)“A12 断网方式”记录方法与证据（适配器状态、防火墙规则、代理设置）。
  2. 断网后的失败先按本节其余条目排查，不要默认归因于断网；本机 `--clean-env` 属开发机模拟，不是真正断网验收。

**7. 首次运行明显偏慢或耗时波动（冷启动/杀毒扫描）**

- **现象**：首次自检、窗口自检、训练预测比文档数字慢（本机解包复验记录中自检约 28–34 s、训练预测约 29 s、保存恢复约 42 s，均受机器负载影响）；第二次运行明显变快；`steps[].seconds` 波动大但 `status` 仍为 `pass`。
- **可能原因**：冷启动（包内 Python/torch 首次导入、桌面首次加载）、Windows Defender 或第三方杀毒实时扫描、机械盘/低配机器、后台负载；属正常波动，**耗时不是单步失败判定依据**（A14 课堂时间预算另行记录）。
- **处理方式**：
  1. 按 `status` 判定步骤是否通过，给首次运行留足时间，不要中途反复中断重跑；如确需排除杀毒影响，可由管理员预先将解压目录加入排除（属现场环境调整，需在记录中注明）。
  2. 查看耗时明细：
     ```powershell
     $run = Get-Content acceptance-run.json -Raw -Encoding UTF8 | ConvertFrom-Json
     $run.steps | Format-Table name, status, seconds
     ```

**8. 失败时先看哪些文件**

- **现象**：脚本退出码非 0，控制台信息不足，不知道哪一步失败。
- **可能原因**：`run_acceptance.ps1` 把逐步骤结果写入 JSON/报告，Python 子步骤的 stderr 另存到 `artifacts\`；只看控制台末尾容易漏掉具体步骤与错误路径。
- **处理方式**（按顺序）：
  1. `acceptance-run.json`：`ok`、`error`、`steps[].status` 与 `detail`（失败步骤及对应输出路径）。
  2. `acceptance-report.md`：系统、用户/管理员、CPU/内存/磁盘、长路径支持与包目录长度、包身份与步骤状态表，可直接作为[第 5 节](#5-目标机记录模板)记录草稿。
  3. `artifacts\*.stderr.txt`：包内 Python 的 stderr，如 `verify-bundle-idempotent.stderr.txt`、`strict-acceptance.stderr.txt`、`strict-acceptance-probe.stderr.txt`、`dataset-report-acceptance.stderr.txt`、`batch-history-acceptance.stderr.txt`（可能为空，失败明细以重跑脚本的 stdout 为准）。
  4. 对应步骤的 JSON：`artifacts\ui-smoke-acceptance.json`、`ui-create-import-acceptance.json`、`ui-flow-acceptance.json`、`ui-restore-acceptance.json`、`startup-acceptance.json`，界面脚本的 `error` 字段通常直接给出原因。
  5. 汇总命令：
     ```powershell
     $run = Get-Content acceptance-run.json -Raw -Encoding UTF8 | ConvertFrom-Json
     $run.steps | Format-Table name, status, seconds
     $run.steps | Where-Object status -eq 'fail' | Select-Object name, detail
     Get-ChildItem artifacts -Filter *.stderr.txt | Select-Object Name, Length, LastWriteTime
     ```
  6. 保留上述文件、`check-bundle` 完整输出与失败截图，按第 6 节记录；需要开发侧分析时附上包 SHA-256 与 `manifest.json` 的 `created_at`。

## 8. 当前状态矩阵（截至 2026-11-23）

> 本节状态基于 2026-11-23 的正式包与本机证据（SHA/体积随重建变化，以[离线分包说明](offline-bundle.md)为准）；外部项（目标机、普通用户、断网、课堂、K230/K210、检测）仍为未验证。

本矩阵把 A1–A15 的当前状态、关键证据与剩余动作集中列出，供交接和目标机验收排期使用。状态取自 `scripts/acceptance_audit.py` 生成的 `artifacts/acceptance-local.json`（生成时间以该文件 `generated_at` 为准；汇总：已验证 9、部分 4、未执行 1、阻塞 1），**不自行提升**；证据用文档相对链接索引，包 SHA-256、文件数等易随重建变化的数字不在此重复。

状态口径：

- **已验证**：证据**仅限开发机与解包目录环境**，不等于目标 Windows 机器、普通用户或真正断网环境已通过验收。
- **部分**：已有局部证据，但缺少真实设备、真正断网、普通用户或真实课堂等关键条件。
- **未执行**：缺少前置输入（如课堂真实图片），尚无验证记录。
- **阻塞**：缺少硬件或工具链，当前无法开始。

| 验收项 | 当前状态 | 关键证据 | 剩余动作/阻塞 |
| --- | --- | --- | --- |
| A1 包完整性 | **已验证**（限本机/解压环境） | [验证证据索引 §2](verification-evidence.md#2-离线包) 的离线包校验步骤；[离线分发包 §3](offline-bundle.md#3-解包校验结果本机)（3.1 包内容校验）的清单摘要、包内 Python 与“包内现场自检”结果 | **目标机待做**：解压后运行 `check-bundle.bat`（或包内 `python\python.exe scripts\verify_offline_bundle.py --extracted .`）并保留输出；以交付的 `.sha256` 复核包身份 |
| A2 解压与启动 | **已验证**（限本机/解压环境） | [验证证据索引 §3](verification-evidence.md#3-界面自动化与截图) 的界面冒烟（自检）通过；`artifacts/ui-camera-bundle.json`；[桌面外壳 §4](desktop-shell.md#4-本机验证结果) | **目标机待做**：干净系统普通用户双击 `start-desktop.bat`，确认窗口出现且状态栏为“就绪（环境自检通过）”，记录启动耗时 |
| A3 首次自检 | **已验证**（限本机/解压环境） | [桌面外壳 §7](desktop-shell.md#7-首次运行自检) 的自动/手动自检与缺 Python 失败提示；verify-all“界面冒烟（自检）”步骤 | **目标机待做**：首次启动自动自检与手动“环境自检”各执行一次并留证；可按需复验缺 Python 失败提示 |
| A4 新建项目 | **已验证**（限本机/解压环境） | [验证证据索引 §3](verification-evidence.md#3-界面自动化与截图) 的界面新建 + 导入（`ui_create_import.ps1`） | **目标机待做**：普通用户 + 中文/空格路径新建项目，核对类别顺序与状态文案 |
| A5 导入图片 | **已验证**（限本机/解压环境） | verify-all“界面新建 + 导入”“界面批量导入”步骤；[验证证据索引 §3](verification-evidence.md#3-界面自动化与截图) | **目标机待做**：用课堂数据逐类逐批导入（每类 ≥ 2 批次，建议 ≥ 30 张）与测试集导入，核对清单合计 |
| A6 检查数据（含严格验收） | **已验证**（限本机/解压环境） | verify-all“界面项目编辑 + 严格验收”拒绝路径；本机严格验收**正向通过**（真实子集 20/20/10，`artifacts/ui-edit-strict-positive.json`，见[验证证据](verification-evidence.md#3-界面自动化与截图)） | **目标机待做**：用每类 ≥30 训练 / ≥10 测试复验正向通过；另可运行一键验收（11 步）中的“严格验收（正向）”步骤核验正向链路（链路验证阈值，非课堂验收门槛） |
| A7 训练与发布 | **已验证**（限本机/解压环境） | verify-all“界面闭环（训练并发布）”步骤；[真实数据验证 §4](real-data-validation.md#4-本机结果2026-11-17) 的公开数据训练/发布记录 | **目标机待做**：设置正式轮数训练并发布，记录轮数、训练耗时与产物 ID，确认导出包可加载 |
| A8 预测 | **已验证**（限本机/解压环境） | verify-all“界面闭环（预测）”步骤；批量预测 30 张准确率 86.7%（[验证证据索引 §3](verification-evidence.md#3-界面自动化与截图)） | **目标机待做**：单图与批量预测各执行一次，记录预测耗时、准确率与 CSV 输出 |
| A9 项目保存恢复 | **已验证**（限本机/解压环境） | verify-all“界面保存 + 恢复”步骤；[桌面外壳 §4](desktop-shell.md#4-本机验证结果) 的解包目录恢复记录 | **目标机待做**：关闭重开后恢复项目，核对项目、类别、当前模型与训练历史均恢复 |
| A10 真实课堂图片 | **未执行** | 仅公开 Fashion-MNIST 子集准确率 0.917（[真实数据验证 §4](real-data-validation.md#4-本机结果2026-11-17)），不能替代课堂数据 | **目标机/课堂待做**：采集真实课堂图片后按 A5–A8 重跑并记录每类样本数、轮数、耗时与准确率；外部前置缺失：课堂采集数据未提供 |
| A11 摄像头采集 | **部分** | [摄像头能力 §2](camera.md#2-本机结果2026-11-18) 的 DroidCam 单张采集（`artifacts/camera-capture.png`）与预览探针约 20.7 fps；[摄像头能力 §3](camera.md#3-应用内采集已实现) 的设备选择/预览/连拍/拍照与错误提示 | **本机待做**：管理员启用物理 `HD Webcam`（当前 Code 22）后实测真实设备采集及权限/占用/缺失错误；**目标机待做**：课堂真实摄像头验证 |
| A12 断网验证 | **部分** | 净环境模拟（不可用代理 + 最小 PATH）下命令行与界面流程通过，见[离线分发包 §3](offline-bundle.md#3-解包校验结果本机)（3.3 净环境模拟）与 `artifacts/offline-clean-env-result.json`、`ui-flow-clean-bundle.json`、`ui-camera-clean-bundle.json` | **目标机待做**：真正断网（拔网线/关闭 Wi‑Fi/防火墙全阻断并清除系统代理）后执行 A2–A9；现有证据只是模拟，非真正断网 |
| A13 权限与路径 | **部分** | 中文+空格路径“解压→自检→一键验收 11/11→再次自检”通过（[离线分发包 §3.7](offline-bundle.md#37-自检幂等性复验与修复2026-11-19)） | **目标机待做**：普通用户（非管理员）+ 干净目标机执行全流程；本机当前令牌为非提权 Medium IL |
| A14 课堂时间预算 | **部分** | 单机课堂演练阶段合计约 16.0 s、含 30 张预测约 33.0 s（2026-11-20 复测；数字随负载波动，以 `artifacts/classroom-rehearsal/result.json` 为准；[真实数据验证 §8](real-data-validation.md#8-课堂演练与时间预算2026-11-18)） | **目标机/课堂待做**：在 40 分钟课堂节奏下实测“建项目 → 采集/导入 → 训练 → 预测”，计入摄像头采集与人工操作时间；本机数字受系统负载影响会波动 |
| A15 板端部署 | **阻塞** | 无板端产物；仅有[K230 板端可行性准备](k230-feasibility.md)（规划，未实现） | **硬件阻塞**：无 K230/K210 硬件与转换工具链，当前无法开始；需硬件、工具链与实机联调 |

汇总与 `artifacts/acceptance-local.json` 一致：已验证 9（A1–A9）、部分 4（A11–A14）、未执行 1（A10）、阻塞 1（A15）。目标机执行步骤见第 4 节与第 7 节，记录模板见第 5 节。状态变化后重新运行 `scripts\acceptance_audit.py` 刷新 `artifacts/acceptance-local.json/md`，本表以其为准、不手工修改状态。
