# 任务协议与父进程控制（T07）

编制日期：2026-11-17

状态：按行 JSON 消息、工作进程与最小父进程已实现并通过本地测试；C#/WPF 任务管理已接入（见[桌面外壳](desktop-shell.md)），未在目标 Windows 机器上做进程集成验收。
本文不表示目标机界面集成或完整项目管理已经可用。

所属计划：[M0-01 分类最小闭环](m0-01-classification-plan.md)。消息字段约束见[模型接口与产物契约](model-contract.md)第 6 节，Schema 为 `schemas/message-envelope.schema.json`。

## 1. 消息格式

- 标准输出每行一条 UTF-8 JSON 消息，标准错误只写日志；每条消息单独通过 Schema 校验后才写出。
- 消息序号从 `0` 开始、同一任务内递增；接收方要求严格递增，重复或倒序消息会被拒绝。
- `artifact_id` 在操作已有模型时填写；新产物在整体发布后由 `result` 消息携带，信封字段与结果引用必须一致。
- 接收方限制单条消息大小（当前 1 MiB），超限行按协议错误记录并忽略。

工作进程命令：

```powershell
# 预测
python -m backend.runtime.worker predict --package <模型包> --image <图片> `
  --request-id req-1 --project-id proj-1 --task-id task-1

# 校验（含固定样本）
python -m backend.runtime.worker validate --package <模型包> `
  --request-id req-2 --project-id proj-1 --task-id task-2

# 训练
python -m backend.runtime.worker train --dataset <清单> --data-root <目录> `
  --output <输出目录> --run-id run-... `
  --request-id req-3 --project-id proj-1 --task-id task-3
```

进度阶段：`predict` 为 `load`、`inference`；`validate` 为 `load`、`fixed_samples`；`train` 为 `accepted`、`load`、`feature_extraction`（按图片数）、`head_training`（按轮次）、`publish`。失败时发送 `error` 消息并以非零码退出。

## 2. 父进程语义

`backend/runtime/supervisor.py` 提供最小父进程，不依赖 WPF：

| 情况 | 行为 |
| --- | --- |
| 消息项目/请求/任务 ID 与当前任务不一致 | 拒绝（`TASK_IDENTITY_MISMATCH`），不改变任务状态 |
| 序号未严格递增 | 拒绝（`TASK_SEQUENCE_INVALID`） |
| 已到终态后又有消息（含迟到的成功结果） | 拒绝（`TASK_LATE_MESSAGE`），终态不变 |
| 消息不符合 Schema | 拒绝（`TASK_ENVELOPE_INVALID`） |
| 子进程未发终态就退出 | 任务失败（`TASK_CHILD_EXITED`），附退出码与标准错误尾部 |
| 取消 | 任务进入 `cancelling`，终止子进程后置为 `cancelled`；此后的成功消息只记录为拒绝 |

任务状态：`running`、`cancelling`、`succeeded`、`failed`、`cancelled`。终态不可被覆盖。

## 3. 取消与未完成产物

- 训练/导出先把文件写入临时目录，全部校验通过后才整体改名发布；`run_id`/`artifact_id` 已存在时拒绝覆盖。
- 取消训练工作进程时直接终止子进程，已完成发布的产物目录不存在（发布只在最后一步发生），未完成的临时目录以 `.tmp-*` 命名，便于识别与清理。
- 父进程不会因为取消后收到的成功消息切换当前模型或改写任务终态。

测试验证：启动真实训练工作进程，收到首条进度后取消，运行目录 `runs/<run_id>` 不存在，任务终态为 `cancelled`。

## 4. 错误码

| 错误码 | 含义 |
| --- | --- |
| `TASK_ENVELOPE_INVALID` | 消息行不是有效 JSON 或不符合信封 Schema |
| `TASK_IDENTITY_MISMATCH` | 消息的项目/请求/任务归属与当前任务不一致 |
| `TASK_SEQUENCE_INVALID` | 序号重复或倒退 |
| `TASK_LATE_MESSAGE` | 终态之后到达的消息（含迟到的成功结果） |
| `TASK_CHILD_EXITED` | 子进程未发送终态消息就退出 |
| `TASK_CANCEL_TIMEOUT` | 取消后子进程未在超时内退出（预留：当前实现会强制终止） |
| `TASK_INTERNAL_ERROR` | 工作进程内部异常，已转换为协议错误 |

工作进程的 `error` 消息沿用契约错误码（`CONTRACT_*`、`RUNTIME_*`、`TRAINING_*`），`stage` 对应出错阶段。

## 5. 本机验证

环境：Windows 11（10.0.26200）、Python 3.12.1、onnxruntime 1.23.2。全部为构造数据，不代表真实效果。

| 场景 | 结果 |
| --- | --- |
| 真实 `predict` 工作进程 | 4 条消息，序号 0～3，`succeeded`，携带产物 ID，无拒绝 |
| 模型包不存在 | `error` 消息 `CONTRACT_PACKAGE_NOT_FOUND`，任务 `failed`，退出码 1 |
| 慢速工作进程取消 | 任务 `cancelled`，无结果，子进程已退出，重复取消返回 false |
| 迟到的重复结果 | 第一条结果生效，第二条记为 `TASK_LATE_MESSAGE`，终态不变 |
| 未发终态退出（码 3） | 任务 `failed`，`TASK_CHILD_EXITED` |
| 非协议行输出 | 记为 `invalid_line`，随后按未发终态处理为失败 |
| 训练中取消 | 任务 `cancelled`，`runs/<run_id>` 未生成 |

对应测试：`tests/test_task_protocol.py`（15 个用例）。

## 6. 未验证与限制

- C#/WPF 任务管理已接入（桌面外壳可发出训练/预测任务，见[桌面外壳](desktop-shell.md)）；未在目标 Windows 机器或真实界面验证取消、重试与结果切换。
- 训练进度为粗粒度阶段（加载、特征提取、每轮分类头、发布），未细分到单张图片内的耗时。
- 未做大量并发任务、长时间运行或大消息吞吐测试；标准输出按行读取，超长行会被拒绝。
- 未在目标 Windows 电脑上验证进程启动时间、取消响应时间与退出清理。
- `TASK_CANCEL_TIMEOUT` 目前只作为预留错误码，取消实现直接强制终止。
