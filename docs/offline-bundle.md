# 离线分发包（M2 开发期基础）

编制日期：2026-11-17；最近更新：2026-11-23

状态：已能生成可校验的离线 ZIP；**精简完整包**（不含 wheel，内置便携 Python 与自包含桌面）约 266 MiB，在本开发机解包验证了逐文件摘要、包内 Python 依赖导入、推理、训练报告、启动脚本与桌面启动，并在**含中文与空格的路径**下用包内 Python 走通“建项目 → 导入 → 训练 → 发布 → 预测 → 项目校验”。仍未在干净 Windows 机器、真正断网环境或普通用户权限下验证，因此不构成 M2 验收通过。

所属路线：[总体路线](roadmap.md) 第 9 节（离线分发与平台验证）。相关：[真实公开数据验证](real-data-validation.md)、[数据与运行基线](data-and-runtime-baseline.md)。

## 1. 构建与校验命令

```powershell
# 1) 便携 Python（内置 torch/onnxruntime 等运行依赖，剔除静态库与头文件）
.\.venv\Scripts\python.exe scripts\build_portable_python.py

# 2) 自包含桌面程序（无需目标机预装 .NET 运行时）
.\.dotnet\dotnet.exe publish desktop\src\Laitp.Desktop\Laitp.Desktop.csproj `
  -c Release -r win-x64 --self-contained true -o dist\desktop-selfcontained

# 3) 完整离线包（便携 Python + 自包含桌面 + wheel + 演示模型）
.\.venv\Scripts\python.exe scripts\build_offline_bundle.py `
  --desktop-dir dist\desktop-selfcontained --python-dir dist\python-portable `
  --output dist\laitp-offline-full.zip

# 3b) 精简完整包（依赖已在便携 Python 中，不含 vendor/wheels）
.\.venv\Scripts\python.exe scripts\build_offline_bundle.py --skip-wheels `
  --desktop-dir dist\desktop-selfcontained --python-dir dist\python-portable `
  --output dist\laitp-offline-lean.zip

# 4) 校验：解包 → 逐文件 SHA-256 → 包内 Python 导入 → 推理 → 报告 → 启动脚本 → 桌面启动
.\.venv\Scripts\python.exe scripts\verify_offline_bundle.py --bundle dist\laitp-offline-lean.zip

# 5) 离线完整流程（中文/空格路径，全部后端命令用包内 Python）
.\.venv\Scripts\python.exe scripts\verify_offline_flow.py --bundle dist\laitp-offline-lean.zip

# 5b) 净环境模拟（清空 PATH 中 Python/.NET、清除 PYTHON*、代理指向不可用地址）
.\.venv\Scripts\python.exe scripts\verify_offline_flow.py --bundle dist\laitp-offline-lean.zip --clean-env

