# 桌面外壳（M1 骨架）

编制日期：2026-11-17

状态：WPF 最小外壳已建立：可新建项目（目录、名称、类别）、打开项目（`project.json`）与最近项目、项目改名、增删类别、类别改名、批量导入图片、查看样本列表与预览、样本重命名/删除并重建数据清单、训练前检查数据与严格验收检查、填写数据清单与轮数启动训练（成功后自动导出 ONNX、登记模型并设为当前模型）、查看训练历史并从历史运行重新导出、查看最近一次训练结果（准确率、每类召回、混淆矩阵、误判样本）、选择模型包与图片预测、显示进度/结果/错误并取消；摄像头支持设备选择/检测刷新、单张拍照导入、连拍与高帧率预览（DroidCam 实测约 21 fps）。已纳入自包含离线包（启动/自检/界面自动化已验证），但**目标 Windows 机器、普通用户与真正断网验收尚未执行**；物理 `HD Webcam` 被禁用（Code 22），真实物理摄像头未验证；摄像头自动化测试已于 2026-11-18 按要求停止，界面采集以 DroidCam 历史记录为准。

所属路线：[总体路线 M1：第一堂课](roadmap.md)。后端协议见[任务协议与父进程](task-protocol.md)，推理与校验规则见[独立推理说明](runtime-inference.md)。

## 1. 结构

```text
desktop/
  Laitp.sln
  src/Laitp.Core/            # 与界面无关：消息信封、任务状态机、父进程、工作区定位
  src/Laitp.Desktop/         # WPF 外壳（MVVM 骨架）
  tests/Laitp.Core.Checks/   # 控制台自检程序（不依赖测试框架包）
  tests/fixtures/            # 自检用的假工作进程脚本
```

| 组件 | 说明 |
| --- | --- |
| `Laitp.Core.Envelope` | 解析按行 JSON 消息，校验归属字段、消息类型与结果产物 ID 自洽 |
| `Laitp.Core.TaskSession` | 状态机：只接受归属一致、序号递增的消息；终态后拒绝迟到消息 |
| `Laitp.Core.TaskSupervisor` | 启动子进程、读取 stdout、维护任务状态、取消并终止进程，保留 stderr 尾部 |
| `Laitp.Core.WorkspaceLocator` | 定位仓库根目录与 Python：优先 `LAITP_HOME` / `LAITP_PYTHON`，否则向上查找 |
| `Laitp.Core.ProjectDocument` | 只读解析 `project.json`：格式版本、类别、模型引用与当前模型；用于界面打开项目 |
| `Laitp.Core.TrainingReport` | 只读解析运行目录 `metrics.json`：准确率、每类召回、混淆矩阵与逐样本结果 |
| `Laitp.Core.DatasetSummary` | 只读统计数据清单：各类训练/验证/测试样本数 |
| `Laitp.Core.SampleList` | 只读解析项目样本列表：路径、类别、存储划分、批次与显示名 |
| `Laitp.Core.DatasetCheckReport` | 只读解析训练前数据检查报告：通过状态与问题项 |
| `Laitp.Core.TrainingRunList` | 只读解析训练历史：运行 ID、准确率、登记状态与当前模型 |
| `Laitp.Desktop.MainViewModel` | 新建/打开项目、改名/增删类别/类别改名、训练/预测/模型对比/导入（逐批/批量/测试集/摄像头拍照）/样本重命名/删除/数据检查/环境自检/训练历史导出/另存为/最近项目/项目归档/取消命令；训练前自动检查数据，训练成功后调用项目发布命令 |
| `Laitp.Desktop.CameraCapture` | 枚举已启用视频采集设备并拍照保存 PNG（WinRT MediaCapture）；返回设备名/字节数/耗时 |
| `Laitp.Desktop.MainViewModel`（摄像头） | 设备下拉框（`CameraDeviceBox`）与“检测/刷新”（`CameraCheckButton`）；“拍照”（`CameraCaptureButton`）按选中设备拍照并按类别导入；“连拍”（`CameraBurstCountBox`/`CameraBurstButton`）连续拍摄并同批次导入；“开始/停止预览”（`CameraPreviewButton`/`CameraPreviewStopButton`）显示实测帧率 |
| `Laitp.Desktop.MainWindow` | 最小界面：新建项目、项目文件、项目编辑、类别摘要、数据导入与样本统计、样本列表与预览、样本重命名/删除、数据清单与轮数、检查数据（含严格验收策略）与环境自检、训练与历史导出、模型包目录、图片路径、训练/预测/取消、产物 ID、训练结果与消息列表 |

