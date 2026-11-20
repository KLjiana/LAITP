using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Laitp.Core;

public sealed record SelfTestCheck
{
    [JsonPropertyName("name")] public string Name { get; init; } = string.Empty;
    [JsonPropertyName("ok")] public bool Ok { get; init; }
    [JsonPropertyName("detail")] public string Detail { get; init; } = string.Empty;
}

public sealed record SelfTestReport
{
    [JsonPropertyName("ok")] public bool Ok { get; init; }
    [JsonPropertyName("generated_at")] public string GeneratedAt { get; init; } = string.Empty;
    [JsonPropertyName("app_directory")] public string AppDirectory { get; init; } = string.Empty;
    [JsonPropertyName("repository_root")] public string? RepositoryRoot { get; init; }
    [JsonPropertyName("python")] public string? Python { get; init; }
    [JsonPropertyName("os")] public string Os { get; init; } = string.Empty;
    [JsonPropertyName("checks")] public List<SelfTestCheck> Checks { get; init; } = new();
}

/// <summary>
/// 首次运行自检：确认包根、Python、后端导入与工作进程可用。
/// 供离线包在启动界面前做“环境是否就绪”检查；结果写入 JSON 文件。
/// </summary>
public static class SelfTest
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true,
    };

    public static SelfTestReport RunChecks()
    {
        var checks = new List<SelfTestCheck>();
        var root = WorkspaceLocator.FindRepositoryRoot(AppContext.BaseDirectory);
        checks.Add(new SelfTestCheck
        {
            Name = "repository_root",
            Ok = root is not null,
            Detail = root ?? "未找到仓库根目录（可设置 LAITP_HOME）",
        });

        var python = root is null ? null : WorkspaceLocator.FindPython(root);
        checks.Add(new SelfTestCheck
        {
            Name = "python",
            Ok = python is not null,
            Detail = python ?? "未找到 Python（可设置 LAITP_PYTHON）",
        });

        if (root is not null && python is not null)
        {
            checks.Add(RunProcess(
                "backend_import", python, root,
                new[] { "-c", "import backend.runtime.worker" }));

            var package = Path.Combine(root, "demo", "model-package");
            var image = Path.Combine(root, "demo", "test.png");
            if (Directory.Exists(package) && File.Exists(image))
            {
                checks.Add(RunProcess(
                    "worker_predict", python, root,
                    new[]
                    {
                        "-m", "backend.runtime.worker", "predict",
                        "--package", package,
                        "--image", image,
                        "--request-id", "req-self-test",
                        "--project-id", "proj-self-test",
                        "--task-id", "task-self-test",
                    },
                    requireResult: true));
            }
            else
            {
                checks.Add(new SelfTestCheck
                {
                    Name = "worker_predict",
                    Ok = true,
                    Detail = "跳过：未找到 demo/model-package 或 demo/test.png",
                });
            }
        }

        return new SelfTestReport
        {
            Ok = checks.All(check => check.Ok),
            GeneratedAt = DateTimeOffset.Now.ToString("o"),
            AppDirectory = AppContext.BaseDirectory,
            RepositoryRoot = root,
            Python = python,
            Os = Environment.OSVersion.ToString(),
            Checks = checks,
        };
    }

    public static int Run(string outputPath)
    {
        var report = RunChecks();
        var target = Path.GetFullPath(outputPath);
        target = target.Length == 0 ? Path.Combine(AppContext.BaseDirectory, "self-test.json") : target;
        var directory = Path.GetDirectoryName(target);
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory);
        }

        File.WriteAllText(
            target,
            JsonSerializer.Serialize(report, JsonOptions) + Environment.NewLine,
            new System.Text.UTF8Encoding(false));
        return report.Ok ? 0 : 1;
    }

    private static SelfTestCheck RunProcess(
        string name,
        string python,
        string workingDirectory,
        IReadOnlyList<string> arguments,
        bool requireResult = false)
    {
        var startInfo = new ProcessStartInfo
        {
            FileName = python,
            WorkingDirectory = workingDirectory,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
            StandardOutputEncoding = new System.Text.UTF8Encoding(false),
            StandardErrorEncoding = new System.Text.UTF8Encoding(false),
        };
        startInfo.Environment["PYTHONPATH"] = workingDirectory;
        foreach (var argument in arguments)
        {
            startInfo.ArgumentList.Add(argument);
        }

        try
        {
            using var process = Process.Start(startInfo);
            if (process is null)
            {
                return new SelfTestCheck { Name = name, Ok = false, Detail = "无法启动进程" };
            }

            var stdout = process.StandardOutput.ReadToEnd();
            var stderr = process.StandardError.ReadToEnd();
            if (!process.WaitForExit(120_000))
            {
                process.Kill(entireProcessTree: true);
                return new SelfTestCheck { Name = name, Ok = false, Detail = "超时（120 秒）" };
            }

            var ok = process.ExitCode == 0;
            if (ok && requireResult)
            {
                ok = stdout.Contains("\"message_type\":\"result\"", StringComparison.Ordinal)
                     || stdout.Contains("\"message_type\": \"result\"", StringComparison.Ordinal);
            }

            var detail = ok
                ? "成功"
                : (stderr.Trim().Length > 0 ? stderr.Trim() : stdout.Trim());
            if (detail.Length > 600)
            {
                detail = detail[^600..];
            }

            return new SelfTestCheck { Name = name, Ok = ok, Detail = detail };
        }
        catch (Exception error)
        {
            return new SelfTestCheck { Name = name, Ok = false, Detail = error.Message };
        }
    }
}