# 6) 一键验证（单元测试 + 构建 + Core 检查 + 包校验 + 净环境流程 + 界面自动化）
.\.venv\Scripts\python.exe scripts\verify_all.py --ui
```

可选参数：`--skip-wheels`、`--skip-demo`、`--skip-desktop`、`--skip-python`、
`--desktop-dir <目录>`、`--python-dir <目录>`、`--output <路径>`。

脚本不负责构建 Python 与桌面程序：打包前先生成上述产物，再用对应参数指定。

## 2. 包内容（本次构建）

四次构建对比：

| 构建 | 桌面程序 | Python | wheel | ZIP 大小 | 清单内文件 |
| --- | --- | --- | --- | --- | --- |
| 框架依赖（首版） | 7 文件 337 KB | 外置 | 有 | 688,213,132 B（约 656 MiB） | 157 |
| 自包含桌面 | 466 文件 167.96 MB | 外置 | 有 | 758,131,608 B（约 723 MiB） | 617 |
| 完整包（当前，含 wheel） | 468 文件 193.52 MB | 便携 17,590 文件 614.48 MB | 33 个 wheel，684.59 MB | 950,153,738 B（约 906 MiB） | 18,206 |
| **精简完整包（当前）** | 468 文件 193.52 MB | **便携 17,590 文件 614.48 MB** | 无 | **278,933,028 B（约 266 MiB）** | **18,172** |

精简完整包 SHA-256：

```text
0b494a5af8139e232cb6cc886a80e4d89c18c81cd43c3a0a382593b717a28ef5
```

（此构建包含界面自检、启动自动自检、UTF-8 输出修复、新建/批量导入/测试集导入/摄像头设备选择·拍照·连拍·高帧率预览·错误提示/训练/预测/历史导出/项目编辑控件；桌面目标框架 `net8.0-windows10.0.19041.0`；便携 Python 已剔除 `__pycache__`，包内自带校验脚本、`check-bundle.bat` 一键自检与 `docs/teacher-quickstart.md` 老师指引。）

完整包 SHA-256：`8c01ee4885613429ecfea238d7e0e0756b6a477af9edc896be40ee40e16db66f`（本机解包校验通过：18,206 个文件摘要、包内 Python 依赖导入、推理、训练报告、桌面启动与首次自检）。

选择建议：目标机首次部署/依赖修复用**完整包**（带 wheel，可重装依赖）；日常分发/课堂使用用**精简包**（体积约 266 MiB，依赖已在便携 Python 内）。

`manifest.json` 记录格式版本、构建时间、每个文件的相对路径/大小/SHA-256、组件来源与总量，以及运行前提（含 `python_embedded`、`desktop_self_contained` 标记）。

## 3. 解包校验结果（本机）

### 3.1 包内容校验（精简完整包）

| 检查 | 结果 |
| --- | --- |
| 解包 | 成功 |
| 清单摘要 | **18,172 个文件全部匹配** |
| 包内 Python 依赖导入 | 成功：torch 2.8.0+cpu、onnxruntime 1.23.2 |
| 解包推理 | 成功（`art-run-real-0001`） |
| 训练报告 | 成功（0.917） |
| 启动脚本 | 存在 `start-desktop.bat` |
| 桌面程序启动 | 成功（存活 4 秒，`LAITP_PYTHON` 指向包内解释器） |
| 包内现场自检 | 通过（`python\python.exe scripts\verify_offline_bundle.py --extracted .` 或双击 `check-bundle.bat`：清单卫生、启动脚本指向、check-bundle.bat 内容、manifest 环境声明一致、第一方文本开发机路径扫描、桌面自包含检查通过，18,172 文件摘要 + 推理 + 报告 + 桌面 + 自检） |
| 启动耗时（解包目录） | 首次窗口 5.11 s；暖启动窗口 0.83 s、自动自检完成 1.59 s（`scripts/measure_startup.ps1`） |
| 首次运行自检 | **通过**：`repository_root`、`python`、`backend_import`、`worker_predict` 全部 ok |
| 自检失败场景 | 错误 `LAITP_PYTHON` 路径时自检返回失败（exit≠0），且 `python` 检查项标记失败 |

当前精简包的桌面程序已包含界面“环境自检”按钮与启动时后台自动自检；界面内点击流程已由 UIAutomation 脚本覆盖（冒烟、主流程、摄像头、净环境；摄像头自动化测试自 2026-11-18 起按要求停止，相关结果为历史记录），详见[桌面外壳](desktop-shell.md)与[验证证据索引](verification-evidence.md)。

首次运行自检：

```powershell
desktop\app\Laitp.Desktop.exe --self-test self-test-result.json
```

结果 JSON 包含 `ok`、仓库根目录、Python 路径、系统信息与逐项检查（仓库识别、Python 定位、后端导入、工作进程预测）；界面启动前可先运行它判断环境是否就绪。退出码 0 表示通过。

框架依赖/自包含/完整包的历史校验结果见上一轮记录与 `manifest.json`；便携 Python 构建时剔除 `torch/lib` 下 20 个静态库（约 2.77 GB）、头文件、基础解释器测试包与 pip 等开发组件，仅保留运行所需 DLL 与依赖。

### 3.2 离线完整流程（中文/空格路径）

`scripts/verify_offline_flow.py` 把精简包解压到 `LAITP 离线 验证 / 包 目录（含空格）`，全部后端命令使用包内 `python/python.exe`：

| 步骤 | 结果 |
| --- | --- |
| 创建项目（`课堂 项目`，3 类） | 成功 |
| 导入图片（每类 2 训练批次 × 8 张 + 测试 4 张） | 成功；清单 train 24 / val 24 / test 12 |
| 数据检查 | 通过（0 问题） |
| 训练（3 轮、64×64、真实权重） | 成功，`train-run-offline-0001` |
| 发布（导出 ONNX 并切换当前模型） | 成功，`art-run-offline-0001` |
| 训练报告 | 成功（该 3 轮小样本验证准确率 0.417） |
| 预测 | 成功（返回类别概率） |
| 项目校验 | 通过 |

说明：该流程用合成彩色图片、仅 3 轮训练，准确率与预测标签**不代表模型质量**，只用于证明包内 Python 在中文/空格路径下可完成完整课堂链路。

### 3.3 净环境模拟（清空 PATH / Python 变量 / 断网代理）

`--clean-env` 模式下，所有子进程只保留 `C:\WINDOWS\System32;C:\WINDOWS` 的 PATH，清除 `PYTHONHOME/PYTHONPATH` 等变量，并设置不可用代理 `http://127.0.0.1:9`（模拟断网，非真正断网）：

