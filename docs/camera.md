# 摄像头能力（开发记录）

状态：**底层单张拍照与应用界面采集已在本机验证**（通过 DroidCam 虚拟摄像头）；物理摄像头仍被禁用，课堂真实摄像头与目标机器未验证。摄像头自动化测试自 2026-11-18 起按要求停止。

## 1. 诊断工具

`desktop/tests/Laitp.CameraChecks`（WinRT `Windows.Media.Capture`）用于枚举视频采集设备并尝试拍一张 PNG：

```powershell
.\.dotnet\dotnet.exe run --project desktop\tests\Laitp.CameraChecks -v quiet -- artifacts\camera-capture.png
```

输出 JSON：设备列表（ID、名称、是否启用）与采集结果（耗时、字节数、错误）。没有已启用设备时记录跳过。

## 2. 本机结果（2026-11-18）

| 项目 | 结果 |
| --- | --- |
| `HD Webcam`（物理摄像头） | 状态 Error，**Code 22（设备已禁用）**；驱动 Microsoft 10.0.26100.9444；`pnputil /enable-device` 返回 Access is denied（需管理员） |
| `DroidCam Video`（虚拟摄像头） | 枚举到 1 个已启用设备 |
| 采集 | 成功，耗时 1.75 s，输出 `artifacts/camera-capture.png`（PNG 1280×720 RGB，20,445 B） |

说明：DroidCam 依赖手机端应用与连接；验证到的是 WinRT 采集链路可用，不代表课堂真实摄像头可用。

## 3. 应用内采集（已实现）

界面“数据导入”区新增摄像头行：设备下拉框（`CameraDeviceBox`，启动时自动刷新，也可点“检测/刷新”）、“拍照”（`CameraCaptureButton`）、“连拍 N 张”（`CameraBurstCountBox` + `CameraBurstButton`，1–20 张）与“开始/停止预览”（`CameraPreviewButton`/`CameraPreviewStopButton`）。拍照与预览均使用当前选中设备；连拍完成后一次导入当前类别同一批次；无设备时状态提示“未找到可用摄像头（设备可能被禁用或未连接，可尝试以管理员启用设备）”。

预览使用 `MediaFrameReader`（Bgra8 + CPU 内存）连续取帧，编码为 JPEG 后显示在样本预览区，状态显示实测帧率；启动失败或超时会回退到“周期单帧拍摄”预览。停止后显示“预览已停止（N 帧，平均 X fps）”。

本机拍照耗时约 0.27–0.73 s/张（19 KB PNG）；连续预览实测 **约 21 fps**（DroidCam 1280×720，8 秒约 167 帧）；解包目录暖启动窗口约 0.83 s、自动自检完成约 1.59 s，自包含桌面暖启动约 1.72 s / 1.99 s（见[性能基准](performance-m0.md#8-桌面与摄像头耗时2026-11-18)）。

长时间预览稳定性（`scripts/ui_preview_stability.ps1 -Seconds 60`）：60 秒连续预览保持 **约 20.9 fps（1313 帧）**，进程内存 264.5–272.4 MB、句柄约 1200，首末内存变化 −0.6 MB，无持续增长或掉帧。

界面自动化脚本 `scripts/ui_camera.ps1 -Screenshot` 可在预览中与数据清单生成后各留一张窗口截图（`artifacts/ui-screenshots/`），作为课堂验收留证；摄像头自动化测试自 2026-11-18 起按要求停止，该命令仅供需要时人工执行。

界面自动化（历史记录）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\ui_camera.ps1 -ProjectParent <临时目录>
```

本机结果（DroidCam Video）：新建 2 类项目 → 每类拍照 2 次，4 次均“拍照成功（DroidCam Video，19 KB），已导入类别 …”；数据清单合计 4 张；数据检查因 4 张画面相同返回“数据检查未通过（3 个问题）”（`DATASET_CONTENT_DUPLICATE`），属静态虚拟摄像头的预期结果，也验证了重复内容校验生效。

## 4. 错误提示

`Laitp.Core.CameraErrors` 将采集异常映射为课堂可读提示（检测、拍照、连拍、预览失败时显示在状态栏）：

| 情况 | 提示 |
| --- | --- |
| 权限被拒绝（`0x80070005`） | “摄像头权限被拒绝：请在 Windows 设置 → 隐私 → 相机 中允许应用访问摄像头” |
| 设备被占用（`0x800700AA`） | “摄像头被其他程序占用：请关闭正在使用摄像头的程序后重试” |
| 设备不存在（`0x80070002`/`0x80070490`） | “未找到摄像头设备：请检查连接，或在设备管理器中启用设备” |
| 设备未就绪（`0x80070015`） | “摄像头未就绪：请稍后重试或重新插拔设备” |
| 其他 | 带 HRESULT 的通用错误 |

本机 `HD Webcam` 仍被禁用（Code 22），因此权限/占用等错误场景尚未在真实设备上触发；映射逻辑有 Core 检查覆盖。

## 5. 已实现与未实现

已实现：
- 视频采集设备枚举与**设备选择**（下拉框 + 检测/刷新）
- 单张拍照并保存 PNG（`MediaCapture.CapturePhotoToStreamAsync`）；拍照后按类别导入项目
- 连拍（1–20 张，同批次导入；重复内容按项目规则去重）
- “开始/停止预览”
- 高帧率预览：`MediaFrameReader`（Bgra8、CPU 内存）→ JPEG → WPF 图像，实测约 21 fps；失败时回退到周期单帧预览

未实现/未验证：
- 多摄像头并发、权限被拒时的专门提示（当前以状态文本显示错误）
- 物理摄像头（当前被禁用）、目标 Windows 机器、真实课堂环境

## 6. 后续计划

1. 在启用物理摄像头的机器与目标机验证真实采集与课堂使用。
2. 采集后可直接进入训练流程（当前需手动点击检查/训练）。

> 实时预览与设备选择已实现；权限/占用/缺失等错误提示见第 4 节。摄像头自动化测试自 2026-11-18 起按要求停止，如需复验参照第 3 节命令人工执行。
