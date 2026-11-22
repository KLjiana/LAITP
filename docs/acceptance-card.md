# 目标机验收操作卡（一页版）

本卡用于**干净 Windows x64 目标机**上快速执行离线包验收；完整项目与判据见[目标机离线验收清单](acceptance-checklist.md)。本卡不代表任何项已通过，结果以现场输出与人工核对为准。

## 1. 准备

- 一台可登录的 Windows 10/11 x64 机器，**普通用户**（非管理员）账号更接近目标场景；卷屏/远程断开会导致窗口类检查失败，需保持本地可交互桌面。
- 准备断网窗口（飞行模式/拔网线/隔离网络），并记录断网方式。
- 解压目录建议**短路径**，可含中文与空格，但避免过长（如 `D:\LAITP 验收`）。
- 从交接目录取得 `laitp-offline-lean.zip` 与 `.sha256`，先核对：

```powershell
Get-FileHash .\laitp-offline-lean.zip -Algorithm SHA256
Get-Content .\laitp-offline-lean.zip.sha256
```

两行摘要必须一致；不一致不要继续。

## 2. 解压与自检

```powershell
Expand-Archive .\laitp-offline-lean.zip -DestinationPath .\laitp
cd .\laitp
.\check-bundle.bat
```

看到自检通过（清单卫生、启动脚本指向、桌面自包含、check-bundle.bat 内容、清单摘要、Python 依赖、推理、训练报告、桌面启动、首次自检）后继续。若失败，先看同目录命令行输出与 `artifacts\` 下日志。

## 3. 一键验收（11 个环节）

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_acceptance.ps1 -IncludeFlow -IncludeExtended
```

- 需**可交互桌面**，全程约 5–8 分钟（受机器负载影响）。
- 脚本会自动设置 UTF-8 控制台编码，兼容中文 Windows 默认 CP936；无需手动 `chcp`。
- “训练与预测”环节含界面批量预测与模型对比；“自检幂等性复核”会在结束时再次核对包内清单。
- 界面步骤失败自动单次重试并留痕：首次失败（非 0 退出码或超时）后自动重跑一次；重试通过记为 pass 并在 `warnings` 记录首次失败，两次均失败判失败。

## 4. 看结果

```powershell
Get-Content .\acceptance-run.json -Raw
Get-Content .\acceptance-report.md -Raw
```

- `acceptance-run.json` 的 `ok` 与 `steps` 是机器判据；`acceptance-report.md` 含系统、用户/是否管理员、CPU/内存/磁盘余量、长路径支持状态与包目录长度、包身份与步骤表，可直接归档。
- 失败时保留 `acceptance-run.json`、`acceptance-report.md`、`artifacts\*.stderr.txt`，并记录现象。

## 5. 现场记录表（手填）

| 项目 | 记录 |
| --- | --- |
| 目标机型号 / Windows 版本 | |
| 用户账号 / 是否管理员 | |
| 断网方式与时间 | |
| 解压绝对路径与长度 | |
| 包 SHA-256（前 12 位） | |
| check-bundle 结果（时间） | |
| run_acceptance 结果（11 步 / ok / 时间） | |
| 界面人工核对（建项目、导入、训练、预测、保存恢复） | |
| 验收人 / 日期 / 签字 | |

## 6. 常见失败速查

| 现象 | 处理 |
| --- | --- |
| 第 1 步“文件大小/摘要不符” | 确认使用最新包（清单已排除 `__pycache__`/pyc）；重新解压到新目录 |
| 第 2 步窗口检查失败 | 解锁桌面/确认不是 RDP 断开或服务会话；先关闭残留的 `Laitp.Desktop`/`python` 进程再重跑 |
| 某个界面步骤偶发超时/失败（其余步骤正常） | 脚本对界面步骤失败自动重试一次；重试通过会记为 pass 并在 `warnings` 留痕；两次失败判失败。若仍失败，关闭残留进程后重跑一次，保留结果并注明“偶发” |
| 界面步骤长时间无响应 | 脚本对界面步骤设有界超时（180–600 s）；超时会终止该步骤进程树并自动重试一次，两次均失败才判为失败并写入 `warnings`，其余步骤继续，不会无限挂起 |
| 界面输入框偶发未写入 | 界面脚本对关键输入框采用多轮设置+回读校验（最多 4 轮、每轮回读 1 s）；仍失败时该步骤会判失败并进入透明重试流程 |
| 上次运行残留窗口/进程 | 脚本启动时会自动清理**本包目录下**的残留 `Laitp.Desktop`/`python` 进程（不影响其它程序），并在 `warnings` 中记录 |
| 第 8/9/10 步“无法解析脚本 JSON 输出” | 使用含编码修复的新版脚本；旧包先在控制台执行 `chcp 65001` |
| “管理员：否” | 正常，不代表失败；普通用户是验收要求 |
| 双击 exe 提示“必须安装 .NET Desktop Runtime” | 不要运行 `desktop/src/.../bin` 下的开发构建 exe；请用分发包根目录的 `start-desktop.bat` 或 `desktop/app/Laitp.Desktop.exe`（包内为自包含发布） |
| 耗时明显偏长 | 冷启动/杀毒扫描/负载；以 `status` 判断，不以耗时判失败 |
| 路径过长 | 报告含“长路径支持/包目录长度”。未启用长路径（`LongPathsEnabled=0`）且完整路径接近 260 字符时，解压/启动可能失败；请换更短解压目录（如 `D:\LAITP`）。本机在启用长路径时以约 300 字符路径解压+自检通过（仅本机证据） |

更多排查见[验收清单 §7 常见失败与排查](acceptance-checklist.md#常见失败与排查)。