| 检查 | 结果 |
| --- | --- |
| 包内 Python（`sys.executable`） | 指向解包目录内 `python\python.exe` |
| 建项目 / 导入 / 数据检查 | 通过（train 24 / val 24 / test 12） |
| 训练 / 发布 / 报告 | 成功；`art-run-offline-0001`；报告 0.417（合成小样本） |
| 预测 / 项目校验 | 成功 |
| 桌面启动（净环境 + 包内 Python） | 成功（存活 4 秒） |
| 桌面 `--self-test`（净环境） | **通过**：`repository_root`、`python`、`backend_import`、`worker_predict` |

该模拟验证了“无需系统 Python/.NET、无需联网配置”的前提基本成立，但仍不是干净 Windows 机器与真正断网验收。

净环境下的**界面自动化**（同一套最小 PATH、不可用代理、包内 Python）：
- `ui_flow.ps1 -CleanEnv`：打开项目 → 检查数据（通过）→ 训练并发布（`art-run-20261118050036`）→ 预测（成功）
- `ui_camera.ps1 -CleanEnv`：设备检测 → 预览（约 21 fps）→ 连拍 → 拍照导入，全部通过

### 3.4 界面自动化（解包目录）

把精简包解压到含中文与空格的临时目录，用 `scripts/ui_smoke.ps1`（Windows UI Automation）对包内桌面程序做界面冒烟：

| 场景 | 结果 |
| --- | --- |
| 正常环境（`LAITP_HOME`/`LAITP_PYTHON` 指向解包目录） | 窗口定位成功；自动自检状态“就绪（环境自检通过）”；点击“环境自检”后状态“环境自检通过，可以开始使用”，消息区 4 项全部通过（含 `worker_predict：成功`） |
| 缺 Python（错误的 `LAITP_PYTHON`，无 `.venv` 回退） | 自动自检后状态“环境自检未通过，请检查运行环境”，消息区显示“失败 python：未找到 Python”与修复提示；手动点击后显示“环境自检未通过（1 项失败）” |
| 打开项目 + 检查数据（解包目录内项目） | 状态“已打开项目，当前模型：art-run-offline-0001”，类别“杯子 / 书本 / 笔袋”；点击“检查数据”后状态“数据检查通过，可以开始训练” |
| 完整界面闭环（包内 Python，项目副本） | 轮数=1 → “训练并发布” → 状态“训练与导出完成，当前模型：art-run-20261117234630”；填测试图片 → “预测” → 状态“成功”，产物 ID 一致 |
| 新建项目 + 导入（解包目录内，包内 Python） | 新建“界面自动化项目”（杯子/书本）：状态“已创建并打开项目”；4 次导入均“导入完成”；清单合计 24 张（训练 12 / 验证 12）；检查数据通过 |
| 批量导入（解包目录内，包内 Python） | 新建项目后点击“批量导入”：状态“批量导入完成：新增 20，重复 0，无效 0；批次 4”；清单合计 20 张（训练 10 / 验证 10）；检查数据通过 |
| 测试集导入（解包目录内，包内 Python） | 勾选“导入为测试集”后逐类导入：清单显示“测试 3/类”，合计 26 张（训练 10 / 验证 10 / 测试 6）；检查数据通过 |
| 摄像头拍照导入（解包目录内，包内 Python） | DroidCam Video：设备下拉框存在；“摄像头：DroidCam Video（1 个可用）”；预览“20.9 fps，167 帧”；连拍 3 张“新增 1、重复 2”；每类拍照 2 次共 4 次成功并导入；清单合计 5 张；静态画面触发重复内容校验（预期） |
| 项目保存与恢复（解包目录内，包内 Python） | 新建 → 导入 → 训练并发布（`art-run-20261118000414`）→ 关闭程序 → 重新打开：状态“已打开项目，当前模型：art-run-20261118000414”，类别、数据清单与检查结论均恢复 |
| 训练历史导出（解包目录内，包内 Python） | 打开含历史运行的项目（`run-real-0001`，91.7%）→ 点击“导出选中运行”：状态“已导出运行 run-real-0001，当前模型：art-run-real-0001-2”，导出包 `manifest.json` 存在 |
| 项目编辑 + 严格验收（解包目录内，包内 Python） | 项目改名 → “项目已改名”；添加/删除类别 → 类别列表正确变化；类别改名 `T恤`→`短袖`；样本重命名/删除成功；严格验收检查显示“数据检查未通过（3 个问题）” |

