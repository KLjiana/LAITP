# 项目文件格式（M1 基础）

编制日期：2026-11-17

状态：`project.json` 的创建、读取、保存与校验已实现；WPF 外壳可新建/打开/编辑项目（改名、增删类别、类别改名）、逐批/批量/测试集导入、样本重命名/删除、检查数据（含严格验收）、训练并自动发布、历史导出、预测、摄像头拍照/连拍导入与高帧率预览，并在关闭重开后恢复项目。摄像头记录说明：真实物理摄像头未验证；摄像头自动化测试已于 2026-11-18 按要求停止，界面采集以 DroidCam 历史记录为准。自动保存仍为随操作即时写盘，尚无版本化快照/回滚。

所属路线：[总体路线 M1：第一堂课](roadmap.md)。界面见[桌面外壳](desktop-shell.md)，数据清单见[数据与运行基线](data-and-runtime-baseline.md)，模型产物见[契约校验说明](contract-validation.md)。

## 1. 目录与文件

按路线图第 5 节的项目布局，项目根目录包含 `project.json`，其他内容沿用相对路径引用：

```text
学生项目/
  project.json
  data/
    dataset-manifest.json      # 可选；由数据命令生成并在 project.json 中引用
    images/  test-images/
  runs/<训练记录 ID>/          # 训练产物（含 training-artifact.json）
  exports/<产物 ID>/           # model-package/ 与 conversion-record.json
  validation-runs/  logs/
```

`project.json` 示例：

```json
{
  "project_format": "1.0",
  "project_id": "proj-20261117-0001",
  "name": "我的分类项目",
  "task": "image_classification",
  "created_at": "2026-11-17T10:00:00+08:00",
  "updated_at": "2026-11-17T10:00:00+08:00",
  "classes": ["水杯", "书本", "笔袋"],
  "dataset_manifest": "data/dataset-manifest.json",
  "models": [
    {
      "artifact_id": "art-20261117-0001",
      "kind": "export",
      "path": "exports/art-20261117-0001/model-package/manifest.json",
      "sha256": "…64 位小写十六进制…",
      "created_at": "2026-11-17T11:00:00+08:00"
    }
  ],
  "current_model_artifact_id": "art-20261117-0001"
}
```

## 2. 字段规则

| 字段 | 规则 |
| --- | --- |
| `project_format` | 必填，`major.minor`；当前支持 `1.0`，主版本或更高次版本直接拒绝 |
| `project_id` | 必填，字母数字开头，仅含字母数字与 `.` `_` `-` |
| `name` | 必填，1～120 字符，允许中文与空格，首尾不能是空白或控制字符 |
| `task` | 必填，首版仅 `image_classification` |
| `created_at` / `updated_at` | 必填，带时区的 RFC 3339 时间 |
| `classes` | 必填、有序、唯一、至少 2 个；类别名同时作为目录名，必须是可移植的相对路径段 |
| `dataset_manifest` | 可选或 `null`；相对项目根目录的路径 |
| `models` | 模型引用数组；`artifact_id` 唯一，`kind` 为 `training` 或 `export`，`path` 为包内相对路径，`sha256` 为文件摘要 |
| `current_model_artifact_id` | `null` 或必须存在于 `models` 中 |

约束：

- 所有路径都是相对路径，禁止绝对路径、盘符、反斜杠、`..` 与空段；复制项目目录后仍可打开。
- 训练产物登记与模型包发布分离：`publish-training` 先登记训练产物，再导出 ONNX 并设为当前模型；导出失败时项目只保留训练记录，不会出现“半发布”的当前模型。
- 项目编辑：改名只改显示名称；添加类别后新类暂无数据，清单重建会失败并返回 `manifest_error`，导入数据后可重建；删除类别至少保留 2 个，类中仍有图片时必须显式 `--with-data`，否则拒绝。
- 类别顺序就是类别 ID；`verify` 会与数据清单的 `classes` 比较，顺序不一致直接报错。
- `models[].sha256` 指向具体文件（训练记录或 ONNX 清单），用于发现项目内文件被替换或损坏；它不是模型包契约校验的替代品。
- 保存采用“写临时文件 → 整体替换”；写入失败时保留原文件并清理临时文件。

## 3. 命令

```powershell
# 新建项目（类别顺序即类别 ID）；--project-id 省略时自动生成 proj-YYYYMMDD-HHMMSS
python -m backend.project create --root 学生项目 `
  --name 我的分类项目 --classes 水杯 书本 笔袋

# 查看项目摘要
python -m backend.project inspect 学生项目\project.json

# 校验项目引用、数据清单类别与模型文件摘要
python -m backend.project verify --root 学生项目

# 登记训练/导出产物（自动计算文件摘要）
python -m backend.project add-model --root 学生项目 `
  --artifact-id art-20261117-0001 --kind export `
  --path exports/art-20261117-0001/model-package/manifest.json

# 设置当前模型
python -m backend.project set-current --root 学生项目 --artifact-id art-20261117-0001

# 训练完成后登记训练产物（不设为当前模型；路径可为项目相对或绝对）
python -m backend.project register-training --root 学生项目 --run runs\run-20261117-0001

# 导出完成后登记 ONNX 模型包并设为当前模型
python -m backend.project register-export --root 学生项目 `
  --artifact-id art-20261117-0001 `
  --manifest exports\art-20261117-0001\model-package\manifest.json

# 训练后一键发布：登记训练产物 → 导出 ONNX → 登记模型包并设为当前模型
python -m backend.project publish-training --root 学生项目 --run runs\run-20261117-0001

# 批量导入图片（自动转 PNG、去重并重建数据清单）
python -m backend.project import --root 学生项目 --class 水杯 --source D:\照片\水杯 --batch batch-1

