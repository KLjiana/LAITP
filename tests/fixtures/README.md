# 契约样例

本目录是 JSON Schema 的静态样例，用于人工阅读和结构校验测试。

- `manifests/valid-classification.json`：结构完整的分类产物清单。
- `manifests/invalid-*.json`：每次只破坏一个条件，用于确认对应拒绝原因。
- `envelopes/valid-*.json`：进度消息与预测结果消息的有效样例。
- `envelopes/invalid-*.json`：缺少必填字段、未知消息类型、版本不兼容和产物 ID 不一致的样例。
- `datasets/valid-classification.json`：分类数据清单的有效样例（类别、批次与划分）。
- `workers/*.py`：T07 协议测试用的假工作进程（慢速、未发终态退出、重复结果、非协议行）。

注意：

1. 清单样例中的 SHA-256 是占位值（`000…0`），只用于结构校验。文件摘要、标签数量、真实张量和运行时兼容性必须用生成的完整产物包验证，见 `tests/test_manifest_package.py`；数据清单的摘要与文件检查见 `tests/test_dataset.py`。
2. `manifests/invalid-traversal-path.json` 在 Schema 层面结构合法（`../model.onnx`），目录穿越由路径校验器返回 `CONTRACT_PATH_INVALID`。这正说明 Schema 不能替代语义校验。
3. 样例中的类别、路径和版本仅作演示，不代表已实现的训练或推理能力。