这验证了 WPF 界面本身能启动、响应按钮并正确展示成功/失败反馈，且在解包目录内用包内 Python 完成了“新建 → 导入 → 检查 → 训练 → 发布 → 预测”的完整界面闭环；仍属单机模拟，不等于干净机器验收。

本次构建已包含 UTF-8 输出修复、全部主流程/编辑控件 AutomationId、八个界面自动化脚本与摄像头控件（设备选择/检测刷新/拍照/连拍/高帧率预览）：`ui_flow.ps1`、`ui_create_import.ps1`（含 `-TreeSource`/`-TestSource`）、`ui_restore.ps1`、`ui_export_history.ps1`、`ui_edit.ps1`、`ui_camera.ps1`，均可对解包目录运行。

### 3.5 包内现场自检

包根还包含 `README.md`（项目总览、快速开始与文档索引）与 `README.txt`（包内说明）；包内 `docs/` 为仓库全部文档副本（含 `teacher-quickstart.md`、`known-limitations.md`、`third-party-notices.md` 等）。`desktop/app` 为自包含发布（`runtimeconfig` 使用 `includedFrameworks`，含 `coreclr.dll`/`hostfxr.dll`），目标机无需预装 .NET Desktop Runtime；自检会显式校验清单卫生、桌面自包含、`start-desktop.bat` 指向、`check-bundle.bat` 内容、`manifest.json` 环境声明（`platform`/`python_embedded`/`desktop_self_contained`）与包内实际一致，并扫描清单内第一方文本是否含开发机绝对路径。不要运行 `desktop/src/.../bin` 下的开发构建 exe（那是框架依赖版本，会提示缺少 .NET Desktop Runtime）。包内自带 `scripts/verify_offline_bundle.py`，以及界面自动化脚本 `ui_smoke.ps1`、`ui_flow.ps1`、`ui_camera.ps1`、`ui_preview_stability.ps1`、`ui_create_import.ps1`、`ui_restore.ps1`、`ui_export_history.ps1`、`ui_edit.ps1`、`measure_startup.ps1`、`run_acceptance.ps1`（一键验收：基础 3 步，加 `-IncludeFlow -IncludeExtended` 可扩展到 11 步，含演示导入、训练预测、保存恢复、数据体检、批量历史汇总、“严格验收（正向）”与“自检幂等性复核”；其中“训练与预测”将执行界面批量预测，包内存在示例模型包时执行模型对比，“批量历史汇总”将优先基于流程项目的非空历史，“严格验收（正向）”用包内 Python 对流程项目执行 `backend.project check-dataset --require-test --min-train/val/test` 验证严格验收正向链路，阈值仅用于链路验证、不作为课堂验收门槛；新增第 10/11 步后正式包已实测 11/11 通过（2026-11-19），界面脚本关键输入框多轮设置+回读校验；界面步骤失败自动单次重试并留痕（有界超时 180–600 s；首次失败记入 `warnings`，重试通过记为 pass，两次失败判失败），验收报告新增“包身份”（manifest format/created_at/文件数/总字节/manifest SHA-256））、`project_archive.py`（项目归档）、`batch_history_export.py`（批量历史汇总）与 `dataset_report.py`（数据体检）；解压后可直接用包内 Python/桌面运行自检，无需开发环境：

```powershell
python\python.exe scripts\verify_offline_bundle.py --extracted .
```

