# 验证证据索引

本文汇总**开发机**上可复现的验证命令、产物位置与留证方式，供目标机验收时对照与复查。所有数字均为开发机结果，**不代表目标机已验收**；目标机验收见[目标机离线验收清单](acceptance-checklist.md)。

## 0. 验证选择（按改动范围）

| 改动范围 | 建议验证 | 预计耗时 |
| --- | --- | --- |
| 仅后端/工具链/文档（不动界面） | `scripts\verify_all.py --quick`（pytest + 构建 + Core + 文档/状态检查），必要时单跑相关 pytest | 1 分钟左右 |
| 界面代码或界面自动化脚本改动 | 先 `--quick`，再单跑对应界面脚本（如 `ui_flow.ps1`、`ui_create_import.ps1`），或解压包内 `run_acceptance.ps1 -IncludeFlow -IncludeExtended` | 1～4 分钟 |
| 发布前 / 大阶段 / 打包后 | 完整 `verify_all.py --ui`（16 步）+ 完整包解包校验 + 包内一键验收 + 双包 SHA/交接更新 | 约 15 分钟 |

日常小步改动优先用前两行；只有大阶段才跑完整 16 步，避免每轮都做长时间验证。

## 1. 一键验证与证据汇总

| 目的 | 命令 | 产物 |
| --- | --- | --- |
| 快速验证（6 个步骤，约 1–2 分钟，日常改代码后用） | `.\.venv\Scripts\python.exe scripts\verify_all.py --quick` | `artifacts/verify-quick/verify-quick.json`、`verify-quick.txt`（JSON 含 `"quick": true`）；阶段验收仍用下面的完整版 |
| 完整本机验证（16 步，约 10 分钟） | `.\.venv\Scripts\python.exe scripts\verify_all.py --ui` | `artifacts/verify-all/verify-all.json`、`verify-all.txt` |
| 含摄像头的历史命令（17 步；需可用摄像头，自动化测试已于 2026-11-18 停止，仅供人工复验） | `.\.venv\Scripts\python.exe scripts\verify_all.py --ui --camera` | 同上 |
| 验收项证据汇总（A1–A15） | `.\.venv\Scripts\python.exe scripts\acceptance_audit.py` | `artifacts/acceptance-local.json`、`acceptance-local.md` |
| 文档一致性检查 | `.\.venv\Scripts\python.exe scripts\check_docs.py` | 核对当前包 SHA/体积、测试数、Core 检查数、验证步数、过期缩写 SHA、依赖版本与 `third-party-notices.md` 一致，以及 docs 与根 README 的 Markdown 本地链接与 #锚点；退出码 0 表示一致 |
| CP936 控制台兼容验收（本机） | 在 `chcp 936` 控制台（中文+空格路径）运行 `run_acceptance.ps1 -IncludeFlow -IncludeExtended` | 修复控制台编码后，**正式包在 CP936 与默认环境下均 11/11 通过**（自检 27.8 s、自检幂等性复核 25.2 s；第 8/9/10 步 JSON 正常解析，stderr 全 0 字节）；旧版在 CP936 下这三步会因 GBK 解码 UTF-8 JSON 失败 |
| 中文+空格路径验收（本机，非提权） | 解压到含中文与空格的临时目录后按“自检 → `run_acceptance.ps1 -IncludeFlow -IncludeExtended` → 再次自检” | **幂等通过**：首次自检 0、验收 11/11（自检 28.0 s、窗口 10.9 s、严格验收 0.5 s）、再次自检 0；打包已排除 `__pycache__`/pyc 并改写演示记录绝对路径；详见[离线分发包 §3.7](offline-bundle.md#37-自检幂等性复验与修复2026-11-19) |
| 包内桌面自包含检查 | python\python.exe scripts\verify_offline_bundle.py --extracted .（随包内自检执行） | 校验 desktop/app 的 runtimeconfig 使用 includedFrameworks 且含 coreclr.dll/hostfxr.dll；框架依赖构建会被判失败；同时校验 start-desktop.bat 指向包内 desktop\app\Laitp.Desktop.exe（不得指向开发 bin 目录）；并校验 check-bundle.bat 含 chcp 65001、包内 python\python.exe、scripts\verify_offline_bundle.py 与 --extracted，且不含开发机绝对路径；12 项 pytest 覆盖 |
| 包内第一方文本绝对路径扫描（A13 回归） | 包内自检（`python\python.exe scripts\verify_offline_bundle.py --extracted .`） | 扫描范围限 `manifest.json` 列出的第一方文件与包根脚本（跳过 `docs/`、`README.md`、`manifest.json` 与二进制）；命中工作区路径/用户目录/`/d/project`/`/mnt/d/project` 即失败；运行时生成产物不在清单内，重复自检幂等；4 项 pytest 覆盖 |
| 构建期绝对路径断言（A13 回归） | 构建离线包时自动执行 | 扫描第一方文本（backend/scripts/configs/schemas/demo/desktop 与包根脚本/说明），命中工作区路径/用户目录/`/d/project`/`/mnt/d/project` 即中止构建；3 项 pytest 覆盖；2026-11-23 构建实测通过（无命中） |
| 依赖与许可说明一致性 | `scripts/check_docs.py`（随文档一致性检查执行） | 解析 `requirements.txt`/`requirements-dev.txt` 的 name==version 固定项，核对 `docs/third-party-notices.md` 是否列出且版本一致；3 项 pytest 覆盖；缺失/不一致会报问题 |
| K230 转换前置静态探测 | `python scripts/k230_model_probe.py --model <模型包> --output artifacts/k230-probe/*.json` | 只读 ONNX 图事实（算子分布、输入输出形状/动态维度、参数量、opset、manifest SHA 匹配），不运行 nncase、不量化、不接触板卡；3 项 pytest 覆盖；结果不得当作转换或板端验证 |
| GitHub Actions 工具/文档 CI | push 触发 `.github/workflows/tooling.yml`（windows-latest） | 运行成功（2026-11-23：run 45080969289 首次通过；run 45081434292 在新增本地 Parser 检查后通过；run 45082936242 在新增 check_docs 步骤后通过；run 45083395984 在加入 K230 静态探测脚本后通过）：`scripts/*.ps1` PowerShell 解析 0 错误，`scripts/check_docs.py` 文档一致性通过（无 dist 时跳过 SHA/体积），工具/文档测试子集（81 项）通过；不含 torch、桌面构建或界面自动化；完整验证仍以开发机运行结果为准 |
| PowerShell 解析检查（本地 + CI） | `pytest -q tests/test_script_hygiene.py::test_powershell_scripts_parse` （无 PowerShell 时自动 skip） | 调用 PowerShell Parser 逐个解析 `scripts/*.ps1`，任一语法错误即失败；本地与 GitHub Actions 均执行；与 CI 工作流中的解析步骤互为双保险 |
| 脚本卫生（BOM/验收结构） | .\.venv\Scripts\python.exe -m pytest tests/test_script_hygiene.py | 所有 scripts/*.ps1 保持 UTF-8 BOM（防止 PS 5.1 解析中文脚本失败）；run_acceptance.ps1 含 11 个环节、超时助手（240/180/420/600/480 s）、单次透明重跑（Retried/FirstExitCode 留痕）、预检清理、包身份与磁盘字段；5 项 pytest 覆盖 |
| 交付状态快速自检 | `.\.venv\Scripts\python.exe scripts\check_state.py` | 约 1 秒：包 SHA/体积入文档并轻量校验 ZIP 内 manifest/自包含/启动脚本结构（不替代完整解包校验）、交接目录 SHA 与文件、最近一键验证、验收汇总、长时间预览稳定性、文档一致性、交接验收报告样例、交接目录文档与仓库一致共 11 项 |

日常改动后用 `--quick` 做分钟级检查（只含上表 6 个快速步骤，不跑离线包校验、净环境流程、课堂演练、界面自动化与摄像头）；阶段验收或发布前仍运行完整版 `verify_all.py --ui`（摄像头自动化已按要求停止，不再加 `--camera`）。

当前本机结果：Python 483 项测试通过、桌面构建 0 警告 0 错误、Core 检查 64 项通过、一键验证 16 步通过（摄像头步骤按要求跳过）；验收汇总为“已验证 9 / 部分 4 / 未执行 1（A10）/ 阻塞 1（A15）”。

## 2. 离线包

| 目的 | 命令/操作 | 说明 |
| --- | --- | --- |
| 校验分发包（zip） | `.\.venv\Scripts\python.exe scripts\verify_offline_bundle.py --bundle dist\laitp-offline-lean.zip` | 解包到临时目录，校验清单、推理、报告、桌面启动、自检 |
| 包内现场自检 | 解压后双击 `check-bundle.bat`，或 `python\python.exe scripts\verify_offline_bundle.py --extracted .` | 使用包内 Python，不需要开发环境 |
| 启动耗时 | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\measure_startup.ps1 -Exe <exe> [-LaitpHome <dir> -LaitpPython <python>]` | 记录窗口出现与自检完成时间 |
| 打包 | `.\.venv\Scripts\python.exe scripts\build_offline_bundle.py --skip-wheels --desktop-dir dist\desktop-selfcontained --python-dir dist\python-portable --output dist\laitp-offline-lean.zip` | 重建精简包并写 `.sha256` |
| 交接目录 | `.\.venv\Scripts\python.exe scripts\make_handoff.py --clean`（加 `--include-full` 时附带完整包） | `dist/handoff/`：ZIP 与 `.sha256`、README、老师指南、验收操作卡、验收清单、证据索引、已知限制、第三方许可说明、验收报告样例、交接说明、`handoff-manifest.json` |

## 3. 界面自动化与截图

> 摄像头自动化测试自 2026-11-18 起按用户要求停止；下表摄像头命令仅供需要时人工执行。

| 场景 | 命令 | 留证 |
| --- | --- | --- |
| 冒烟 + 自检 | `powershell -File scripts\ui_smoke.ps1 -Screenshot` | `artifacts/ui-smoke.json`、`artifacts/ui-screenshots/ui-smoke-*.png` |
| 打开→检查→训练→预测 | `powershell -File scripts\ui_flow.ps1 -ProjectPath <project.json> -ImagePath <png> -TrainPredict [-Epochs 20] [ -UseRecent] [ -SaveAsDir <dir>] [ -ArchiveDir <dir>] [ -BatchImagesDir <dir>] [ -ComparePackage <dir>] [ -DataReport] [ -PostChecks]` | `artifacts/ui-flow.json`（含 open/check/train/predict 耗时、归档导出/导入状态、批量预测与模型对比状态、数据体检与项目校验/历史导出状态） |
| 批量预测（后端） | `.\.venv\Scripts\python.exe -m backend.runtime.batch --package <模型包> --images <目录> --output <json> [--csv <csv>]` | `artifact_id`、张数、准确率、各类/各批次准确率、混淆统计、逐张结果；`--csv` 导出 Excel 可读结果 |
| 模型对比（后端） | `.\.venv\Scripts\python.exe -m backend.runtime.compare --packages <包A> <包B> --images <目录> [--output <json>] [--csv <csv>]` | 两个模型包在同一测试集的准确率/各类准确率、一致率与分歧样本；输出 `labels_match`（两包标签顺序与内容是否一致）、`labels_a`/`labels_b`（两包标签列表）与 `warnings`（标签不一致时提示准确率/一致率不可比，不改变 `ok`）；`--csv` 导出逐图对比；7 项 pytest 覆盖 |
| 项目归档（CLI） | `.\.venv\Scripts\python.exe scripts\project_archive.py export --project <project.json> --output <zip>`；`import --archive <zip> --target <dir>` | 单文件 ZIP 备份/迁移；已在解压包内用包内 Python 完成 33 文件往返验证 |
| 项目归档（界面） | 桌面“导出存档/从存档导入”；自动化 `ui_flow.ps1 -ArchiveDir <目录>` | 导出/导入状态与 ZIP 内容（284 条目、project.json）；导入后先执行 `backend.project verify --root`，校验失败不切换项目；4 项 Core 检查覆盖 |
| 数据集报告（CLI） | `.\.venv\Scripts\python.exe scripts\dataset_report.py --project <project.json> [--output report.md] [--csv samples.csv]` | 每类每批次样本、重复/无效图片、尺寸分布与风险提示；4 项 pytest 覆盖 |
| 检测草案 Schema（非激活） | `.\.venv\Scripts\python.exe -m pytest tests\test_detection_draft_schemas.py` | `schemas/detection/` 草案与样例校验；不改变契约 1.0，校验器仍拒绝 `object_detection`；9 项用例 |
| 检测草案合成校验（非激活） | `.\.venv\Scripts\python.exe scripts\detection_draft_check.py [--output <目录>] [--images N]` | 生成合成图片/标注并验证草案 Schema 与边界规则（越界、负值、尺寸不一致等）；不训练、不接入生产；4 项 pytest 覆盖 |
| 批量预测历史汇总（CLI） | `.\.venv\Scripts\python.exe scripts\batch_history_export.py --project <project.json> [--markdown <md>] [--csv <csv>] [--details-csv <明细.csv>]` | 汇总项目内多次批量预测（表格/CSV），含最近一次各类/各批次准确率；`--details-csv` 导出最近一次运行的类别/批次明细 CSV（表头 `类型,名称,总数,正确数,准确率`，UTF-8 BOM；JSON 摘要新增 `details_csv` 字段，无可用历史时不生成文件并在 warnings 中提示）；损坏文件跳过；6 项 pytest 覆盖；界面“导出历史汇总”按钮已接入 |
| 模型对比历史（界面） | 批量历史下方 `CompareHistoryListBox` +“查看对比历史” | 读取项目 `runs/compare-*.json` 最近 10 条，回看两包准确率/一致率/标签一致性/分歧样本 |
| 检测数据集清单草案（非激活） | `.\.venv\Scripts\python.exe -m pytest tests/test_detection_dataset_manifest_draft.py` | `schemas/detection/dataset-manifest-2.0-draft.schema.json` 与样例；版本固定 `2.0-draft`；样本追溯字段（`sha256`/`width`/`height`/`box_count`）必填、`capture_batch` 可选；分类策略与加载器不变；13 项用例 |
| 检测 ONNX 导出可行性探测（草案工具，未激活） | .\.venv\Scripts\python.exe scripts\detection_draft_probe.py --skip-fasterrcnn（另跑 `--model fasterrcnn`） | SSDLite(随机权重) ONNX 8.98 MB / 1,481 节点 / 43 算子 / 无 NMS / 含 If；fasterrcnn(随机权重) 75.94 MB / 1,515 节点 / 53 算子 / 无 NMS / 含 If 与 RoiAlign（输出名已按模型实际字典顺序声明，可按名称对应类型）；仅可行性探测，不训练、不接入生产；4 项 pytest 覆盖 |
| 检测草案跨字段校验（非激活） | `.\.venv\Scripts\python.exe scripts\detection_draft_dataset_check.py --manifest <清单.json>` | 逐样本校验图片存在/可解码、摘要、宽高、标注、框数、越界与类别范围；不接入生产；5 项 pytest 覆盖 |
| 模型对比（界面） | 桌面“模型对比”（`ComparePackageCombo` 选择历史包 / `ComparePackageBox` 手输 + `CompareButton`）；自动化 `ui_flow.ps1 -ComparePackage <目录>` | 实测“模型对比完成：A 76.7% / B 90.0%，一致率 76.7%（30 张）”；标签不一致时消息区显示警告；CSV 导出与 7 项 pytest 覆盖 |
| 长路径解压与自检（本机） | 解压 `dist/laitp-offline-lean.zip` 到 140 字符目录后运行包内自检 | 本机 `LongPathsEnabled=1`：解压成功、`verify_offline_bundle --extracted` 退出 0（ZIP 内最长相对路径 159 字符，完整路径约 300 字符）；耗时约 130 s（杀毒扫描影响）；未在未启用长路径的目标机验证，不作为目标机结论 |
| 包内清单环境声明一致性 | 包内自检（`verify_offline_bundle.py --extracted .`） | 核对 manifest.environment 的 platform/python_embedded/desktop_self_contained 声明与包内实际（便携 Python、自包含 runtimeconfig）一致；新增 3 项 pytest 覆盖 |
| 界面流程总超时看门狗 | 包内验收第 6 步调用 `ui_flow.ps1`（脚本内部总超时 540 s < 外层 600 s） | 所有状态/按钮等待循环同时受全局 deadline 约束（ui_flow 540 s、ui_create_import 360 s、ui_restore 420 s，均低于外层步骤超时）；超过总时限抛出“总超时”并写出 JSON，使失败可控且可重试，而不是被外层强杀；1 项脚本卫生测试覆盖 |
| 包内一键验收 | 解压离线包后 `powershell -ExecutionPolicy Bypass -File scripts\run_acceptance.ps1 [-IncludeFlow] [-IncludeExtended]` | 扩展前 9 步已在正式包实测 9/9 通过（2026-11-19；批量预测 4 张/50.0%、模型对比 A 50.0% / B 0.0%、历史汇总 1 次运行）；新增第 10 步“严格验收（正向）”与第 11 步“自检幂等性复核”后已扩展为 11 步，覆盖严格验收正向链路（包内 Python 对流程项目执行 `backend.project check-dataset --require-test --min-train/val/test`；阈值仅用于链路验证，不作为课堂验收门槛）；正式包已实测 11/11 通过（2026-11-19；含“自检幂等性复核”），验收报告含“包身份”（manifest format/created_at/文件数/总字节/manifest SHA-256），详见[项目状态报告](status-report.md)。 |
| 新建 + 导入 | `powershell -File scripts\ui_create_import.ps1` | `artifacts/ui-create-import.json` |
| 批量导入 / 测试集导入 | `... -TreeSource <dir>` / `... -TestSource <dir>` | 同上 |
| 保存 + 恢复 | `powershell -File scripts\ui_restore.ps1` | `artifacts/ui-restore.json` |
| 严格验收正向通过（界面） | `powershell -File scripts\ui_edit.ps1 -ProjectPath <project.json> -MinTrain 20 -MinVal 20 -MinTest 10 -ExpectStrictPass` | `artifacts/ui-edit-strict-positive.json`：`ok=true`、`strict_positive=true`、状态“严格验收检查通过”；真实子集每类 20/20/10 |
| 历史导出 | `powershell -File scripts\ui_export_history.ps1` | `artifacts/ui-export-history.json` |
| 项目编辑 + 严格验收 | `powershell -File scripts\ui_edit.ps1` | `artifacts/ui-edit.json` |
| 摄像头（设备/预览/连拍/拍照） | `powershell -File scripts\ui_camera.ps1 -ProjectParent <dir> -Screenshot` | `artifacts/ui-camera*.json`、`artifacts/ui-screenshots/ui-camera-*.png` |
| 长时间预览稳定性 | `powershell -File scripts\ui_preview_stability.ps1 -Seconds 60` | `artifacts/ui-preview-stability.json`（fps、帧数、内存、句柄采样） |
| 净环境（无 Python/.NET + 不可用代理） | 上述任一脚本加 `-CleanEnv` | 同上 |

> 2026-11-19 一次运行中第 5 步“新项目与导入”界面步骤超时失败（其余步骤通过），关闭残留进程后重跑 **11/11 通过**；2026-11-20 又一次运行中第 6 步“训练与预测”界面步骤超时失败（其余步骤通过），重跑 **11/11 通过**。两次均判定为界面自动化偶发抖动，结果均保留，首次失败不作为通过证据；连续两次偶发促成了“单次透明重跑”策略的实现——界面步骤失败（非 0 退出码或超时）后自动重跑一次，重试通过记为 pass 并在 `warnings` 留痕，两次均失败才判失败（见 `scripts/run_acceptance.ps1` 与 `tests/test_script_hygiene.py`）。

截图使用 `PrintWindow`（PW_RENDERFULLCONTENT）抓取窗口内容，窗口被其他程序遮挡时也能得到正确画面。截图仅用于留证，不参与自动断言。

## 4. 分领域验证

| 领域 | 命令 | 产物/依据 |
| --- | --- | --- |
| 契约 Schema 与拒绝场景 | `.\.venv\Scripts\python.exe -m pytest -q` | 483 项测试 |
| M0 基准（训练/导出/延迟/内存） | `.\.venv\Scripts\python.exe -m benchmarks.m0_benchmark --output artifacts\benchmark-m0` | `artifacts/benchmark-m0/m0-benchmark.json` |
| 离线环境基准 | `.\.venv-offline\Scripts\python.exe -m benchmarks.m0_benchmark --output artifacts\benchmark-m0-offline` | `artifacts/benchmark-m0-offline/m0-benchmark.json` |
| 真实公开数据（Fashion-MNIST 3 类） | `.\.venv\Scripts\python.exe scripts\real_data_validation.py` | `artifacts/real-data/result.json`（准确率约 0.917，产物 `art-run-real-0001`） |
| 净环境离线流程 | `.\.venv\Scripts\python.exe scripts\verify_offline_flow.py --clean-env` | `artifacts/offline-clean-env-result.json` |
| 摄像头底层探针 | `.\.dotnet\dotnet.exe run --project desktop\tests\Laitp.CameraChecks -v quiet -- --preview artifacts\camera-preview-probe.json` | `artifacts/camera-preview-probe.json`（约 20 fps，Bgra8 1280×720） |
| 摄像头单张采集 | `.\.dotnet\dotnet.exe run --project desktop\tests\Laitp.CameraChecks -v quiet` | `artifacts/camera-capture.png` |
| Core 检查（C#） | `.\.dotnet\dotnet.exe run --project desktop\tests\Laitp.Core.Checks -v quiet` | 64 项通过 |

> 最近复测：2026-11-20 复测 stage 16.0 s / 30 张预测 17.0 s（含预测合计约 33.0 s），训练阶段 6.2 s；数字随负载波动，以 `artifacts/classroom-rehearsal/result.json` 为准。

## 5. 目标机验收留证建议

1. 解压离线包到中文/空格路径，双击 `check-bundle.bat`，保存完整输出截图。
2. 按[验收清单](acceptance-checklist.md)逐项执行，每步保留：截图、界面结果 JSON（如适用）、训练产物 ID、耗时记录。
3. 摄像头项额外保存 `ui_camera.ps1 -Screenshot` 生成的预览截图。
4. 将 `artifacts/` 与验收记录一并归档；`artifacts/` 不在版本库中，需单独备份。

## 6. 当前证据快照（2026-11-23）

| 项目 | 值 |
| --- | --- |
| 精简包 | `dist/laitp-offline-lean.zip`，SHA-256 见同名 `.sha256` 文件 |
| Python 测试 | 483 passed |
| Core 检查 | 64 项通过 |
| 一键验证 | 16 步通过（摄像头步骤按要求跳过） |
| 真实数据准确率 | 约 0.917（Fashion-MNIST 3 类，构造划分） |
| 摄像头预览 | 约 20–21 fps（DroidCam 虚拟摄像头） |
| 解包暖启动 | 窗口约 0.8 s、自检完成约 1.6 s（此前测量） |

证据文件会随重新验证而刷新；引用具体数字时请同时注明生成时间与命令。
