using System.IO;
using Laitp.Core;
using Windows.Devices.Enumeration;
using Windows.Graphics.Imaging;
using Windows.Media.Capture;
using Windows.Media.Capture.Frames;
using Windows.Media.MediaProperties;
using Windows.Storage.Streams;

namespace Laitp.Desktop;

/// <summary>
/// 摄像头采集：枚举已启用的视频采集设备，用第一个设备拍一张 PNG。
/// 使用 WinRT MediaCapture（开发机已用 DroidCam 虚拟摄像头验证）。
/// </summary>
public static class CameraCapture
{
    public sealed record CameraDevice(string Id, string Name);

    public sealed record CaptureResult(string Path, string DeviceName, int Bytes, double Seconds);

    /// <summary>
    /// 连续帧预览会话：读取 Bgra8 帧并编码为 JPEG 交给界面显示。
    /// 编码期间到达的帧会被丢弃，避免积压；实测帧率取决于设备与编码速度。
    /// </summary>
    public sealed class PreviewSession : IAsyncDisposable
    {
        private readonly MediaCapture _capture;
        private readonly MediaFrameReader _reader;
        private readonly Action<byte[]> _onJpegFrame;
        private int _encoding;

        private PreviewSession(
            MediaCapture capture, MediaFrameReader reader, Action<byte[]> onJpegFrame)
        {
            _capture = capture;
            _reader = reader;
            _onJpegFrame = onJpegFrame;
        }

        public static async Task<PreviewSession> StartAsync(
            Action<byte[]> onJpegFrame, string? deviceId = null)
        {
            try
            {
                return await StartCoreAsync(onJpegFrame, deviceId);
            }
            catch (InvalidOperationException)
            {
                throw;
            }
            catch (Exception error)
            {
                throw new InvalidOperationException(
                    CameraErrors.Describe(error), error);
            }
        }

        private static async Task<PreviewSession> StartCoreAsync(
            Action<byte[]> onJpegFrame, string? deviceId)
        {
            var device = await FindDeviceAsync(deviceId);
            var capture = new MediaCapture();
            await capture.InitializeAsync(new MediaCaptureInitializationSettings
            {
                StreamingCaptureMode = StreamingCaptureMode.Video,
                VideoDeviceId = device.Id,
                MemoryPreference = MediaCaptureMemoryPreference.Cpu,
            });
            var source = capture.FrameSources.Values.FirstOrDefault(
                             item => item.Info.SourceKind == MediaFrameSourceKind.Color)
                         ?? throw new InvalidOperationException("摄像头没有可用的彩色视频源");
            var reader = await capture.CreateFrameReaderAsync(
                source, MediaEncodingSubtypes.Bgra8);
            var session = new PreviewSession(capture, reader, onJpegFrame);
            reader.FrameArrived += session.OnFrameArrived;
            var status = await reader.StartAsync();
            if (status != MediaFrameReaderStartStatus.Success)
            {
                await session.DisposeAsync();
                throw new InvalidOperationException($"预览启动失败：{status}");
            }

            return session;
        }

        private async void OnFrameArrived(
            MediaFrameReader sender, MediaFrameArrivedEventArgs args)
        {
            if (Interlocked.Exchange(ref _encoding, 1) == 1)
            {
                return;
            }

            try
            {
                using var frame = sender.TryAcquireLatestFrame();
                var bitmap = frame?.VideoMediaFrame?.SoftwareBitmap;
                if (bitmap is null)
                {
                    return;
                }

                using var stream = new InMemoryRandomAccessStream();
                var encoder = await BitmapEncoder.CreateAsync(
                    BitmapEncoder.JpegEncoderId, stream);
                encoder.SetSoftwareBitmap(bitmap);
                await encoder.FlushAsync();
                stream.Seek(0);
                var bytes = new byte[stream.Size];
                using var reader = new DataReader(stream.GetInputStreamAt(0));
                await reader.LoadAsync((uint)stream.Size);
                reader.ReadBytes(bytes);
                _onJpegFrame(bytes);
            }
            catch (Exception)
            {
                // 单帧失败不终止预览；界面侧会按实际帧率显示。
            }
            finally
            {
                Interlocked.Exchange(ref _encoding, 0);
            }
        }

        public async ValueTask DisposeAsync()
        {
            _reader.FrameArrived -= OnFrameArrived;
            try
            {
                await _reader.StopAsync();
            }
            catch (Exception)
            {
                // 设备已断开时停止可能失败，忽略。
            }

            _reader.Dispose();
            _capture.Dispose();
        }
    }

    public static async Task<IReadOnlyList<CameraDevice>> ListDevicesAsync()
    {
        var devices = await DeviceInformation.FindAllAsync(DeviceClass.VideoCapture);
        return devices
            .Where(device => device.IsEnabled)
            .Select(device => new CameraDevice(device.Id, device.Name))
            .ToList();
    }

    private static async Task<DeviceInformation> FindDeviceAsync(string? deviceId)
    {
        var devices = await DeviceInformation.FindAllAsync(DeviceClass.VideoCapture);
        var enabled = devices.Where(device => device.IsEnabled).ToList();
        if (enabled.Count == 0)
        {
            throw new InvalidOperationException(
                "未找到可用的摄像头（设备可能被禁用或未连接）");
        }

        if (!string.IsNullOrEmpty(deviceId))
        {
            var match = enabled.FirstOrDefault(device => device.Id == deviceId);
            if (match is not null)
            {
                return match;
            }
        }

        return enabled[0];
    }

    public static async Task<IReadOnlyList<string>> ListDeviceNamesAsync()
    {
        var devices = await ListDevicesAsync();
        return devices.Select(device => device.Name).ToList();
    }

    public static async Task<CaptureResult> CaptureAsync(
        string outputDirectory, string? deviceId = null)
    {
        Directory.CreateDirectory(outputDirectory);
        try
        {
            var device = await FindDeviceAsync(deviceId);
            return await CaptureCoreAsync(device, outputDirectory);
        }
        catch (InvalidOperationException)
        {
            throw;
        }
        catch (Exception error)
        {
            throw new InvalidOperationException(
                CameraErrors.Describe(error), error);
        }
    }

    private static async Task<CaptureResult> CaptureCoreAsync(
        DeviceInformation device, string outputDirectory)
    {

        var path = Path.Combine(
            outputDirectory, $"camera-{DateTime.Now:yyyyMMdd-HHmmss-fff}.png");
        var watch = System.Diagnostics.Stopwatch.StartNew();
        using var capture = new MediaCapture();
        await capture.InitializeAsync(new MediaCaptureInitializationSettings
        {
            StreamingCaptureMode = StreamingCaptureMode.Video,
            VideoDeviceId = device.Id,
        });

        using var stream = new InMemoryRandomAccessStream();
        await capture.CapturePhotoToStreamAsync(ImageEncodingProperties.CreatePng(), stream);
        stream.Seek(0);

        var bytes = new byte[stream.Size];
        using (var reader = new DataReader(stream.GetInputStreamAt(0)))
        {
            await reader.LoadAsync((uint)stream.Size);
            reader.ReadBytes(bytes);
        }

        await File.WriteAllBytesAsync(path, bytes);
        return new CaptureResult(
            path, device.Name, bytes.Length, Math.Round(watch.Elapsed.TotalSeconds, 2));
    }
}