也可**双击 `check-bundle.bat`**（自动切换 UTF-8 代码页、运行同一自检并暂停显示结果）。本机实测（全新解压目录）：**通过**——18,172 个清单文件摘要全部匹配、清单卫生/启动脚本/自检脚本/桌面自包含/manifest 环境声明等结构检查通过、第一方文本无开发机绝对路径、包内 Python 导入成功、解包推理 `art-run-real-0001`、训练报告 0.917、`start-desktop.bat` 存在、桌面启动存活 4 秒、首次自检四项通过、错误 Python 失败场景识别正常；批处理退出码 0。

上述结构/环境/路径检查均为只读且幂等：路径扫描范围限 `manifest.json` 列出的第一方文件与包根脚本（跳过 `docs/`、`README.md`、`manifest.json` 与二进制），自检/验收运行时生成的产物不在清单内，不会误报。相关单测：manifest 环境声明一致性 3 项、包内第一方文本路径扫描 4 项。

说明：自检会在解压目录内生成 `__pycache__` 等运行产物；当前构建已排除第一方 `__pycache__`/`*.pyc`，清单 18,172 个文件不含编译缓存，运行期新生成的缓存不计入清单。自检脚本另含清单卫生检查，清单中若出现缓存/编译产物会直接判失败；历史构建曾因 pyc 被重写导致“先 check-bundle 再一键验收”不幂等，修复与复验见 §3.7。

### 3.6 可移植性与绝对路径扫描（2026-11-19）

为核对“离线包不依赖开发机绝对路径”（A13 相关），对当次构建的 `dist/laitp-offline-lean.zip` 做了一次只读静态扫描（该构建早于 §3.7 的修复构建，`manifest.json` 的 `created_at` 见下文；表中配置路径问题已在 §3.7 修复）：解压到 `%TEMP%` 临时目录（扫描后删除），逐行匹配文本文件，**不运行**包内完整验证。

- **范围**：包内 9,167 个文本文件——第一方 108 个（`backend/`、`docs/`、`scripts/`、`schemas/`、`configs/`、`demo/` 与根文件）、自包含桌面的生成配置 2 个、便携 Python 与第三方 9,057 个；覆盖 `.py`、`.ps1`、`.bat`、`.md`、`.txt`、`.json`、`.schema`、`.yml`、`.yaml`、`.csv`、`.toml`、`.xml`、`.cs` 等扩展名，跳过 `.pyd/.dll/.exe/.png/.pt/.onnx/.pth（权重）` 等二进制与超过 8 MiB 的文件。`python/Lib/site-packages`、`python/Lib/test` 等第三方目录单独统计，不作为修复对象。
- **模式**：`D:\project\Python\LAITP`（含正/反斜杠、JSON/Python 源码中的双反斜杠转义与大小写变体）、`D:\project`/`D:/project`、MSYS `/d/project`、开发机用户目录 `C:\Users\KL_jiana`、WSL `/mnt/d/project`；另用盘符绝对路径正则复核第一方文本，人工判断是否开发机路径。
- **对象构建**：解包后 `manifest.json` 的 `created_at` 为 `2026-11-19T03:37:01+00:00`。

| 分类 | 文件数 | 命中处数 | 代表文件与位置 |
| --- | --- | --- | --- |
| 真正问题（配置，扫描时需修复） | 1 | 3 | `demo/run/config.json` 第 4/5/10 行：`dataset_manifest`、`dataset_root`、`weights.path` 仍为 `D:\project\Python\LAITP\...` |
| 无害（文档示例/系统路径） | 3 | 4 | `docs/teacher-quickstart.md` 第 7 行（`D:\LAITP` 解压位置示例）、`docs/remaining-work.md` 第 130 行（证据归档目录示例 `D:\LAITP 验收证据\...`）、`docs/offline-bundle.md` 第 121 行 2 处（净环境 PATH 示例 `C:\WINDOWS\System32;C:\WINDOWS`） |
| 第三方库自带 | 0 | 0 | `python/Doc/html/howto/logging-cookbook.html` 第 2606 行的 `ext://project...` 被 `[A-Za-z]:[\\/]project` 正则误命中（1 处误报，不是路径） |

结论：

