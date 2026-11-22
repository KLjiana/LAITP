# 剩余工作与解锁条件（截至 2026-11-23，2026-11-20 第 250 轮更新）

本文把 LAITP 当前**本机无法继续推进、依赖外部条件**的剩余工作集中成一份清单，供 lead、学校/机房管理员、硬件与课程负责人及接手人分工推动。本文是**工作清单与解锁条件说明**，不是验收结论，也不改变任何验收状态：文中“已验证”一律沿用既有文档与证据的口径，**不声称任何未验证项已通过**。

相关入口：[总体路线与项目大纲](roadmap.md)、[项目状态报告](status-report.md)、[目标机离线验收清单](acceptance-checklist.md)（[§8 当前状态矩阵](acceptance-checklist.md#8-当前状态矩阵2026-11-19)）、[验证证据索引](verification-evidence.md)、[检测待决问题决策建议](detection-decisions.md)、[K230 板端可行性准备](k230-feasibility.md)。

## 1. 状态声明（截至 2026-11-23，2026-11-20 第 250 轮更新）

### 1.1 本机已完成并有证据的范围

以下结论均来自**开发机 / 解压目录**，细项与数字以被链接文档和 `artifacts/` 为准：

- 分类 M0–M2 的软件链路已实现并验证：契约 `1.0` 校验、数据清单、CPU 训练、ONNX 导出与模型包、推理 / 批量预测 / 模型对比、项目保存恢复、WPF 主流程、离线包与包内自检。本机 Python 测试 483 项通过、桌面构建 0 警告 0 错误、Core 检查 64 项通过、交付状态自检 `scripts/check_state.py` 11 项通过（2026-11-23，见[项目状态报告 §2](status-report.md)）。
- 本机一键验证 `scripts/verify_all.py --ui` 为 **16 步通过**（界面摄像头拍照导入按用户要求跳过，约 10 分钟）。
- 正式精简包解压后在**中文+空格路径、非提权进程**下执行 `scripts/run_acceptance.ps1 -IncludeFlow -IncludeExtended` 为 **11/11 环节通过**（2026-11-20；包内自检、窗口自检、启动耗时、演示数据、新建与导入、训练与预测、保存与恢复、数据体检、批量历史汇总、严格验收（正向）、自检幂等性复核；见 `artifacts/acceptance-report-final.md` 与[项目状态报告 §2](status-report.md)）。这是**解压环境证据，不是目标机验收**：未在干净目标机、普通用户、真正断网条件下执行。
- 离线包已排除第一方 `__pycache__`/`*.pyc`，并修复“先 `check-bundle` 再一键验收”的幂等缺陷；当前精简包清单 **18,172 个文件**，按“自检 → 一键验收 11/11 → 再次自检”复验幂等通过（2026-11-19 为当时 18,170 文件构建；2026-11-23 正式包的一键验收仍含“自检幂等性复核”并通过；中文+空格路径、非提权；见[离线分发包 §3.7](offline-bundle.md#37-自检幂等性复验与修复2026-11-19)）。包 SHA-256 与体积以 `dist/laitp-offline-*.zip.sha256` 和[离线分发包](offline-bundle.md)为准，本文不写死具体值。
- A1–A15 验收汇总：**已验证 9、部分 4、未执行 1（A10）、阻塞 1（A15）**，与[验收清单 §8 矩阵](acceptance-checklist.md#8-当前状态矩阵2026-11-19)一致；其中 A6 严格验收正向通过已有界面证据（真实子集 20/20/10，`artifacts/ui-edit-strict-positive.json`，见[验证证据索引 §3](verification-evidence.md#3-界面自动化与截图)），A13 仍为**部分**（普通用户/干净目标机待验证）。A1–A9 的“已验证”只限开发机与解压目录环境，不等于目标 Windows 机器、普通用户或真正断网环境已通过。
- 摄像头：设备选择 / 预览 / 拍照 / 连拍链路曾用 `DroidCam Video` 虚拟摄像头在本机验证（预览约 20–21 fps），但物理摄像头被禁用，自动化测试自 2026-11-18 起按要求停止（见[摄像头能力](camera.md)）。
- 检测 M3：只有规划、契约草案、决策建议稿与**未激活**的 Schema 草案 / 合成校验脚本；没有检测标注、训练、导出、电脑测试、转换或板端证据（见[检测课可行性规划](detection-feasibility.md)）。

### 1.2 未完成、本文不声称通过的范围

- 干净 Windows x64 目标机上的“解压双击 → 新建 → 采集/导入 → 检查 → 训练 → 预测 → 保存恢复”全流程（A1–A9 的目标机复验）。
- 目标机普通用户（非管理员）在受管账号、域环境或受限权限下的完整流程（A13）。
- 真正断网 / 隔离网络下的解压运行与自检（A12）。
- 物理摄像头（`HD Webcam` 当前 Code 22 被禁用）的真实采集、预览与课堂使用（A11）。
- 真实课堂图片数据与 40 分钟课堂时间预算（A10、A14）。
- K230 / K210 的模型转换、量化与实物板端运行（A15、M4）。
- 检测 M3 的 Q1–Q8 决策、P2 定稿、P1–P9 实现与验收（当前连检测格式都未激活；校验器仍拒绝检测任务）。

### 1.3 状态词与使用方式

| 状态 | 含义 | 与验收矩阵的关系 |
| --- | --- | --- |
| **阻塞** | 缺少外部条件（机器、硬件、工具链、决策），本机无法开始或无法完成。 | 对应 `artifacts/acceptance-local.json` 的 `blocked` |
| **未执行** | 前置输入尚未提供，尚未产生任何执行记录。 | 对应 `not_run` |
| **部分** | 已有部分本机证据，但关键场景（目标机、断网、普通用户、真实设备、真实课堂）缺失。 | 对应 `partial` |

使用方式：

1. 本文只列剩余工作与解锁条件，**不新增、不提升**任何验收结论；A1–A15 的判定仍以[目标机离线验收清单](acceptance-checklist.md)与重新生成的 `artifacts/acceptance-local.json` 为准。
2. 各节的“本机还能做什么”只描述当前条件下仍可准备或复核的事项，不表示已经执行；本轮实际执行范围见第 10 节。
3. 解锁后在对应小节记录实际结果与证据路径，不要直接把“已执行”写成“已通过”。

## 2. 总览

| 编号 | 剩余工作 | 当前状态 | 主要外部依赖 / 提供方 | 对应验收项 |
| --- | --- | --- | --- | --- |
| R1 | 目标机离线验收（解压 → `check-bundle.bat` → 11 环节包内验收 → A1–A9 人工留证；包内验收含严格验收正向与自检幂等性复核） | **阻塞**（本机 A1–A9 有证据，目标机未执行） | 学校/机房：干净 Windows 机器、普通用户、断网窗口；lead：离线包与记录模板 | A1–A9（A12/A13 同批，见 R4） |
| R2 | 物理摄像头真实采集（A11） | **部分** | 机器管理员：启用 `HD Webcam` 或更换摄像头；用户：明确同意恢复自动化测试 | A11 |
| R3 | 课堂真实数据与 40 分钟时间预算（A10/A14） | **未执行**（A10）/ **部分**（A14） | 学校/授课教师：经授权的课堂图片与课堂环境 | A10、A14 |
| R4 | 真正断网验证（A12） | **部分** | 学校 IT / 网络管理员：断网或隔离网络环境 | A12（与 A13 同批） |
| R5 | K230/K210 板端部署（A15） | **阻塞** | 硬件提供方：板卡/外设；SDK 提供方：固定版本工具链与离线包；lead：排期与许可确认 | A15（K210 属 M4） |
| R6.1 | 检测 Q1–Q8 决策（门槛 A 六项） | **阻塞**（全部未决） | lead 召集评审；课程/验收、工程、硬件负责人参与 | M3（不属 A1–A15） |
| R6.2 | P2 定稿（草案 → 正式契约升版） | **阻塞**（依赖 R6.1） | lead 批准范围；工程按契约流程同步五处 | M3 |
| R6.3 | 检测数据标注工具与样例 | **未执行**（仅有草案 Schema 与样例） | lead 决定标注入口；课程提供标注规范；工程实现 P5 | M3 |
| R6.4 | 合成数据回归 | **部分**（草案级已存在，正式版未建立） | 依赖 R6.2；工程升级并接入验证套件 | M3 |
| R6.5 | P3/P4/P5（无硬件可做部分） | **部分**（仅完成 P3/P6 前置的草案探测，SSDLite 与 fasterrcnn 各本机单次；P3/P4/P5 主体未执行） | lead 排期；训练依赖/权重/许可证确认；课程确认课堂方案 | M3 |

## 3. R1 目标机离线验收（A1–A9、A13 同批；A12 见 R4）

| 属性 | 内容 |
| --- | --- |
| 当前状态 | **阻塞**。本机 A1–A9 已有证据，但没有干净目标机，目标机验收项一项都未执行；不得写成已通过。 |
| 对应验收项 | A1–A9、A13；A12 的断网条件在同一台目标机上同批执行（见 R4）。逐项状态见[验收清单 §8](acceptance-checklist.md#8-当前状态矩阵2026-11-19)。 |
| 解锁后责任人 | 学校/机房提供机器与账号；lead 提供交付包、记录模板并指定证据归档人；执行人按第 3.4 节命令操作。 |
| 本机还能做什么 | 本机不能替代目标机验收。交付前可只读核对交接目录 SHA / 文件齐全（`scripts\check_state.py`，11 项交付状态自检）与文档一致性（`scripts\check_docs.py`），并准备证据目录模板；包内已排除 `__pycache__`/pyc 并完成“自检 → 一键验收 11/11 → 再次自检”幂等复验（见[离线分发包 §3.7](offline-bundle.md#37-自检幂等性复验与修复2026-11-19)）。以上均为本机/解压环境证据；本轮未运行完整 `verify_all`、未打包。 |

### 3.1 内容

在**目标 Windows 机器**（干净系统、普通用户、真正断网）上完成 M2 离线分发与课堂流程验收：

1. 环境准备：干净 Windows 10/11 x64，内存 ≥ 8 GB，解压盘 ≥ 2 GB 可用空间，屏幕 ≥ 1024×768；普通用户（非管理员）执行；解压路径包含中文与空格（如 `D:\课堂 软件\LAITP 离线包`）；断网（拔网线、关闭 Wi-Fi 或防火墙全阻断，并清除系统代理）。
2. 解压 → 核对包身份 → 双击 `check-bundle.bat`（包内自检）→ 执行 11 环节包内一键验收 → 归档 `acceptance-report.md`。
3. 逐项执行并留证 A1–A9：包完整性、解压与启动、首次自检、新建项目、导入图片、检查数据（勾选严格验收；正向通过本机已有界面证据，目标机仍需用每类 ≥30 训练 / ≥10 测试复验）、训练与发布、预测、项目保存恢复；A13 的普通用户 + 中文/空格路径在同一次执行中覆盖。

### 3.2 为什么现在是阻塞 / 未完成

- 现有 A1–A9 证据全部来自开发机或解压目录，机器上已预装 .NET SDK / Python / 开发环境，账号、系统策略和网络条件都不代表机房目标机；`verify_all.py --ui` 16 步与包内 11 环节（仅解压环境自动化链路）都不能替代“干净机器 + 普通用户 + 真正断网 + 解压双击”。
- 目前没有可用于验收的干净目标机、普通用户账号和断网窗口；验收清单要求的记录模板、截图与耗时数据也需现场产生。
- A13 的普通用户与路径条件未在目标机受管账号、域环境或受限权限下验证；本机账号权限与目标机不等价。

### 3.3 解锁条件（谁提供什么）

- **学校 / 机房管理员**：
  - 1 台干净 Windows 10/11 x64 实机或虚拟机（≥8 GB 内存、≥2 GB 解压盘可用空间、屏幕 ≥1024×768、允许解压与写入本地磁盘；不影响他人使用）；
  - 普通用户账号（非管理员；如为域账号请说明组策略限制），并允许管理员在需要时单独启用物理摄像头（见 R2）；
  - 断网或隔离网络窗口（学校 IT 配合，见 R4），以及 60–90 分钟验收时间。
- **lead / 交付人**：
  - `laitp-offline-lean.zip`（含同名 `.sha256`）；首次部署或依赖修复时附 `laitp-offline-full.zip`；
  - [目标机离线验收清单](acceptance-checklist.md)（第 2、4、5、6、7 节）、包内 `docs/teacher-quickstart.md`、记录模板与证据目录规范；
  - 每个类别 ≥30 张训练图片、≥10 张测试图片（建议 3 个类别，按 `类别/批次/*.png` 组织），或由学校提供真实数据（见 R3）。
- **验收人 / 证据归档人**：由 lead 指定；负责把现场证据归档并在验收记录上签字（不得由执行人自行宣布通过）。

### 3.4 解锁后的执行步骤（可复制命令）

以下命令在**目标机**执行；尖括号占位符替换为实际路径。第 0–4 步先完成包内自动化，第 5 步再人工逐项确认 A2–A9。

```powershell
# 0. 环境与账号留证（普通用户执行；断网后运行“网络状态”部分）
whoami
Get-ComputerInfo | Select-Object WindowsProductName, WindowsVersion, CsTotalPhysicalMemory
Get-PSDrive -PSProvider FileSystem | Select-Object Name, Free
Get-NetAdapter | Select-Object Name, Status
netsh winhttp show proxy
Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' |
    Select-Object ProxyEnable, ProxyServer

# 1. 核对交付包身份（解压前，与交接的 .sha256 比对；示例文件名按实际替换）
Get-FileHash .\laitp-offline-lean.zip -Algorithm SHA256
Get-Content .\laitp-offline-lean.zip.sha256

# 2. 解压到中文/空格路径（资源管理器右键解压或 Expand-Archive；不要放 U 盘、网络共享或只读目录）
cd 'D:\课堂 软件\LAITP 离线包'

# 3. 包内自检（等待完成并保留完整输出）
cmd /c "check-bundle.bat > check-bundle-output.txt 2>&1"
Get-Content .\check-bundle-output.txt

# 4. 包内一键验收（11 个环节，约 5–6 分钟；-IncludeExtended 必须与 -IncludeFlow 同用）
powershell -ExecutionPolicy Bypass -File scripts\run_acceptance.ps1 -IncludeFlow -IncludeExtended

# 5. 人工逐项确认 A2–A9（包内验收覆盖自动化链路，人工仍要核对界面状态与记录）
.\start-desktop.bat
# 界面内依次执行：
#   环境自检（A3）→ 新建项目并使用中文/空格路径（A4）→ 逐类逐批导入 + 测试集导入（A5）
#   → 检查数据（勾选严格验收；A6）→ 设置轮数训练并发布，记录产物 ID 与耗时（A7）
#   → 单图预测 + 批量预测，记录准确率/误判/CSV（A8）→ 关闭程序后重新打开并恢复项目（A9）

# 6. 归档证据（目录由 lead 指定；示例）
$evidence = 'D:\LAITP 验收证据\目标机-2026-11-19'
New-Item -ItemType Directory -Force $evidence | Out-Null
Copy-Item .\acceptance-report.md, .\acceptance-run.json, .\check-bundle-output.txt $evidence
Copy-Item .\artifacts\*.json $evidence -ErrorAction SilentlyContinue
Copy-Item .\artifacts\ui-screenshots $evidence -Recurse -ErrorAction SilentlyContinue
Get-Date | Out-File $evidence\执行时间与执行人.txt
```

说明：

- `run_acceptance.ps1` 在解压目录内执行；生成的 `acceptance-report.md` 是步骤记录（含系统、用户、是否管理员、11 个环节状态），**不等于 A1–A9 已通过**，仍需人工按第 5 步核对界面状态。
- A1 的现场证据为 `check-bundle.bat` 完整输出；A7/A8 需记录产物 ID、训练耗时、预测耗时与准确率；A9 需记录关闭重开后项目、类别、当前模型与训练历史均恢复。
- 任一脚本退出码非 0、界面状态文案不符合预期或留证缺失，均按[验收清单 §6](acceptance-checklist.md)判定规则记录为失败/未通过，不得改写为通过。

### 3.5 验收证据去向

- 目标机现场证据目录（lead 指定，建议随交接目录归档）：`acceptance-report.md`、`acceptance-run.json`、`check-bundle-output.txt`、`artifacts\*.json`、界面截图、包 SHA-256 核对记录、执行时间与执行人记录。
- 结果填入[验收清单 §5 记录模板](acceptance-checklist.md)（机器型号/系统/内存、账号类型、安装路径、包 SHA-256、A1–A9 逐项结果、失败项与日志）。
- A1–A9/A13 是否通过以[验收清单 §6](acceptance-checklist.md)判定规则为准，由 lead 审核证据后更新 §8 矩阵；本文和 `acceptance-report.md` 都不直接改验收状态。
- 相关文档：[目标机离线验收清单](acceptance-checklist.md)（§2/§4/§5/§6/§7/§8）、[验证证据索引 §5](verification-evidence.md)、[离线分发包](offline-bundle.md)。

## 4. R2 物理摄像头真实采集（A11）

| 属性 | 内容 |
| --- | --- |
| 当前状态 | **部分**。虚拟摄像头（DroidCam）链路已在本机验证；物理 `HD Webcam` 被禁用（Code 22）；自动化测试已按要求停止，真实设备未验证。 |
| 对应验收项 | A11（[验收清单 §8](acceptance-checklist.md#8-当前状态矩阵2026-11-19)）。 |
| 解锁后责任人 | 机器管理员：启用设备或更换摄像头；用户/lead：明确同意恢复摄像头自动化测试（如需要）；执行人：人工采集验收。 |
| 本机还能做什么 | 本机无管理员权限，不能启用物理设备；按要求不再新增或恢复摄像头自动化测试。可在管理员启用设备后，用真实摄像头复验采集/预览/连拍；当前可整理人工验收记录模板。 |

### 4.1 内容

启用物理 `HD Webcam`（或更换可用的 USB 摄像头）后，人工验证：

- 设备选择与检测刷新能识别真实摄像头；
- 预览画面正常、帧率可记录、能正常停止；
- 连拍 3 张、拍照导入当前类别成功（重复内容校验按项目规则工作）；
- 可选：在用户明确同意恢复自动化测试后，运行 `scripts\ui_camera.ps1` 留证，或运行 `verify_all.py --ui --camera`（17 步）；否则只做人工操作并如实记录“未运行自动化”。

### 4.2 为什么现在是阻塞 / 未完成

- 物理 `HD Webcam` 状态为 **Error，Code 22（设备已禁用）**；本机执行 `pnputil /enable-device` 返回 Access is denied，需要管理员权限启用或更换设备（见[摄像头能力 §2](camera.md)）。
- `DroidCam Video` 只是虚拟摄像头：它证明了 WinRT 采集与界面链路可用，不代表课堂真实摄像头、驱动、权限策略可用。
- 摄像头自动化测试自 2026-11-18 起按要求停止；恢复自动化需要用户明确同意，不能默认重新开启。
- 权限被拒、设备占用、设备缺失等错误提示只有 Core 检查覆盖，尚未在真实设备上触发。

### 4.3 解锁条件（谁提供什么）

- **机器管理员 / 学校 IT**：在设备管理器中启用 `HD Webcam`（或提供可用 USB 摄像头及驱动），记录设备名称、驱动版本、启用方式；如为实验室机器，确认普通用户可访问摄像头权限（Windows 设置 → 隐私 → 相机）。
- **用户 / lead**：明确是否恢复摄像头自动化测试；若不恢复，只做人工验证并在记录中注明。
- **执行人**：在目标机（或本机启用设备后）按 4.4 执行并留证；真实课堂摄像头使用场景由学校/教师确认。

### 4.4 解锁后的执行步骤（可复制命令）

```powershell
# 1. 查看摄像头设备状态（普通用户即可）
Get-PnpDevice -Class Camera | Select-Object Status, FriendlyName, InstanceId

# 2. 管理员启用设备（需管理员；把 <InstanceId> 换成上一步查到的值）
pnputil /enable-device "<InstanceId>"
# 或：设备管理器 → 摄像头 → HD Webcam → 右键“启用设备”

# 3. 底层单张采集探针（开发机命令；目标机包内无 .dotnet，改用界面验证）
.\.dotnet\dotnet.exe run --project desktop\tests\Laitp.CameraChecks -v quiet -- artifacts\camera-capture.png

# 4. 界面人工验证（启动后）
.\start-desktop.bat
# 打开/新建项目 → 摄像头行选择设备 → 开始预览（记录 fps 与稳定性）→ 连拍 3 张
# → 拍照导入当前类别 → 停止预览 → 关闭程序；保留预览与数据清单截图

# 5. 可选：仅在用户明确同意恢复自动化测试后执行
powershell -ExecutionPolicy Bypass -File scripts\ui_camera.ps1 -ProjectParent <临时项目父目录> -Screenshot
# 如确需整包套件复验（会重新跑完整 16 步并追加摄像头步骤，耗时较长）：
.\.venv\Scripts\python.exe scripts\verify_all.py --ui --camera
```

### 4.5 验收证据去向

- `artifacts\camera-capture.png`（底层探针输出）、`artifacts\ui-camera.json`（如运行脚本）、`artifacts\ui-screenshots\`（预览与数据清单截图）。
- 在[验收清单 §5 记录模板](acceptance-checklist.md)记录设备名、启用方式、预览 fps、拍照/连拍结果、是否运行自动化；A11 状态由 lead 按证据更新 §8。
- 真实设备上的权限/占用/缺失错误如能复现，另记错误提示与 HRESULT，作为[摄像头能力 §4](camera.md)的补充证据。
- 相关文档：[摄像头能力](camera.md)（§2/§3/§4/§5）、[验证证据索引 §3](verification-evidence.md)、[验收清单 §8](acceptance-checklist.md#8-当前状态矩阵2026-11-19)。

## 5. R3 课堂真实数据与课堂时间预算（A10、A14）

| 属性 | 内容 |
| --- | --- |
| 当前状态 | **未执行**（A10：没有课堂真实图片）/**部分**（A14：只有单机时间记录，不含采集与课堂环境）。 |
| 对应验收项 | A10、A14（[验收清单 §8](acceptance-checklist.md#8-当前状态矩阵2026-11-19)）。 |
| 解锁后责任人 | 学校/授课教师：经授权的课堂图片与课堂安排；lead：数据使用/留存/隐私确认与验收人；执行人：导入→训练→预测与时间记录。 |
| 本机还能做什么 | 本机现有数字来自公开 Fashion-MNIST 子集与单机课堂演练，不能代替课堂数据；可提前准备数据接收清单、时间记录模板与导入/检查命令，但不得把本机数字写成课堂预算已通过。 |

### 5.1 内容

用学校课堂采集的真实图片重跑 A5–A8：

1. 每个类别 ≥30 张训练图片、≥10 张测试图片（建议 3 类；按 `类别/批次/*.png` 组织；覆盖不同光照、背景、距离、角度；测试集独立采集、不参与训练与调参）。
2. 建项目 → 逐类逐批导入（含测试集）→ 数据检查（建议严格验收）→ 训练并发布 → 单图/批量预测，记录每类样本数、训练轮数、各阶段耗时、准确率、误判样本与误判原因。
3. 按 40 分钟课堂节奏测量“建项目 → 采集/导入 → 检查 → 训练 → 预测/讲评”的实际用时，计入摄像头采集与人工操作时间（A14）。

### 5.2 为什么现在是阻塞 / 未完成

- 没有课堂真实图片：A10 无输入数据；现有准确率数字（约 0.917）来自公开 Fashion-MNIST 3 类子集，分布与课堂拍摄差异大，不能替代。
- A14 只有单机演练记录（2026-11-20 复测：阶段合计约 16.0 s、含 30 张预测约 33.0 s；数字随负载波动，以 `artifacts/classroom-rehearsal/result.json` 为准；早前 2026-11-19 约 12.6 s / 29.5 s），不含真实摄像头采集、人工标注/筛选与课堂环境时间（见[真实数据验证 §8](real-data-validation.md)）。
- 课堂数据涉及学生肖像、隐私与学校授权，需学校确认使用范围、保存期限与删除方式；在没有授权前不能收集或提交到仓库。

### 5.3 解锁条件（谁提供什么）

- **学校 / 授课教师**：
  - 经学校许可的课堂图片数据集（按类别/采集批次组织；说明类别定义、采集设备、场景、样本数量、是否含独立测试集）；
  - 课堂安排（日期、40 分钟课堂流程与现场教师），并确认肖像/隐私与数据留存要求。
- **lead**：确认数据只用于验收、不进入 git；指定存放与删除责任；指定 A10/A14 记录人与审核人；必要时更新[真实数据验证](real-data-validation.md)的真实课堂数据章节（数据本身不公开）。
- **执行环境**：目标机（R1）为正式执行环境；A10/A14 可与目标机验收同批完成。

### 5.4 解锁后的执行步骤（可复制命令）

在**目标机**（或经 lead 同意的开发机预跑，结果不作为目标机证据）执行；训练与预测默认走界面，命令行用于数据导入、检查与留档。尖括号占位符替换为实际路径。

```powershell
# 1. 建项目（建议 3 类；类别名与课堂类别一致）
.\.venv\Scripts\python.exe -m backend.project create --root "<验收目录>\课堂 项目" --name "课堂实物分类" --classes 类别A 类别B 类别C

# 2. 按批次导入训练图片（源目录建议：类别/批次/*.png）
.\.venv\Scripts\python.exe -m backend.project import-tree --root "<验收目录>\课堂 项目" --source "<课堂数据>\训练集"

# 3. 导入独立测试集
.\.venv\Scripts\python.exe -m backend.project import-tree --root "<验收目录>\课堂 项目" --source "<课堂数据>\测试集" --split test

# 4. 数据检查与严格验收（阈值按学校实际样本量调整并记录；不要为通过验收临时放宽）
.\.venv\Scripts\python.exe -m backend.project check-dataset --root "<验收目录>\课堂 项目" --require-test --min-train 30 --min-val 10 --min-test 10

# 5. 数据体检（报告留档）
.\.venv\Scripts\python.exe scripts\dataset_report.py --project "<验收目录>\课堂 项目\project.json"

# 6. 训练与发布（界面操作）：.\start-desktop.bat → 训练并发布 → 记录轮数、开始/结束时间、产物 ID
# 7. 单图与批量预测（界面操作，记录准确率、各类/各批次结果与误判样本）
#    可选：对已发布模型包补充命令行批量预测（测试目录需按类别组织才能算准确率）
.\.venv\Scripts\python.exe -m backend.runtime.batch --package "<验收目录>\课堂 项目\exports\<产物ID>\model-package" --images "<课堂数据>\测试集" --output "<验收目录>\课堂 项目\runs\classroom-batch.json" --csv "<验收目录>\课堂 项目\runs\classroom-batch.csv"

# 8. A14 时间预算：记录建项目/导入/检查/训练/预测/讲评各阶段起止，统计总时长是否满足 40 分钟课堂
```

### 5.5 验收证据去向

- 项目内 `runs\`：训练记录、`runs\dataset-report.md`、批量预测 JSON/CSV、误判列表；界面截图。
- A14 时间记录表（各阶段起止与总计）与 A10 记录（每类样本数、轮数、耗时、准确率、误判原因）填入[验收清单 §5 记录模板](acceptance-checklist.md)；A10/A14 状态由 lead 按证据更新 §8。
- 如需长期引用，由 lead 决定是否在[真实数据验证](real-data-validation.md)新增“真实课堂数据”章节；课堂图片本身不入库、不公开。
- 相关文档：[真实数据验证](real-data-validation.md)（§4/§6/§8）、[老师快速上手](teacher-quickstart.md)、[验收清单](acceptance-checklist.md)。

## 6. R4 真正断网验证（A12）

| 属性 | 内容 |
| --- | --- |
| 当前状态 | **部分**。仅有净环境模拟（清空 PATH / 清除 Python 变量 / 代理指向不可用地址），未在真正断网或隔离网络环境执行。 |
| 对应验收项 | A12（与 A13 同批；[验收清单 §8](acceptance-checklist.md#8-当前状态矩阵2026-11-19)）。 |
| 解锁后责任人 | 学校 IT / 网络管理员：断网或隔离网络；lead：验收窗口与执行人；执行人：记录断网方式与证据。 |
| 本机还能做什么 | 本机是联网开发机，不具备真正断网/隔离条件；不重复已覆盖的模拟。可准备断网检查清单与证据模板。 |

### 6.1 内容

在真正断网（拔网线、关闭 Wi-Fi、防火墙全部阻断并清除系统代理；或隔离 VLAN/无外网实验室）后，执行 A2–A9 全流程并证明无任何网络访问仍可完成：

1. 断网前后记录网络适配器状态、WinHTTP/IE 代理设置、防火墙策略（必要时导出规则）。
2. 在断网状态下解压离线包 → `check-bundle.bat` → 包内 11 环节一键验收 → 人工执行 A2–A9。
3. 观察是否出现网络相关错误、超时或隐式下载；如有，记录日志并视为未通过/缺陷。

### 6.2 为什么现在是部分 / 未完成

- 现有净环境证据（[离线分发包 §3.3](offline-bundle.md)）是在联网开发机上清空 PATH、清除 `PYTHON*`、把代理指向不可用地址得到的模拟，仍存在网络栈；它能证明“不依赖开发环境与网络配置”，不能证明“网络层完全断开时仍可运行”。
- 离线包证明依赖已打包，但运行时不发起网络请求、系统策略不拦截本地操作仍需要在真实断网环境验证。

### 6.3 解锁条件（谁提供什么）

- **学校 IT / 网络管理员**：可断网的目标机（与 R1 同一台）或隔离网络；断网/恢复操作授权；防火墙与代理策略说明（如必须保留某些内网服务，需明确并记录）。
- **lead**：安排验收窗口与执行人，指定断网证据归档位置。
- 该验证与 R1 同批执行，避免重复准备。

### 6.4 解锁后的执行步骤（可复制命令）

```powershell
# 0. 断网并留证（在网络管理员指导下执行；示例：关闭适配器后确认无连接）
Get-NetAdapter | Select-Object Name, Status, LinkSpeed
netsh winhttp show proxy
Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' |
    Select-Object ProxyEnable, ProxyServer
# 如用防火墙全阻断，保留规则导出/截图作为断网证据

# 1. 断网状态下解压离线包到本地磁盘（路径可含中文/空格）
cd 'D:\课堂 软件\LAITP 离线包'

# 2. 包内自检
cmd /c "check-bundle.bat > check-bundle-output.txt 2>&1"

# 3. 包内一键验收（11 环节；-IncludeFlow 与 -IncludeExtended 必须同用）
powershell -ExecutionPolicy Bypass -File scripts\run_acceptance.ps1 -IncludeFlow -IncludeExtended

# 4. 断网期间人工执行 A2–A9（与 R1 第 5 步相同），记录任何网络请求/超时/失败
```

说明：不得用“代理指向不可用地址”代替真正断网；若只能做到防火墙阻断，须记录规则范围并注明“非物理断网”。验证完成后由网络管理员恢复网络，并记录恢复时间。

### 6.5 验收证据去向

- 断网方式与证据（适配器状态截图、防火墙规则导出、代理设置）、`check-bundle-output.txt`、`acceptance-report.md`、`acceptance-run.json`、界面截图；与 R1 证据放在同一目标机证据目录。
- A12 结果填入[验收清单 §5 记录模板](acceptance-checklist.md)，A12/A13 状态由 lead 按证据更新 §8。
- 相关文档：[离线分发包 §3.3](offline-bundle.md)、[验收清单](acceptance-checklist.md)、[验证证据索引](verification-evidence.md)。

## 7. R5 K230 / K210 板端部署（A15、M4）

| 属性 | 内容 |
| --- | --- |
| 当前状态 | **阻塞**。无 K230/K210 硬件，无固定 SDK/转换工具链，检测链路本身未实现；K210 属 M4，需独立网络与转换链。 |
| 对应验收项 | A15（M3 硬件部分）；K210 属 M4，不能复用 K230 结果。 |
| 解锁后责任人 | 硬件提供方：板卡/摄像头/屏幕/调试线；SDK 提供方：固定版本 CanMV/K230 SDK、nncase、离线安装包与许可；lead：排期与板端验收负责人；工程：转换与板端联调。 |
| 本机还能做什么 | 无板卡与工具链，不能开始实物步骤；可复用现有分类契约的固定样本、SHA-256 与离线打包流程作为模板，并先推进 R6 的检测决策与无硬件工作为 P6–P8 准备输入。不得把转换仿真/电脑验证写成板端可用。 |

### 7.1 内容

按[K230 板端可行性准备 §4](k230-feasibility.md)的顺序做最小验证，再谈检测课堂：

1. **工具链离线可用**：在断网机器上安装并运行 nncase 转换示例；固定并记录版本。
2. **ONNX 一致性**：固定输入样本在 PC 端 ONNX Runtime 与转换前模型输出一致（数值级）。
3. **量化精度**：固定验证集上量化前后指标下降不超过预设阈值（阈值在运行前冻结）。
4. **板端推理**：同一固定样本在实物板端输出与 PC 端一致性检查（类别/框容差）。
5. **实时性**：摄像头输入下达到课堂可接受的帧率与延迟，记录内存峰值。
6. **契约与打包**：板端产物纳入模型包校验流程；离线 ZIP 内含所需工具与固件（许可允许时）。

K210 不在此关键路径：其网络结构、转换器、KPU 算子与内存限制与 K230 不同，必须按 M4 单独验证，不能把 K230 的 kmodel 或转换成功当作 K210 可用（见[检测课可行性规划 §5.4](detection-feasibility.md)）。

### 7.2 为什么现在是阻塞 / 未完成

- 没有 K230/K210 开发板、摄像头、屏幕与调试线；没有指定 CanMV/K230 SDK 与 nncase 版本组合；本机未安装、未验证任何转换工具链（T1–T5 全部未执行）。
- 检测本身未实现：没有检测训练、导出、量化或电脑推理产物可转换；检测契约 Q1–Q8 仍未决策（R6.1），后处理位置与执行方未定。
- 许可与离线分发未确认：固件、nncase、CanMV 及示例工程能否随离线包再分发，需要厂商/产品/法务确认。
- 即使转换成功，也不能代表板端可用：必须有实物板端固定样本比对与实时性记录（见[K230 板端可行性准备 §7](k230-feasibility.md)）。

### 7.3 解锁条件（谁提供什么）

- **硬件提供方（学校/lead/合作方）**：指定型号的 K230 开发板（含内存配置说明）、配套摄像头、屏幕/调试线；K210 板按 M4 另行提供。
- **SDK / 工具链提供方**：CanMV/K230 SDK 与 nncase **指定版本**、离线安装包/固件、版本兼容矩阵与已知算子限制；明确许可证是否允许随离线分发；如不允许，说明教师机转换方案及部署要求（可研 Q8）。
- **lead**：确认 R6.1 检测决策与 P3/P6 排期；指定板端验收负责人与证据归档人；确认是否允许教师机离线转换。
- **课程/硬件负责人**：确认目标板卡、固件、运行时版本及其实测记录责任（[检测待决问题决策建议](detection-decisions.md) §3.8 与 §4.1 门槛 C 的 Q8 机制）。

### 7.4 解锁后的执行步骤（可复制命令）

以下 0–2 步是当前无硬件即可核对的部分；3 步之后须等工具链实际到位，**转换命令以实际 SDK/nncase 版本文档为准，本仓库不得臆造**；P6 执行后把实际命令、版本、SHA-256 与产物摘要回填本节和[K230 板端可行性准备](k230-feasibility.md)。

```powershell
# 0. 现状与既有基线复核（分类链路；不代表检测或板端能力）
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m backend.runtime validate --package "<现有分类模型包目录>"

# 1. T1 获取与版本固定：记录板卡型号、固件/SDK/nncase 版本、来源、SHA-256、许可证与离线安装步骤
#    （按实际提供物填写；缺失项记录为阻塞，不得跳过）

# 2. T2 干净环境安装：在断网目标机/教师机上从本地文件安装并按 SDK 示例完成一次最小转换

# 3. T3 转换可复现：同一 ONNX + 同一转换配置重复转换，归档日志、配置、工具版本与产物 SHA-256

# 4. 量化与转换前后一致性（P7）：校准集从训练数据冻结，按冻结阈值比较；阈值不得事后放宽

# 5. 实物板端固定样本一致性（P8/G5）与实时性/资源（G6）：记录板卡型号、固件、运行时、耗时、内存

# 6. 契约与打包：kmodel/板端运行时纳入模型包校验与离线包；确认许可后再分发
```

前置关系：本项依赖 R6 的检测链路（至少 P2/P4 的格式与导出）与 R6.1 的 Q1/Q3 板端相关子决策；在检测格式与工具链都就绪前，不应向学校承诺板端课程时间表。

### 7.5 验收证据去向

- 转换记录（工具链版本/配置/来源产物 ID/产物 SHA-256）、量化校准清单与前后比较记录、板端固定样本比对记录、帧率/延迟/内存实测记录。
- 按[K230 板端可行性准备 §4](k230-feasibility.md)的 6 条门槛逐项归档；A15 状态由 lead 在取得实物证据后更新 §8，转换成功或仿真通过不得写成板端可用。
- 相关文档：[K230 板端可行性准备](k230-feasibility.md)、[检测课可行性规划](detection-feasibility.md)（§5/§6/§7）、[总体路线与项目大纲 §7](roadmap.md)。

## 8. R6 检测 M3 无硬件前置（P1–P5 可先行）

检测 M3 当前**未实现、未验证**：没有检测标注、数据清单、训练/导出、电脑测试、转换或板端证据；契约校验器仍按任务不支持拒绝检测产物。按[检测课可行性规划 §7](detection-feasibility.md)，P1–P5 可在无板卡条件下先行，P6/P7 需要转换工具链，P8/P9 必须实物硬件 + 课堂数据。本节只列无硬件阶段可做与必须由 lead 先决策的部分。

### 8.1 R6.1 Q1–Q8 决策（门槛 A 六项，必须最先关闭）

| 属性 | 内容 |
| --- | --- |
| 当前状态 | **阻塞**。Q1–Q8 全部未决；[检测待决问题决策建议](detection-decisions.md)只是建议稿，没有决策效力。 |
| 本机还能做什么 | 本机无决策权，只能准备评审材料：核对草案、样例与拒绝场景；本轮仅写本文档，未新增决策或实现。 |
| 相关验收项 | M3（不属 A1–A15；检测能力尚无验收项） |

**内容**：按[检测待决问题决策建议 §4.1](detection-decisions.md)的决策门槛，**P2 定稿前**必须先关闭 **Q1、Q2、Q5、Q6、Q7、Q3**；Q4 的原则部分随 Q3 一并确认（细节 P4 前）；Q8 先定机制（数值在 P7/P8/P9 运行前分别冻结）；Q1 的板端版本线与 Q3 的板端执行方后置到 P6 工具链结论之后。决策顺序建议 Q1 → Q5 → Q7 → Q6 → Q2 → Q3（+Q4 原则）→ Q8 机制；也可按 §4.2 的“最小可行组合”一次打包批准。

**为什么阻塞**：这六项决定检测契约版本线、类别数下限（单类）、坐标口径、空标注、标注文件布局与后处理结构，直接决定 P2 的 Schema 与样例；在未决状态下实现方只能各自猜测，返工与口径分裂风险最高。当前只有建议稿，没有登记决策记录，也没有更新的草案状态。

**解锁条件（谁提供什么）**：

- **lead**：召集并批准评审（按[§4.3](detection-decisions.md)的第一次评审“结构门”），对 Q1–Q8 拍板或明确延后条件；指定决策记录归档位置。
- **课程/验收负责人**：确认课堂可接受度（尤其 Q2 单类检测、Q6 负样本、Q8 阈值责任与冻结时点）。
- **工程负责人**：提出可测口径、维护决策记录模板与后续任务拆分。
- **硬件负责人**：参与 Q1 板端版本线与 Q3 板端执行方（可后置到 P6），提供板卡/固件/工具链信息。
- 输出：决策记录 + 更新[检测待决问题决策建议 §5.2 登记表](detection-decisions.md) + 更新[检测契约与标注/结果格式草案 §5](detection-contract-draft.md)对应 Q 行状态（改为“已决策”不等于“契约已生效/检测已实现”）。

**解锁后的执行步骤（可复制命令）**：

```powershell
# 会前现状核对（草案、样例与非激活隔离；通过也不代表检测可用）
.\.venv\Scripts\python.exe -m pytest tests\test_detection_draft_schemas.py tests\test_detection_dataset_manifest_draft.py tests\test_detection_draft_check.py tests\test_detection_draft_dataset_check.py -q
.\.venv\Scripts\python.exe scripts\detection_draft_check.py --output artifacts\detection-draft
.\.venv\Scripts\python.exe scripts\detection_draft_dataset_check.py --manifest tests\fixtures\detection\dataset-manifest-valid.json

# 评审按检测待决问题决策建议 §4.3 执行：第一次评审关闭门槛 A 六项（Q1/Q5/Q7/Q6/Q2/Q3，附 Q4 原则）
# 每项决策用 §5.1 模板登记，写入 §5.2 登记表，并同步草案 §5 的 Q 行与检测课可行性规划 P1 退出条件

# 决策记录更新后复核文档链接与口径
.\.venv\Scripts\python.exe scripts\check_docs.py
```

**验收证据去向**：决策记录与登记表（[检测待决问题决策建议](detection-decisions.md) §5）、草案状态更新（[检测契约与标注/结果格式草案](detection-contract-draft.md) §5）、P1 退出条件记录（[检测课可行性规划](detection-feasibility.md) §7）。这些是决策记录，**不是能力验收证据**；检测仍为未实现、未验证。

### 8.2 R6.2 P2 定稿（草案 → 正式契约升版）

| 属性 | 内容 |
| --- | --- |
| 当前状态 | **阻塞**（依赖 R6.1；现有 Schema 仍是草案标记（`2.0-draft` / `0.1-draft`），未激活，不在生产加载路径）。 |
| 本机还能做什么 | 决策前不能冻结正式字段；可准备字段映射表与拒绝场景清单。本轮未改 Schema/契约/校验器。 |
| 相关验收项 | M3（P2 退出条件） |

**内容**：门槛 A 关闭后，把检测草案收敛为可评审的正式版本：

- 按 Q1 决定版本线（建议：模型契约 `1.1`、数据集清单 `2.0`、项目格式 `2.0`、消息协议 `1.1`；板端 P6 后另定），分类契约 `1.0` 保持冻结；
- 更新 [检测契约与标注/结果格式草案](detection-contract-draft.md)、`schemas/` 下正式 Schema（不再用 `-draft` 标记）、有效/无效样例、拒绝场景测试；
- 按[模型接口与产物契约 §9](model-contract.md)同步文档、Schema、生产方、消费方与验证五处；P2 定稿≠检测可用，校验器放开与实现属于 P4。

**为什么阻塞**：Q1–Q8 未决则字段、必填性、版本号与样例无法冻结；现有 `schemas/detection/` 只是结构草案（`schemas/detection/README.md` 明确“草案、未激活”），不能作为生产 Schema。

**解锁条件（谁提供什么）**：R6.1 门槛 A 决策完成并登记；lead 批准 P2 定稿范围与评审样例；工程负责人按契约流程排期；课程负责人确认示例类别与标签规则。无需外部硬件。

**解锁后的执行步骤（可复制命令）**：

```powershell
# 1. 现状基线：草案 Schema/样例通过、分类契约未被放宽（当前校验器仍拒绝检测任务）
.\.venv\Scripts\python.exe -m pytest tests\test_detection_draft_schemas.py tests\test_detection_dataset_manifest_draft.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_detection_draft_check.py tests\test_detection_draft_dataset_check.py -q

# 2. 按决策更新正式 Schema、样例与测试后，跑全量回归（确认分类 1.0 行为不变）
.\.venv\Scripts\python.exe -m pytest -q

# 3. 同步契约文档（模型契约版本表、检测草案状态、可行性规划 P1/P2 退出条件）
# 4. 文档链接与口径检查
.\.venv\Scripts\python.exe scripts\check_docs.py
```

**验收证据去向**：正式 Schema 与样例文件、拒绝场景测试结果、契约文档版本表与 P2 评审记录；M3 的最终验收在 P9 另立（[检测课可行性规划 §6/§7](detection-feasibility.md)），A1–A15 不覆盖检测。相关文档：[检测契约与标注/结果格式草案](detection-contract-draft.md)、[模型接口与产物契约](model-contract.md)、`schemas/detection/README.md`。

### 8.3 R6.3 检测数据标注工具与样例

| 属性 | 内容 |
| --- | --- |
| 当前状态 | **未执行**。没有任何检测画框标注界面或导入工具，只有未激活的草案 Schema 与 `tests/fixtures/detection/` 结构样例。 |
| 本机还能做什么 | 无工具可测；可准备标注规范样例与拒绝场景清单（本轮未写代码）。 |
| 相关验收项 | M3（P2/P5 交付物） |

**内容**：为 P2/P5 准备标注能力：

1. 由 lead 决定标注入口（应用内画框还是外部工具导入，可研 Q5）；应用内画框需在 WPF 界面实现（P5），外部导入必须先定义转换格式、坐标/类别校验与摘要绑定，不能直接信任第三方坐标。
2. 提供标注样例与有效/无效样例：类别来自项目类别表、框为整数原图像素、越界/零面积/负值拒绝、空标注与重复框规则、图片/标注同步重命名删除、批次与划分约束。
3. 标注规范：每图框数、最小框尺寸、教师抽查比例、负样本比例与漏标提示；与[检测课可行性规划 §3](detection-feasibility.md)和[检测待决问题决策建议](detection-decisions.md)的 Q5/Q6/Q7 一致。

**为什么未执行**：Q5/Q6/Q7 与可研 Q5（标注入口）未决；应用内画框属 P5，需要 P2 定稿与排期；外部工具方案未批准；当前样例只是结构校验用途（通过 Schema 不等于标注语义合法）。

**解锁条件（谁提供什么）**：R6.1 决策关闭（至少 Q5/Q6/Q7）与 R6.2 P2 定稿；lead 决定标注入口并安排 P5 排期；课程负责人提供标注规范与课堂示例；工程实现工具与导入校验；真实标注数据由学校提供（见 R3）。

**解锁后的执行步骤（可复制命令）**：

```powershell
# 现状：核对草案样例与跨字段校验（草案、非正式，不代表检测能力）
.\.venv\Scripts\python.exe -m pytest tests\test_detection_draft_schemas.py tests\test_detection_draft_dataset_check.py -q
.\.venv\Scripts\python.exe scripts\detection_draft_dataset_check.py --manifest tests\fixtures\detection\dataset-manifest-valid.json

# P5 实现后（命令待界面/脚本落地后补充）：
#   人工标注 10 张样例 → 保存/重开/修改/删除 → 越界、类别越界、图片/标注摘要不一致应被拒绝
#   外部导入方案获批时：先做格式转换 + 摘要/坐标校验，再接入导入
```

**验收证据去向**：标注工具验收记录（截图/自动化 JSON）、标注样例与拒绝场景测试、教师抽查记录；归入 P5 交付物与 M3 证据（[检测课可行性规划 §7](detection-feasibility.md)），不进入 A1–A15。相关文档：[检测课可行性规划 §3](detection-feasibility.md)、[检测契约与标注/结果格式草案](detection-contract-draft.md)、`schemas/detection/README.md`。

### 8.4 R6.4 合成数据回归

| 属性 | 内容 |
| --- | --- |
| 当前状态 | **部分**。已有草案级合成校验脚本与 4 组 draft pytest；正式版本回归未建立，也未接入验证套件。 |
| 本机还能做什么 | 可在决策不影响的范围内扩展草案拒绝场景、准备正式版回归清单；本轮未新增代码/测试。 |
| 相关验收项 | M3（P2/P4 验证） |

**内容**：用合成图片/标注做无硬件回归，覆盖：Schema 结构与必填、框越界/负值/零面积、图片与标注尺寸/摘要不一致、类别上界、空标注、重复框、路径（绝对路径/盘符/反斜杠/`..`）、批次跨划分与测试集冻结等。现有：[`scripts/detection_draft_check.py`](../scripts/detection_draft_check.py)（生成合成图片与草案标注，校验草案 Schema 与 Schema 无法表达的边界规则）、[`scripts/detection_draft_dataset_check.py`](../scripts/detection_draft_dataset_check.py)（清单跨字段校验）、`tests/test_detection_draft_*.py`。这些只验证草案隔离，不改变生产，不代表检测可用。

**为什么是部分**：正式 Schema/版本未定（依赖 R6.2），回归对象仍是 `*-draft`；尚未纳入 `verify_all.py` 或包内验收；检测能力本身未实现。

**解锁条件（谁提供什么）**：R6.2 P2 定稿；lead 批准回归范围与是否纳入 `verify_all`（可放在 P4/P5 阶段）；工程升级为正式回归并维护样例。无需外部硬件。

**解锁后的执行步骤（可复制命令）**：

```powershell
# 现状草案回归（非正式；通过不代表检测可用）
.\.venv\Scripts\python.exe -m pytest tests\test_detection_draft_schemas.py tests\test_detection_dataset_manifest_draft.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_detection_draft_check.py tests\test_detection_draft_dataset_check.py -q
.\.venv\Scripts\python.exe scripts\detection_draft_check.py --output artifacts\detection-draft
.\.venv\Scripts\python.exe scripts\detection_draft_dataset_check.py --manifest tests\fixtures\detection\dataset-manifest-valid.json

# P2 定稿后：用正式 Schema/样例重写对应用例，并接入验证套件（是否纳入 --quick/--ui 由 lead 决定）
```

**验收证据去向**：pytest 输出、合成数据输出目录清单/摘要、纳入验证套件的报告；在正式版本完成前必须标注“草案/非正式”。相关文档：[验证证据索引 §3](verification-evidence.md)、`schemas/detection/README.md`（§8 校验方式）、[检测课可行性规划 §7](detection-feasibility.md)。

### 8.5 R6.5 P3/P4/P5（无硬件可做的其他部分）

| 属性 | 内容 |
| --- | --- |
| 当前状态 | **部分**：仅完成 P3/P6 前置的草案探测（SSDLite 与 fasterrcnn，各本机单次，见下），P3/P4/P5 主体未执行（未排期、未开始）。 |
| 本机还能做什么 | P3–P5 不依赖板卡，可在 lead 排期后推进；决策前只能准备候选模型清单、许可证核对、CPU 基线与不训练的可行性探测（已完成，见下），不得先实现检测格式，也不得把探测结果写成 P3/P4/P5 结论。 |
| 相关验收项 | M3（P3/P4/P5 退出条件） |

**内容**：

- **前置可行性探测（草案工具，已做；SSDLite 与 fasterrcnn 各本机单次）**：2026-11-19 新增并运行 `scripts/detection_draft_probe.py`（草案工具、未激活、不接入生产），对 torchvision 检测模型做 CPU 实例化、随机输入前向、opset 17 ONNX 导出、算子/NMS/控制流统计与 onnxruntime 输出形状探测。SSDLite320-MobileNetV3-Large（`weights=None`、随机初始化、`num_classes=3`，结果写入 `artifacts/detection-draft/probe-ssdlite.json`，本机生成、忽略提交）：ONNX 8.98 MB、1,481 节点、43 种算子，**无 `NonMaxSuppression`、无自定义 domain**，输出 `boxes(128,4)`/`scores(128)`/`labels(128)` 为原始检测头（图内无 NMS/最终筛选）；同时图含 `If` 等控制流算子，`boxes` 数值在模型输入像素尺度。FasterRCNN-MobileNetV3-Large-320-FPN（同条件，结果写入 `artifacts/detection-draft/probe-fasterrcnn.json`）：ONNX 约 75.94 MB、1,515 节点、53 种算子，同样无 `NonMaxSuppression`/自定义 domain，但含 `If` 与 `RoiAlign`，参数约 1,896 万（约为 SSDLite 的 8.5 倍）；输出名已按模型实际字典顺序声明为 `boxes`/`labels`/`scores`，可按名称对应类型（见[检测课可行性规划 §4.5](detection-feasibility.md)）。两个候选的 CPU 实例化/导出均可行，仍只作 P3/P6 风险筛查，**不训练、不评估精度、不转换、不量化、不上板**，不能外推转换或板端能力。
- **P3 训练可行性实测**：在决策与 P2 定稿后，用合成或公开小数据并行比较至少两个候选检测模型（如 YOLO 小模型与 SSDLite-MobileNetV3 一类），记录每轮/总训练耗时、内存峰值、模型体积、ONNX 导出与一致性、许可证与转换风险，决定课堂方案（课堂内/教师机/跨课时）与唯一原型候选；**当前没有任何检测训练耗时实测，不能承诺一节课内完成**（见[检测课可行性规划 §4.4](detection-feasibility.md)；上一条探测不含训练，不能替代本项）。
- **P4 检测后端链路**：标注校验、检测数据集清单构建/校验、检测训练、导出检测产物包、电脑端加载/评估/固定样本一致性、兼容与拒绝场景测试、跨进程/跨课时恢复。
- **P5 标注与电脑测试界面**：画框/改框/删除、类别选择、保存恢复、数据检查、训练入口与进度/取消、检测结果渲染与电脑测试。

**为什么主体未执行**：Q1–Q8 未决、P2 未定稿；候选模型、许可证（可研 Q6）与课堂方案（可研 Q4）未决；训练依赖与权重离线获取方式未记录。已完成的前置探测只是不训练的结构/导出筛查（见上），不构成 P3 训练实测、验收证据或 P4/P5 实现。

**解锁条件（谁提供什么）**：R6.1 决策 + R6.2 P2 定稿；lead 批准 P3–P5 排期与验收人；工程记录训练依赖/预训练权重版本、SHA-256、许可证与离线获取方式（沿用[数据与运行基线](data-and-runtime-baseline.md)记录方式）；课程负责人确认课堂方案取舍；P3 的正式结论需目标机级别 CPU 实测（目标机选定见 R1，目标机规格可研 Q9）。

**解锁后的执行步骤（可复制命令）**：

```powershell
# 环境与分类基线复核（不是检测实现；仅确认现有链路与 CPU 参考）
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m benchmarks.m0_benchmark --output artifacts\benchmark-m0

# P3/P6 前置探测（草案工具，未激活；不训练、不发布、不接入生产）：
# 只做 SSDLite 与 fasterrcnn 的 CPU 实例化/前向/ONNX 导出与算子/输出形状探测，不替代 P3 训练实测
.\.venv\Scripts\python.exe -m pytest tests\test_detection_draft_probe.py -q
.\.venv\Scripts\python.exe scripts\detection_draft_probe.py --skip-fasterrcnn --output artifacts\detection-draft\probe-ssdlite.json
.\.venv\Scripts\python.exe scripts\detection_draft_probe.py --model fasterrcnn --output artifacts\detection-draft\probe-fasterrcnn.json

# 说明：检测训练/评估命令尚不存在——P3 候选模型确定、训练依赖与权重离线就绪后，
# 由工程新增命令与脚本并回填本节；不得用上述分类命令或草案探测冒充检测能力，也不得先承诺课堂课时。
```

**验收证据去向**：P3 实测报告（耗时/内存/体积/ONNX 一致性/许可证结论）、P4/P5 代码与测试、固定样本与拒绝场景记录、电脑测试记录；按[检测课可行性规划 §7](detection-feasibility.md)的 P3/P4/P5 退出条件归档；草案探测 JSON（`artifacts/detection-draft/probe-ssdlite.json` 与 `artifacts/detection-draft/probe-fasterrcnn.json`，忽略提交）与 `tests/test_detection_draft_probe.py` 结果只作前置风险筛查，**不是** P3/P4/P5 验收证据；M3 最终验收在 P9（需硬件与课堂数据）。相关文档：[检测课可行性规划](detection-feasibility.md)（§4/§7/§8）、[总体路线与项目大纲 §7](roadmap.md)、[检测契约与标注/结果格式草案](detection-contract-draft.md)。

## 9. 需 lead / 学校补充的信息

以下信息未齐前，对应小节只能保持阻塞；请 lead 在信息确定后回填本节并通知执行人。

| 类别 | 需要补充的信息 | 找谁 / 用途 |
| --- | --- | --- |
| 目标机 | 干净 Windows 10/11 x64 机器型号/数量、系统版本、内存与磁盘、普通用户账号类型（本地/域）、可用日期、解压路径规划 | 学校 / 机房管理员；R1 解锁前提 |
| 断网窗口 | 可断网或隔离的时段、断网方式、网络恢复责任人、防火墙/代理策略 | 学校 IT / 网络管理员；R4 解锁前提 |
| 摄像头 | 管理员启用 `HD Webcam` 或更换摄像头的责任人与日期；普通用户摄像头权限策略；用户是否同意恢复摄像头自动化测试 | 机器管理员 + 用户/lead；R2 解锁前提 |
| 课堂数据 | 课堂图片提供人、类别定义、每类样本量与批次、独立测试集、采集场景、肖像/隐私授权与保存期限、40 分钟课堂安排与现场教师 | 学校 / 授课教师 + lead；R3 解锁前提 |
| K230/K210 | 板卡型号与数量、摄像头/屏幕/调试线、CanMV/K230 SDK 与 nncase 指定版本、离线安装包/固件、许可与再分发确认、到货日期、板端验收负责人 | 硬件/SDK 提供方 + lead；R5 解锁前提 |
| 检测决策 | Q1–Q8 决策人（lead/课程/验收/工程/硬件角色）、评审日期、P2 定稿负责人、P3–P5 排期、候选模型许可证结论（可研 Q6）、课堂方案（可研 Q4）、教师机离线转换是否允许（可研 Q8） | lead + 课程负责人 + 工程负责人；R6 解锁前提 |
| 验收归档 | 目标机验收证据归档人与审核人、板端验收负责人、A10/A14 记录审核人、证据保存位置与期限 | lead；全部验收项的证据去向 |

补充说明：

- 表中的“可研 Q4/Q5/Q6/Q8/Q9”指[检测课可行性规划 §8.2](detection-feasibility.md)的待决问题；与[检测待决问题决策建议](detection-decisions.md)的 Q1–Q8 编号不同，引用时必须带文档名（编号规则见该建议稿 §2.2）。
- 信息到位后，先更新本节，再把对应小节的“当前状态”改为实际结果并附证据路径；在此之前不得在汇报中写成已解锁或已通过。

## 10. 检查与未做事项（2026-11-20 第 250 轮）

### 10.1 本轮已做（2026-11-20 第 250 轮）

- 只读交接审计：核对 R1–R6.5、状态报告外部阻塞/未验收项、关键口径（11 环节、451/64/16、A 项 9/4/1/1、检测草案未激活、摄像头已停）与 `dist/handoff/`（双包与 `.sha256`、README、teacher-quickstart、acceptance-card、acceptance-checklist、verification-evidence、acceptance-report-sample、交接说明、handoff-manifest）；运行 `scripts/check_docs.py` 与 `scripts/check_state.py` 通过。
- 最小修正：更新过期轮次/日期表述、状态报告第 249 轮验证记录的 PASS/SKIP 计数，并补全 README 的交接目录清单；重新生成 `dist/handoff/`（未重建 ZIP）。未改代码、Schema、契约、A1–A15 验收状态、`artifacts/` 或实现文件，未提交 git。
- 历史（2026-11-19 第 216 轮）：新增本文档 `docs/remaining-work.md`。
- 在[项目状态报告 §5 主要文件](status-report.md)与[总体路线与项目大纲 §10](roadmap.md#10-当前待落地事项)末尾加入指向本文的链接。
- 运行 `.\.venv\Scripts\python.exe scripts\check_docs.py`，结果 `ok: true, problems: []`（链接与既有文档口径一致）。
- 未修改代码、Schema、契约、A1–A15 验收状态、`artifacts/acceptance-local.json` 或其他实现文件；未提交 git。
- 2026-11-19 按当时正式包构建更新：一键验收统一为 11 环节（新增严格验收正向、自检幂等性复核），补充“中文+空格路径、非提权进程”通过限定条件与未覆盖环境（干净目标机/普通用户/断网）；同步 A6 严格验收正向界面证据与 A13 仍为部分的口径；记录包内已排除 `__pycache__`/pyc、“自检 → 验收 11/11 → 自检”幂等通过（清单 18,169 文件，当时；当前为 18,172 文件）；同步测试 418 项、Core 64 项、`check_state` 10 项（当时；当前为 483 项、Core 64 项、`check_state` 11 项）。本次更新只改文档（另同步 `status-report`/`acceptance-checklist` 各一处文件数），未重新执行验收、未打包。

### 10.2 本轮未做（2026-11-20；不得视为已执行或已通过）

- 未运行完整 `scripts/verify_all.py --ui`，未打包、未重建离线包，未提交 git。
- 未在目标机、真正断网、普通用户（受管/域环境）下执行验收；未启用物理摄像头；未采集课堂真实数据；未做 K230/K210 转换或板端验证。
- 未做出检测 Q1–Q8 的任何决策，未修改检测草案状态，未实现检测标注/训练/导出/推理/转换；未运行第 8 节列出的检测草案测试（本轮只做文档）。
- 本文中的命令是解锁后的操作步骤，执行前需按实际环境确认路径与版本；执行结果以实际输出和证据为准。

## 11. 相关文档

- [总体路线与项目大纲](roadmap.md)：里程碑、M3/M4 范围与阶段退出条件；[§10 当前待落地事项](roadmap.md#10-当前待落地事项)。
- [项目状态报告](status-report.md)：已实现能力、本机验证证据与外部阻塞；[§3 外部阻塞与未验收项](status-report.md#3-外部阻塞与未验收项)。
- [目标机离线验收清单](acceptance-checklist.md)：A1–A15、判定规则、记录模板与[§8 当前状态矩阵](acceptance-checklist.md#8-当前状态矩阵2026-11-19)。
- [验证证据索引](verification-evidence.md)：可复现命令、产物与目标机留证建议。
- [离线分发包](offline-bundle.md)：构建/校验命令、包内容与净环境模拟证据。
- [真实数据验证](real-data-validation.md)：公开数据结果与课堂演练时间预算。
- [摄像头能力](camera.md)：设备状态、应用内采集与错误提示。
- [检测课可行性规划](detection-feasibility.md)：P1–P9、G0–G7 门槛与待决问题。
- [检测契约与标注/结果格式草案](detection-contract-draft.md)：检测契约候选文本（草案，未激活）。
- [检测待决问题决策建议](detection-decisions.md)：Q1–Q8 建议与决策记录模板（建议稿，未决策）。
- [K230 板端可行性准备](k230-feasibility.md)：板端前置条件、未知项与 6 条验证门槛。
- [模型接口与产物契约](model-contract.md)：版本兼容、交接校验与验收阈值规则。