## 2. 构建环境

本机原只有 .NET 8 运行时（8.0.3，含 WindowsDesktop），没有 SDK。为不改动系统环境，SDK 8.0.428 解压到仓库内 `.dotnet/`（已忽略，不提交）：

```powershell
Invoke-WebRequest https://aka.ms/dotnet/8.0/dotnet-sdk-win-x64.zip -OutFile artifacts\dotnet-sdk.zip
Expand-Archive artifacts\dotnet-sdk.zip -DestinationPath .dotnet -Force
.\.dotnet\dotnet.exe --info
```

## 3. 构建、自检与运行

```powershell
# 构建（0 警告 0 错误）
.\.dotnet\dotnet.exe build desktop\Laitp.sln -v minimal

# 无框架自检：信封、状态机、父进程成功/失败/取消，以及可选的真实 Python 集成
.\.dotnet\dotnet.exe run --project desktop\tests\Laitp.Core.Checks
.\.dotnet\dotnet.exe run --project desktop\tests\Laitp.Core.Checks -- `
  --package artifacts\...\model-package --image artifacts\...\data\images\...\001.png

# 启动界面（需要可交互桌面）
.\.dotnet\dotnet.exe run --project desktop\src\Laitp.Desktop
```

界面启动后端时使用：

```text
<python> -m backend.runtime.worker predict --package <包> --image <图片>
         --request-id <req> --project-id proj-local --task-id <task>
