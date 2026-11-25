# 证据文件说明

本目录存放**可随仓库分发**的小型证据 JSON（由脚本生成、可复现），弥补 `artifacts/` 不入库的问题。

| 文件 | 生成命令 | 说明 |
| --- | --- | --- |
| `k230-static-probe-real-data.json` | `python scripts/k230_model_probe.py --model artifacts/real-data/fashion-project/exports/<产物>/model-package --output docs/evidence/k230-static-probe-real-data.json` | ONNX 静态图事实（算子分布、输入输出形状、参数量、manifest SHA 匹配） |
| `preflight-sha-mismatch-sample.json` | `python scripts/preflight_target.py --zip dist/laitp-offline-lean.zip --expected-sha256 000… --output docs/evidence/preflight-sha-mismatch-sample.json` | 预检**拒绝**路径样例（SHA-256 故意给错 → `blocked`，1 个 blocker）；证明预检能拦住摘要不符的包 |
| `preflight-dev-sample.json` | `python scripts/preflight_target.py --zip dist/laitp-offline-lean.zip --output docs/evidence/preflight-dev-sample.json` | 目标机验收前环境预检样例（本机开发环境：ready，0 blocker/0 warn）；磁盘/内存/控制台代码页等数值属本机当时状态 |
| `k230-readiness-real-data.json` | `python scripts/k230_readiness.py --model artifacts/real-data/fashion-project/exports/<产物>/model-package --output docs/evidence/k230-readiness-real-data.json` | K230 启动条件自检结果（本机为 `blocked`，缺工具链/nncase/校准数据） |

## 边界

- 这些文件只证明**本机、当时**的静态事实；仓库内路径以相对形式记录（仓库外路径保留绝对形式），产物 ID 属于本机环境。
- **不构成** nncase 转换成功、量化效果或 K230 板端运行证据；相关结论须在目标板与固定工具链上重新生成。
- 重新生成时更新文件名中的产物/日期（如需要）并同步本说明。