# 按 来源/类别/批次 目录结构一次导入多类多批（批次目录名即批次名；
# 无子目录时整目录作一个批次，可用 --batch 统一批次名）
python -m backend.project import-tree --root 学生项目 --source D:\课堂照片

# 仅重建数据清单
python -m backend.project rebuild-dataset --root 学生项目

# 列出样本 / 删除单个样本（删除后自动重建清单）
python -m backend.project samples --root 学生项目
python -m backend.project delete-sample --root 学生项目 --path images\水杯\batch-1\001.png

# 项目编辑：改名、添加类别、删除类别（有数据时需显式 --with-data）
python -m backend.project rename --root 学生项目 --name 新名字
python -m backend.project add-class --root 学生项目 --name 桌子
python -m backend.project remove-class --root 学生项目 --name 桌子 --with-data

# 训练前数据检查（--require-test 要求独立测试集且每类至少 1 张）
python -m backend.project check-dataset --root 学生项目

# 严格验收检查（示例：每类至少 30 训练 / 8 验证 / 10 测试）
python -m backend.project check-dataset --root 学生项目 `
  --require-test --min-train 30 --min-val 8 --min-test 10

# 类别改名（同步移动数据目录）、样本重命名
python -m backend.project rename-class --root 学生项目 --old 书本 --new 课本
python -m backend.project rename-sample --root 学生项目 --path images\水杯\batch-1\001.png --name 课堂样本

# 训练历史与重新导出（export-run 会把所选运行发布为当前模型）
python -m backend.project runs --root 学生项目
python -m backend.project export-run --root 学生项目 --run run-20261117-0001
```

标准输出为 UTF-8 JSON，退出码 `0` 成功、`1` 失败。

## 4. 错误码

| 错误码 | 含义 |
| --- | --- |
| `PROJECT_JSON_INVALID` | 文件不是有效 UTF-8 JSON |
| `PROJECT_SCHEMA_INVALID` | 不符合 Schema（缺字段、未知字段、路径或时间格式非法等） |
| `PROJECT_VERSION_UNSUPPORTED_MAJOR` | 项目格式主版本不受支持 |
| `PROJECT_VERSION_UNSUPPORTED_MINOR` | 项目格式次版本高于支持范围 |
| `PROJECT_ALREADY_EXISTS` | 目标目录已有 `project.json`，拒绝覆盖 |
| `PROJECT_NOT_FOUND` | 项目文件不存在 |
| `PROJECT_CLASS_INVALID` | 类别为空、重复、首尾空白或不能作为目录名 |
| `PROJECT_MODEL_INVALID` | 产物 ID 重复、类型未知、路径越界或文件不存在 |
| `PROJECT_MODEL_DIGEST_MISMATCH` | 模型文件摘要与记录不一致 |
| `PROJECT_DATASET_MISMATCH` | 数据清单缺失、无法读取或类别顺序与项目不一致 |
| `PROJECT_IMPORT_INVALID` | 导入来源不存在、没有支持图片、批次名非法或 split 非法 |
| `PROJECT_SAVE_FAILED` | 写入失败；原文件保持不变 |

## 5. 界面接入

- 桌面外壳新增“项目文件”输入框与“打开项目”按钮；打开后显示项目名称、类别列表与模型数量。
- 若项目设置了当前模型，界面自动把模型包目录填为清单所在目录，可直接预测。
- 界面只做只读解析与基本结构校验（格式版本、类别、模型路径、当前模型存在）；文件摘要、数据清单一致性与契约校验仍由 Python 命令负责。
- 界面已接入新建/编辑项目、采集导入、样本管理、检查数据、训练发布、历史导出与预测；所有写操作即时落盘。

## 6. 本机验证

| 检查 | 结果 |
| --- | --- |
| Python 项目测试 | 86 个用例通过（项目 32 + 数据集 17 + 编辑 9 + 数据检查 11 + 改名 9 + 训练历史 8）：创建/读取/保存、版本与字段拒绝、摘要与路径检查、原子保存失败、复制后可打开、训练/导出登记、一键发布、批量导入、样本列表与删除、项目编辑、训练前/严格验收检查、类别/样本改名、训练历史与重新导出、CLI |
| C# 桌面自检 | 47 项通过（项目文件、训练报告、数据清单摘要、样本列表、数据检查报告与策略、训练历史与拒绝场景） |
| `dotnet build` | 0 警告 0 错误 |
| WPF 启动冒烟 | 进程启动后存活 4 秒未崩溃（未做界面交互验证） |
| 训练→发布→预测链路 | 训练运行 `run-pub-0001`；`publish-training` 生成 `art-run-pub-0001`，项目 `verify` 通过，当前模型指向该导出包；随后 `predict` 成功返回 3 类概率 |
| 批量导入链路 | 3 类 × 2 批次逐一导入：文件转为 PNG、清单重建后 6 个样本（训练 3 / 验证 3），类别顺序与项目一致 |

验证均在本开发机、使用临时构造数据，不代表目标机器或课堂流程。以上为本节编写时（2026-11-17）的本机快照；当前全量测试与 Core 检查数量见[验证证据索引](verification-evidence.md)（523 项 / 64 项）。

## 7. 限制与下一步

- 项目文件尚不记录样本/标注清单、训练历史摘要与最近使用时间；样本信息仍由数据清单承担。
- 没有并发写保护、锁文件或项目迁移工具；旧格式变化需显式迁移。
- `verify` 不替代模型包契约校验；发布前仍需 `python -m backend.contracts package`。
- 界面不提供任意模型包的手工登记或历史模型回滚；模型登记由训练发布与历史运行导出完成。
- 下一步：目标机验收、真实课堂数据与物理摄像头验证（见[项目状态报告](status-report.md)与[剩余工作与解锁条件](remaining-work.md)）。