- **核心运行链路不依赖开发机绝对路径**：`backend/` 运行时代码、`start-desktop.bat`/`check-bundle.bat`、`scripts/*.ps1` 自动化脚本、`configs/`、`schemas/`、`demo/model-package/` 与桌面生成配置均无命中；启动脚本使用 `%~dp0`，脚本使用包内相对路径，`/d/project`、开发机用户目录与 WSL 挂载模式在第一方文本中为 0。
- **扫描时需修复的唯一条目**是随包分发的训练运行记录 `demo/run/config.json`：其 `dataset_root` 会被 `backend.classification export --run demo/run`（未显式提供 `--data-root` 时）读取，在目标机上指向不存在的开发机目录，导出会以“固定样本文件不存在”失败；包内自检与训练报告只读取 `training-artifact.json`/`metrics.json`/`model.pt`，不读取该字段，因此**不属于 A1 包校验阻断项**。`dataset_manifest` 与 `weights.path` 目前只作来源记录。该问题属**低风险可移植性缺陷**，未在目标机验证。
- 二进制不在文本扫描范围；抽样发现 41 个 `backend/__pycache__/*.pyc` 与 2 个桌面 DLL 内含开发机源码/PDB 路径（`.pyc` 的 `co_filename`、DLL 的 RSDS 调试记录），只用于调试回溯显示，不构成运行依赖，但建议打包时排除。

修复建议（扫描时只更新文档、未改生产代码、未重新打包；其中第 1、3 项已在 §3.7 的当前构建修复并复验，第 2 项已于 2026-11-23 实现，见下）：

1. 打包 `demo/run` 时生成可移植副本：把 `config.json` 的 `dataset_manifest`/`dataset_root`/`weights.path` 改写为包内相对路径或与机器无关的来源说明；`training-artifact.json` 的 `files` 记录了 `config.json` 的 SHA-256，改写后必须同步更新该摘要，或按契约重新签发一份演示运行记录，避免原地修改已发布记录。
2. **已实现（2026-11-23）**：构建脚本在生成 manifest 前扫描第一方文本（`backend/`、`scripts/`、`configs/`、`schemas/`、`demo/`、`desktop/` 与包根脚本/说明；排除 `docs/`、`README.md`、`manifest.json` 与二进制），命中工作区路径、用户目录、`/d/project`、`/mnt/d/project` 等标记即中止构建；3 项 pytest 覆盖。包内自检脚本同样内置该扫描（限 manifest 列出的第一方文件，4 项 pytest 覆盖；见 §3.5）。
3. 打包时排除 `__pycache__`、`.pdb` 等调试产物，避免把开发机源码路径与调试信息带入分发包。

### 3.7 自检幂等性复验与修复（2026-11-19）

在“中文+空格路径”且控制台为 **CP936（中文 Windows 默认代码页）**（`…\Temp\教学 平台 验收 <随机>`，路径 54 字符）下用当前精简包（清单 18,170 文件）复验目标机建议顺序：

- **解压 → `check-bundle`（自检）→ `run_acceptance.ps1 -IncludeFlow -IncludeExtended`（11 环节）→ 再次自检**：
  - 首次自检：退出码 0（34.0 s，清单卫生检查通过，18,170 文件摘要匹配）
  - 一键验收：退出码 0、`ok=true`、**11/11 环节通过**（自检 34.0 s、窗口 11.3 s、启动 2.6 s、演示 1.0 s、新建导入 25.0 s、训练预测 29.0 s、保存恢复 42.2 s、数据体检 0.3 s、历史汇总 0.2 s、严格验收 0.5 s、自检幂等性复核 25.6 s）
  - 验收后再次自检：退出码 0，清单卫生检查与摘要均通过 → **幂等性通过**
- 修复内容：打包时统一排除第一方 `__pycache__`/`*.pyc`（清单不再包含 pyc）；演示训练记录 `demo/run/config.json` 的 3 处开发机绝对路径改写为包内相对位置，并同步 `training-artifact.json` 中 config.json 的摘要/大小，避免训练报告校验失败。
- 补充：解压树最长路径 214 字符（<260）；项目路径含中文与空格时新建/导入/训练/预测/保存恢复均正常。普通用户权限与非提权干净目标机仍需按 R1/R4 验收。

目标机执行包内一键验收遇到失败时（如第 1 步“文件大小不符”或第 11 步“自检幂等性复核”失败），按[目标机离线验收清单 §7 常见失败与排查](acceptance-checklist.md#常见失败与排查)逐条排查；本节结论只来自本机解包复验，不代表目标机已验证。
