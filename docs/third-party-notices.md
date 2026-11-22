# 第三方组件与许可说明

本文列出离线分发包内**随附的第三方运行时与依赖**及其许可证，便于学校/机构在离线分发前做合规核对。**本文件不构成法律意见**；正式对外分发前，请按所在机构要求复核并保留随包许可文本。

## 1. 运行时

| 组件 | 版本 | 许可证 | 包内位置 / 说明 |
| --- | --- | --- | --- |
| Python | 3.12.1（便携版） | PSF-2.0 | `python/`；自带 `LICENSE.txt` |
| .NET Desktop Runtime / WPF | 8.0（自包含发布） | MIT | `desktop/app/`；随包无独立安装器 |

## 2. Python 依赖（精简包与完整包均含）

| 组件 | 版本 | 许可证 |
| --- | --- | --- |
| torch | 2.8.0+cpu | BSD-3-Clause |
| torchvision | 0.23.0+cpu | BSD-3-Clause |
| onnx | 1.19.1 | Apache-2.0 |
| onnxruntime | 1.23.2 | MIT |
| Pillow | 11.3.0 | MIT-CMU（HPND 类） |
| numpy | 2.5.5 | BSD-3-Clause（并含 0BSD/MIT/Zlib/CC0-1.0 等子许可） |
| jsonschema | 4.25.1 | MIT |
| psutil | 7.0.0 | BSD-3-Clause |

完整包另有 `vendor/wheels/` 离线 wheel 与 `vendor/wheels.sha256`；各 wheel 内自带 `*.dist-info/LICENSE*` 与 METADATA 许可字段。

## 3. 模型与权重

| 项目 | 版本/来源 | 许可证 | 说明 |
| --- | --- | --- | --- |
| MobileNetV3-Small ImageNet 预训练权重 | `mobilenet_v3_small-imagenet`（见 `configs/weights.v1.json`，SHA-256 已记录） | BSD-3-Clause（torchvision 权重） | 仅作迁移学习初始化；不随学生数据再分发原始权重 |
| 演示模型包 | `demo/model-package`（仓库内构建的演示产物） | 随本项目 | 由合成/公开样例训练，不含第三方受限素材 |

## 4. 开发/验证工具（不进入分发包运行时依赖）

| 组件 | 版本 | 许可证 |
| --- | --- | --- |
| pytest | 8.4.2 | MIT |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |

## 5. 许可文本获取

- 包内 Python 组件：`python/Lib/site-packages/<包名>-<版本>.dist-info/` 下的 `LICENSE*` 与 `METADATA`；
- Python 解释器：`python/LICENSE.txt`；
- .NET：随源码仓库的 MIT 许可；自包含运行时目录中的第三方声明以运行时发布包为准；
- wheel：`vendor/wheels/` 中各 wheel 文件内。

## 6. 边界与提醒

- 本文只覆盖**当前版本**随包组件；新增依赖、权重或工具时必须同步更新本文件与 `requirements*.txt`、`configs/weights.v1.json`。
- 本文件不改变[已知限制与验收边界](known-limitations.md)中的证据边界；许可核对不等于目标机验收。