```

仓库根目录与 Python 解释器通过环境变量 `LAITP_HOME`、`LAITP_PYTHON` 覆盖；未设置时自动向上查找包含 `backend/runtime` 的目录并使用 `.venv\Scripts\python.exe`。

## 4. 本机验证结果

| 检查 | 结果 |
| --- | --- |
| `dotnet build` | 成功，0 警告 0 错误（Core / Desktop / Checks） |
| `Laitp.Desktop.MainViewModel`（预测） | “预测”单图（`PredictButton`）与“批量预测”（`BatchImagesBox` + `BatchPredictButton`）：批量预测调用 `backend.runtime.batch`，一次加载模型后逐张预测，状态显示总体/各类准确率，消息区列出误判样本与 CSV 路径 |
| `Laitp.Desktop.MainViewModel`（归档） | “导出存档”（`ArchivePathBox` + `ExportArchiveButton`）调用 `Laitp.Core.ProjectArchive` 打包项目；“从存档导入”（`ImportArchiveButton`）恢复到 ZIP 同名目录并打开项目 |
| `Laitp.Core.CameraErrors` | 摄像头异常到课堂提示的映射（权限、占用、缺失、未就绪） |
| `Laitp.Core.RecentProjects` | 最近打开项目列表：去重、置顶、上限 5、JSON 持久化（`%LOCALAPPDATA%\Laitp\recent-projects.json`） |
| `Laitp.Core.ProjectCopy` | 项目目录复制（“另存为”）：拒绝相同目录、拒绝非空目标，逐文件/目录复制 |
| `Laitp.Core.Checks` | 64 项全部通过：信封与状态机、父进程成功/失败/取消、仓库定位、项目文件、训练报告、数据清单摘要、样本列表、数据检查报告与策略、训练历史、环境自检、摄像头错误提示、最近项目、项目复制及拒绝场景 |
| `Laitp.CameraChecks` | 摄像头诊断控制台：枚举视频采集设备并尝试拍一张 PNG；本机通过 DroidCam Video 验证（1280×720，1.75 s），详见[摄像头能力](camera.md) |
| 真实 Python 工作进程集成 | 通过：C# 父进程启动 `backend.runtime.worker predict`，收到进度与结果，产物 ID 正确 |
| WPF 启动冒烟 | 进程启动后存活 4 秒未崩溃，随后手动结束（未做界面自动化或截图验证；早期记录，后续已补界面自动化） |
| 训练与发布（命令行链路） | 工作进程训练 13 条消息：`accepted` → `load` → `feature_extraction`（18 张）→ `head_training`（2 轮）→ `publish`；`publish-training` 生成 `art-run-pub-0001`，项目 `verify` 通过，当前模型切换为该导出包，随后的 `predict` 成功 |
| 训练结果报告 | 真实训练运行经 `classification report` 校验：准确率 0.333、3×3 混淆矩阵、每类召回、9 条逐样本结果；随后发布 `verify` 通过 |
| 批量导入（命令行链路） | 3 类 × 2 批次逐一 `import`：全部 exit 0，最后一批后清单重建为 6 个样本（训练 3 / 验证 3），类别顺序与项目一致 |
| 新建项目（命令行链路） | `backend.project create` 省略 `--project-id`：自动生成 `proj-YYYYMMDD-HHMMSS`，项目文件类别顺序正确 |
| 样本列表与删除（命令行链路） | 真实项目列出 15 个样本；删除 1 个后清单重建成功、样本数变为 14；空批次目录被清理 |
| 项目编辑（命令行链路） | 改名成功；添加类别后清单提示“未重建”（新类暂无数据）；删除新增类别后清单恢复；删除有数据类别（显式确认）后类别剩 2 个、清单重建、`verify` 通过 |
| 训练前数据检查（命令行链路） | 常规检查通过（6 个样本）；`--require-test` 对无测试集项目返回 `DATASET_TEST_SPLIT_MISSING`（exit 1） |
| 类别改名与样本重命名（命令行链路） | 类别“书本”→“课本”：目录同步移动、类别顺序保持、清单重建；样本改名后扩展名保留、清单更新、`verify` 通过 |
| 训练历史与重新导出（命令行链路） | 训练运行 `run-history-0001` 在 `runs` 中显示未登记、准确率 0.333；`export-run` 生成 `art-run-history-0001`，历史变为已登记、项目当前模型指向该产物、`verify` 通过 |
| 严格验收检查（命令行链路） | 真实子集项目基础检查通过；`--require-test --min-train 30 --min-val 8 --min-test 10` 返回 `DATASET_CLASS_TOO_FEW_SAMPLES`（exit 1），与子集规模不足的预期一致 |
| 界面自动化（UIAutomation） | 窗口定位成功；自动自检状态“就绪（环境自检通过）”；点击“环境自检”后状态与消息区显示 4 项通过；缺 Python 场景下自动自检与手动按钮均显示“环境自检未通过”及修复提示 |
| 界面主流程（UIAutomation） | 填入真实项目路径 → 点击“打开项目”：状态“已打开项目，当前模型：art-run-real-0001”，类别“T恤 / 裤子 / 外套”；点击“检查数据”：状态“数据检查通过，可以开始训练”，检查徽标“数据检查通过” |
| 一键验证（本机） | `scripts/verify_all.py --ui`：Python 测试、构建、Core 检查、验收证据汇总、文档一致性、离线包校验、净环境流程、真实数据课堂演练与 8 个界面自动化步骤全部通过（16 步，约 10 分钟；摄像头步骤按要求跳过），报告写入 `artifacts/verify-all/` |
| 界面完整闭环（UIAutomation） | 同一项目副本：轮数设为 1 → 点击“训练并发布” → 状态“训练与导出完成，当前模型：art-run-20261117233919”；填入测试图片 → 点击“预测” → 状态“成功”，产物 ID 更新为同一导出包 |
| 解包目录完整闭环（UIAutomation） | 在含中文/空格的解包目录、使用包内 Python：打开项目 → 检查数据 → 训练并发布 → 预测，状态与产物 ID 均正确（`art-run-20261117234630`） |
| 新建项目 + 导入（UIAutomation） | 新建“界面自动化项目”（苹果/香蕉）：状态“已创建并打开项目”；4 次导入均“导入完成”（前 3 次清单暂不满足批次要求属预期）；清单合计 24 张（训练 12 / 验证 12）；检查数据通过 |
| 解包目录新建 + 导入（UIAutomation） | 在含中文/空格的解包目录、使用包内 Python：新建“界面自动化项目”（杯子/书本）→ 导入 4 批 → 清单 24 张 → 检查数据通过 |
| 项目保存与恢复（UIAutomation） | 新建 → 导入 4 批 → 训练并发布（产物 `art-run-20261118000011`）→ 关闭程序 → 重新启动并打开同一项目：状态“已打开项目，当前模型：art-run-20261118000011”，类别、数据清单与检查结论均恢复 |
| 训练历史导出（UIAutomation） | 打开含历史运行的项目 → 自动选中 `run-real-0001` → 点击“导出选中运行”：状态“已导出运行 run-real-0001，当前模型：art-run-real-0001-2”，产物 ID 更新，导出包 `manifest.json` 存在 |
| 解包目录历史导出（UIAutomation） | 在含中文/空格的解包目录、使用包内 Python：打开含历史运行的项目 → 导出选中运行，状态、产物 ID 与导出包均正确 |
| 项目编辑 + 严格验收（UIAutomation） | 打开真实项目副本：项目改名 → “项目已改名”；添加/删除类别 → 类别列表正确变化；类别改名 T恤→短袖 → “短袖 / 裤子 / 外套”；样本重命名/删除 → 状态与清单更新；勾选严格验收后检查：状态“数据检查未通过：3 个问题”，徽标“数据检查未通过（3 个问题）” |
| 解包目录项目编辑（UIAutomation） | 在含中文/空格的解包目录、使用包内 Python：项目改名、添加/删除类别、类别改名、样本重命名/删除、严格验收失败提示均正确 |
| 批量导入（UIAutomation） | 新建项目后填入来源根目录并点击“批量导入”：状态“批量导入完成：新增 24，重复 0，无效 0；批次 4”，数据清单合计 24 张，检查数据通过 |
| 测试集导入（UIAutomation） | 勾选“导入为测试集”后逐类导入测试图片：清单显示“测试”数量且合计增加，检查数据通过（为严格验收准备独立测试集） |
| 摄像头拍照导入（UIAutomation） | DroidCam Video：每类拍照 2 次，4 次均“拍照成功（DroidCam Video，19 KB），已导入类别 …”；清单合计 4 张；静态画面触发 `DATASET_CONTENT_DUPLICATE`（预期） |
| 摄像头预览（UIAutomation） | 设备下拉框存在；点击“开始预览”：状态“预览中（20.4 fps，155 帧）”；“停止预览”：“预览已停止（208 帧，平均 20.6 fps）” |
| 摄像头连拍（UIAutomation） | 设置连拍 3 张 → 点击“连拍”：状态“连拍完成：拍摄 3 张，导入完成：新增 1，重复 2，无效 0”（DroidCam 静态画面预期去重），清单合计 5 张 |
| 净环境界面自动化 | 清空 PATH 中 Python/.NET、清除 PYTHON*、代理不可用、使用包内 Python：`ui_flow.ps1 -CleanEnv`（打开→检查→训练→预测）与 `ui_camera.ps1 -CleanEnv`（设备→预览→连拍→拍照）均通过 |
| 最近项目 | `ui_flow.ps1` 打开项目后写入 `%LOCALAPPDATA%\Laitp\recent-projects.json`；`ui_flow.ps1 -UseRecent` 点击“打开最近”成功恢复项目（截图可见最近下拉框与“打开最近”按钮） |
| 另存为 | `ui_flow.ps1 -SaveAsDir <新目录>`：复制项目目录并切换当前项目；状态“已另存为：…”；新目录含 `project.json`/`data`/`exports`/`runs`，随后数据检查通过 |
| 项目归档 | 界面“导出存档/从存档导入”：把项目目录打包为单文件 ZIP 或恢复到空目录；导入后先调用 `backend.project verify --root` 校验项目与产物摘要，失败则保留解压目录、不切换当前项目；Core 检查覆盖导出内容、往返一致、拒绝非空目标与缺 `project.json`/越界条目的归档 |
| 校验项目 | 项目区“校验项目”（`VerifyProjectButton`）：调用 `python -m backend.project verify --root <项目目录>`，通过时状态“项目校验通过”，失败时显示问题数并把最多 10 条 `code：message` 追加到消息区；用于课前自检项目与产物摘要 |
| 项目归档（自动化） | `ui_flow.ps1 -ArchiveDir <目录>`：导出到 `flow-archive.zip`，状态含“已导出存档”；再导入到同名目录并打开，状态含“已从存档导入”；实测 284 个条目、`project.json` 可解析 |
| 批量历史导出 | 批量预测历史区“导出历史汇总”（`ExportBatchHistoryButton`）：调用 `scripts/batch_history_export.py`，生成 `runs/batch-history.md` 与 `runs/batch-history.csv`，状态“已导出批量历史：N 次运行（跳过 M 个）” |
| 模型对比历史 | 批量历史下方“模型对比历史（最近 10 次）”（`CompareHistoryListBox`）+“查看对比历史”（`ViewCompareHistoryButton`）：读取 `runs/compare-*.json`，回看两包准确率/一致率/标签一致性/分歧样本 |
| 数据体检（界面） | 数据检查区“数据体检”（`DatasetReportButton`）：调用 `scripts/dataset_report.py`，报告与样本 CSV 写入项目 `runs/`；`ui_flow.ps1 -DataReport` 实测“数据体检完成：150 张样本，0 组重复，0 张无效，0 条风险”，报告含类别/批次表；“打开体检报告”（`OpenDatasetReportButton`）可直接打开 `runs/dataset-report.md`（无关联程序时回退打开所在目录） |
| 批量预测 | `ui_flow.ps1 -BatchImagesDir <测试集目录>`：训练后点“批量预测”；状态“批量预测完成：30 张，准确率 86.7%（30 张有真实类别）”，消息区显示各类准确率、**各批次准确率**与误判样本；逐张结果 CSV 与汇总 JSON 均保存到项目 `runs/batch-predict-*.csv` / `runs/batch-predict-*.json`（Excel 可打开） |
| 批量预测历史详情 | `BatchHistoryListBox` 选中后点“查看选中历史”（`ViewBatchHistoryButton`）：读取对应 `runs/batch-predict-*.json`，把总体/各类/各批次准确率与 CSV 路径追加到消息区；文件缺失或损坏时仅状态提示 |
| 打开结果目录 | 训练历史区“打开结果目录”（`OpenRunsButton`）：打开当前项目 `runs` 目录（不存在则创建），状态“已打开结果目录：…” |
| 模型对比 | “模型对比”（`ComparePackageCombo` 选择项目历史模型包 / `ComparePackageBox` 手输 + `CompareButton`）：对当前模型包与对比包在同一批量测试目录上执行 `backend.runtime.compare`，状态与消息区显示两包准确率、一致率、分歧样本（最多 5 条）与**标签一致性警告**（`labels_match=false` 时提示不可比）；后端 7 项 pytest 覆盖，界面自动化 `ui_flow.ps1 -ComparePackage` 已验证（A 76.7% / B 90.0%，一致率 76.7%） |
| 界面截图证据 | `ui_smoke.ps1 -Screenshot`（PrintWindow，覆盖遮挡窗口）保存窗口 PNG；实测截图可见标题“LAITP 分类实验（M1 骨架）”、摄像头设备/检测/拍照/连拍控件与状态“环境自检通过，可以开始使用” |
| 摄像头预览截图 | `ui_camera.ps1 -Screenshot` 在预览中与数据清单生成后各截一张；截图可见 DroidCam 预览画面、状态“预览中（21.2 fps，178 帧）”、类别/拍照/连拍控件 |

这些检查只覆盖开发机协议、启动与界面自动化，不覆盖真实课堂数据或目标机性能。

## 5. 未实现与限制

- 物理摄像头 `HD Webcam` 被禁用（Code 22，启用需管理员）；摄像头验证使用 DroidCam 虚拟摄像头，真实摄像头与多摄像头并发待验证。
- 训练前自动执行基础数据检查（每类训练/验证覆盖、批次划分、文件摘要与可解码），未通过时拒绝开始训练；“检查数据”按钮可勾选严格验收（独立测试集与每类样本下限）。
- 训练历史可查看与重新导出，但不支持删除运行或回滚到某个历史模型（重新导出即切换当前模型）。
- 新增类别不会立即生成数据清单（新类无样本，按 T03 规则无法划分），需导入该类别图片后重建；删除有数据类别必须勾选“同时删除数据”。
- 样本改名/删除为立即生效并自动重建清单。
- 训练前自动执行基础数据检查（每类训练/验证覆盖、批次划分、文件摘要与可解码），未通过时拒绝开始训练；界面“检查数据”可手动查看问题列表。
- 界面单张预测不显示各类概率；已支持批量预测（总体/各类准确率与 CSV），但尚未加入错误对话框与重试。
- 项目归档导入先做 ZIP 结构校验（拒绝非空目标、越界条目、缺 `project.json`），再调用 `backend.project verify --root` 校验项目 Schema、数据清单与模型摘要；失败保留解压目录、不切换当前项目；界面归档流程已由 `ui_flow.ps1 -ArchiveDir` 覆盖。
- 数据清单按 T03 规则要求每类至少 2 个采集批次；不足时导入文件保留但清单不重建，界面会显示原因。
- 导出使用训练运行内的数据清单副本定位验证图片；项目数据被移动后发布可能失败，需要重新采集或提供数据根目录。
- 训练结果面板读取 `metrics.json` 显示，不重复做文件摘要校验；发布与报告命令（Python 侧）负责完整校验。
- 已做界面自动化（冒烟、主流程、摄像头、净环境）；未做高 DPI、可访问性与目标 Windows 机器运行验证。
- 自包含桌面与便携 Python 已随包分发（瘦身包不含 wheel）；仍需在干净目标机验证解压双击与普通用户权限。
- 后端进程路径与仓库/包资源布局绑定（开发期方案），产品化前需要继续收敛。
- 项目以目录形式管理（`project.json` + `data/` + `exports/` + `runs/`）；“另存为”会复制整个项目目录，“导出存档/从存档导入”可生成或恢复单文件 ZIP。

## 6. 下一步

1. 目标 Windows 机器验证：普通用户、真正断网、解压双击、启动/训练/预测耗时。
2. 课堂真实图片（替代公开数据）与课堂时间预算现场测量。
3. 物理摄像头启用后的真实采集验证、多摄像头并发与权限错误实测。
4. 高 DPI、可访问性与长时间运行稳定性检查；离线包完整包（含 wheel）交付形式评估。

## 7. 首次运行自检

桌面程序支持 `--self-test <输出 JSON>`：检查仓库根目录识别、Python 定位、后端导入与演示模型工作进程预测，写入 JSON 并以退出码 0/1 表示是否就绪。离线包解压后可先运行：

```powershell
desktop\app\Laitp.Desktop.exe --self-test self-test-result.json
```

界面内也有“环境自检”按钮：点击后在消息区逐项显示检查结果（通过/失败与详情），状态栏给出总体结论，便于课堂现场排查 Python、后端或模型包问题。

窗口创建后会在后台自动运行一次自检：通过时状态栏显示“就绪（环境自检通过）”；失败时在消息区列出失败项与修复提示（`LAITP_HOME`/`LAITP_PYTHON`/离线包启动脚本），避免课堂开始后才发现环境问题。自动自检不阻塞界面操作。

该自检验证环境与后端链路，不替代界面交互验证。

界面冒烟可用 `scripts/ui_smoke.ps1`（Windows UI Automation）：启动程序、定位窗口、点击“环境自检”并读取状态栏/消息区。加 `-LaitpHome`/`-LaitpPython` 可对解包目录运行；加 `-BrokenPython` 验证缺 Python 时的失败提示。

主流程可用 `scripts/ui_flow.ps1 -ProjectPath <project.json>`：填入项目路径、点击“打开项目”与“检查数据”，读取状态栏、类别与检查结论。加 `-TrainPredict -ImagePath <png>` 可继续设置轮数为 1、点击“训练并发布”、等待完成、填入图片并点击“预测”，验证完整界面闭环。控件通过 XAML `x:Name` 暴露稳定 AutomationId（`ProjectPathBox`、`OpenProjectButton`、`CheckDatasetButton`、`EpochsBox`、`TrainButton`、`PackagePathBox`、`ImagePathBox`、`PredictButton`、`StatusText`、`ClassesTextBlock`、`DataCheckStatusText`、`ArtifactText`）。

新建项目与导入可用 `scripts/ui_create_import.ps1 -SourceRoot <dir> -ProjectParent <dir>`：设置项目目录/名称/类别并点击“新建并打开”，再逐类逐批导入（`NewProjectRootBox`、`NewProjectNameBox`、`NewProjectClassesBox`、`CreateProjectButton`、`ImportClassBox`、`ImportSourceBox`、`ImportBatchBox`、`ImportButton`、`DatasetSummaryTextBlock`），最后读取数据检查结论。加 `-TreeSource <dir>` 改用界面“批量导入”（`ImportTreeSourceBox`、`ImportTreeButton`）；加 `-TestSource <dir>` 会勾选“导入为测试集”（`ImportAsTestCheckBox`）导入独立测试集。

摄像头拍照导入可用 `scripts/ui_camera.ps1 -ProjectParent <dir>`：新建项目后按类别拍照并校验导入结果（需要可用摄像头，开发机使用 DroidCam）；摄像头自动化测试自 2026-11-18 起按要求停止，该命令仅供需要时人工执行。

保存与恢复可用 `scripts/ui_restore.ps1 -SourceRoot <dir> -ProjectParent <dir>`：新建 → 导入 → 训练并发布 → 关闭程序 → 重新打开项目，校验当前模型、类别、数据清单与检查结论。

训练历史导出可用 `scripts/ui_export_history.ps1 -ProjectPath <project.json>`：打开项目（自动选中第一条历史运行）→ 点击“导出选中运行”→ 校验状态、产物 ID 与导出包文件。

项目编辑与严格验收可用 `scripts/ui_edit.ps1 -ProjectPath <project.json>`：项目改名、添加/删除类别、类别改名、样本重命名/删除，并勾选严格验收执行检查（验证样本不足时的失败提示）。
