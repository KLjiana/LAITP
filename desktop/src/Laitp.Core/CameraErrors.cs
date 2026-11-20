using System;

namespace Laitp.Core;

/// <summary>把摄像头相关异常转换为课堂可读提示。</summary>
public static class CameraErrors
{
    public static string Describe(Exception error) => Describe(error.HResult, error.Message);

    public static string Describe(int hresult, string message) => hresult switch
    {
        unchecked((int)0x80070005) =>
            "摄像头权限被拒绝：请在 Windows 设置 → 隐私 → 相机 中允许应用访问摄像头",
        unchecked((int)0x800700AA) =>
            "摄像头被其他程序占用：请关闭正在使用摄像头的程序后重试",
        unchecked((int)0x80070002) or unchecked((int)0x80070490) =>
            "未找到摄像头设备：请检查连接，或在设备管理器中启用设备",
        unchecked((int)0x80070015) =>
            "摄像头未就绪：请稍后重试或重新插拔设备",
        _ => $"摄像头操作失败（0x{hresult:X8}）：{message}",
    };
}
