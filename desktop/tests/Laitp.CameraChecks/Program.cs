using System.Diagnostics;
using System.Text.Json;
using Windows.Devices.Enumeration;
using Windows.Graphics.Imaging;
using Windows.Media.Capture;
using Windows.Media.Capture.Frames;
using Windows.Media.MediaProperties;
using Windows.Storage.Streams;

namespace Laitp.CameraChecks;

/// <summary>
/// 摄像头能力检查：枚举视频采集设备，并尝试用第一个可用设备拍一张 PNG。
/// 输出 JSON；枚举成功即返回 0，采集失败会记录在结果中（设备被禁用时属预期）。
/// 用法：dotnet run --project desktop\tests\Laitp.CameraChecks [-- <输出 png 路径>]
/// </summary>
internal static class Program
{
    private static async Task<int> Main(string[] args)
    {
        if (args.Length > 0 && args[0] == "--preview")
        {
            return await PreviewProbeAsync(args.Length > 1 ? args[1] : "artifacts/camera-preview-probe.json");
        }

        var outputPath = Path.GetFullPath(
            args.Length > 0
                ? args[0]
                : Path.Combine("artifacts", "camera-capture.png"));
        Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);

        var report = new Dictionary<string, object?>
        {
            ["generated_at"] = DateTimeOffset.Now.ToString("o"),
            ["output"] = outputPath,
        };

        try
        {
            var devices = await DeviceInformation.FindAllAsync(DeviceClass.VideoCapture);
            var listed = devices.Select(device => new Dictionary<string, object?>
            {
                ["id"] = device.Id,
                ["name"] = device.Name,
                ["enabled"] = device.IsEnabled,
            }).ToList();
            report["ok"] = true;
            report["device_count"] = listed.Count;
            report["devices"] = listed;

            var candidates = devices.Where(device => device.IsEnabled).ToList();
            if (candidates.Count == 0)
            {
                report["capture"] = "skipped：没有已启用的视频采集设备";
            }
            else
            {
                foreach (var candidate in candidates)
                {
                    var result = await TryCapture(candidate.Id, outputPath);
                    result["device"] = candidate.Name;
                    report["capture"] = result;
                    if (result["ok"] is true)
                    {
                        break;
                    }
                }
            }
        }
        catch (Exception error)
        {
            report["ok"] = false;
            report["error"] = error.Message;
        }

        var json = JsonSerializer.Serialize(report, new JsonSerializerOptions
        {
            WriteIndented = true,
            Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        });
        Console.WriteLine(json);

        var success = report.TryGetValue("ok", out var ok) && ok is true;
        if (success && report.TryGetValue("capture", out var capture) &&
            capture is Dictionary<string, object?> captured &&
            captured.TryGetValue("ok", out var captureOk) && captureOk is true)
        {
            return 0;
        }

        // 设备被禁用/不可用时也返回 0：本工具用于采集环境诊断。
        return success ? 0 : 1;
    }

    private static async Task<int> PreviewProbeAsync(string outputPath)
    {
        var report = new Dictionary<string, object?>
        {
            ["generated_at"] = DateTimeOffset.Now.ToString("o"),
        };
        var frames = 0;
        var since = Stopwatch.StartNew();
        MediaCapture? capture = null;
        MediaFrameReader? reader = null;
        try
        {
            var devices = await DeviceInformation.FindAllAsync(DeviceClass.VideoCapture);
            var device = devices.FirstOrDefault(item => item.IsEnabled)
                         ?? throw new InvalidOperationException("没有已启用的视频采集设备");
            capture = new MediaCapture();
            await capture.InitializeAsync(new MediaCaptureInitializationSettings
            {
                StreamingCaptureMode = StreamingCaptureMode.Video,
                VideoDeviceId = device.Id,
                MemoryPreference = MediaCaptureMemoryPreference.Cpu,
            });
            var source = capture.FrameSources.Values.FirstOrDefault(
                             item => item.Info.SourceKind == MediaFrameSourceKind.Color)
                         ?? throw new InvalidOperationException("没有彩色视频源");
            reader = await capture.CreateFrameReaderAsync(source, MediaEncodingSubtypes.Bgra8);
            reader.FrameArrived += (sender, args2) =>
            {
                if (Interlocked.Increment(ref frames) == 1)
                {
                    using var frame = sender.TryAcquireLatestFrame();
                    var bitmap = frame?.VideoMediaFrame?.SoftwareBitmap;
                    report["first_frame_format"] = bitmap?.BitmapPixelFormat.ToString();
                    report["first_frame_size"] = bitmap is null
                        ? null
                        : $"{bitmap.PixelWidth}x{bitmap.PixelHeight}";
                }
            };
            var startStatus = await reader.StartAsync();
            report["reader_start"] = startStatus.ToString();
            await Task.Delay(5000);
            report["frames_5s"] = frames;
            report["fps"] = Math.Round(frames / Math.Max(0.001, since.Elapsed.TotalSeconds), 2);
            report["ok"] = frames > 0;
        }
        catch (Exception error)
        {
            report["ok"] = false;
            report["error"] = error.GetType().Name + "：" + error.Message;
        }
        finally
        {
            try
            {
                if (reader is not null)
                {
                    await reader.StopAsync();
                    reader.Dispose();
                }
            }
            catch (Exception)
            {
                // 忽略停止失败。
            }

            capture?.Dispose();
        }

        var json = JsonSerializer.Serialize(report, new JsonSerializerOptions
        {
            WriteIndented = true,
            Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        });
        var target = Path.GetFullPath(outputPath);
        Directory.CreateDirectory(Path.GetDirectoryName(target)!);
        await File.WriteAllTextAsync(target, json);
        Console.WriteLine(json);
        return report["ok"] is true ? 0 : 1;
    }

    private static async Task<Dictionary<string, object?>> TryCapture(
        string deviceId, string outputPath)
    {
        var watch = Stopwatch.StartNew();
        MediaCapture? capture = null;
        try
        {
            capture = new MediaCapture();
            await capture.InitializeAsync(new MediaCaptureInitializationSettings
            {
                StreamingCaptureMode = StreamingCaptureMode.Video,
                VideoDeviceId = deviceId,
            });

            using var stream = new InMemoryRandomAccessStream();
            await capture.CapturePhotoToStreamAsync(
                ImageEncodingProperties.CreatePng(), stream);
            stream.Seek(0);

            var bytes = new byte[stream.Size];
            using var reader = new DataReader(stream.GetInputStreamAt(0));
            await reader.LoadAsync((uint)stream.Size);
            reader.ReadBytes(bytes);
            await File.WriteAllBytesAsync(outputPath, bytes);

            return new Dictionary<string, object?>
            {
                ["ok"] = true,
                ["seconds"] = Math.Round(watch.Elapsed.TotalSeconds, 3),
                ["bytes"] = bytes.Length,
            };
        }
        catch (Exception error)
        {
            return new Dictionary<string, object?>
            {
                ["ok"] = false,
                ["seconds"] = Math.Round(watch.Elapsed.TotalSeconds, 3),
                ["error"] = error.GetType().Name + "：" + error.Message,
            };
        }
        finally
        {
            capture?.Dispose();
        }
    }
}
