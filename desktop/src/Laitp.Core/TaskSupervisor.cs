using System.Diagnostics;
using System.Text;

namespace Laitp.Core;

public sealed record TaskOutcome(
    TaskState State,
    Envelope? Result,
    Envelope? Error,
    IReadOnlyList<string> Progress,
    IReadOnlyList<Rejection> Rejections,
    int? ExitCode,
    string StderrTail)
{
    public bool Ok => State == TaskState.Succeeded;
    public string? ErrorCode => Error?.PayloadString("code");
    public string? ArtifactId => Result?.PayloadArtifactId() ?? Result?.ArtifactId;
}

/// <summary>
/// 最小父进程：启动 Python 工作进程，按行读取协议消息，维护任务状态并支持取消。
/// 语义与 backend/runtime/supervisor.py 一致，供 WPF 界面直接使用。
/// </summary>
public sealed class TaskSupervisor : IDisposable
{
    private const int StderrTailChars = 4000;

    private readonly Process _process;
    private readonly TimeSpan _cancelTimeout;
    private readonly StringBuilder _stderr = new();
    private readonly object _stderrGate = new();
    private Thread? _stdoutThread;
    private Thread? _stderrThread;
    private volatile bool _started;
    private volatile bool _cancelRequested;
    private bool _disposed;

    public TaskSupervisor(
        string executable,
        IEnumerable<string> arguments,
        string workingDirectory,
        string requestId,
        string projectId,
        string taskId,
        TimeSpan? cancelTimeout = null)
    {
        Session = new TaskSession(requestId, projectId, taskId);
        _cancelTimeout = cancelTimeout ?? TimeSpan.FromSeconds(5);

        var startInfo = new ProcessStartInfo
        {
            FileName = executable,
            WorkingDirectory = workingDirectory,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
            StandardOutputEncoding = new UTF8Encoding(false),
            StandardErrorEncoding = new UTF8Encoding(false),
        };
        foreach (var argument in arguments)
        {
            startInfo.ArgumentList.Add(argument);
        }

        _process = new Process { StartInfo = startInfo };
    }

    public TaskSession Session { get; }

    public event Action<Envelope>? MessageReceived;

    public int? ExitCode => _process.HasExited ? _process.ExitCode : null;

    public void Start()
    {
        if (_started)
        {
            throw new InvalidOperationException("任务已经启动");
        }

        if (!_process.Start())
        {
            throw new InvalidOperationException("无法启动后端进程");
        }

        _started = true;
        _stdoutThread = new Thread(ReadStdout) { IsBackground = true, Name = "laitp-stdout" };
        _stderrThread = new Thread(ReadStderr) { IsBackground = true, Name = "laitp-stderr" };
        _stdoutThread.Start();
        _stderrThread.Start();
    }

    public bool Cancel(string reason = "user_cancelled")
    {
        if (!_started)
        {
            throw new InvalidOperationException("任务尚未启动");
        }

        if (Session.State is TaskState.Succeeded or TaskState.Failed or TaskState.Cancelled)
        {
            return false;
        }

        _cancelRequested = true;
        Session.MarkCancelling();
        try
        {
            if (!_process.HasExited)
            {
                _process.Kill(entireProcessTree: true);
            }
        }
        catch (InvalidOperationException) { }
        catch (System.ComponentModel.Win32Exception) { }

        try
        {
            _process.WaitForExit((int)_cancelTimeout.TotalMilliseconds);
        }
        catch (InvalidOperationException) { }

        Session.MarkCancelled(reason);
        return true;
    }

    public TaskOutcome WaitForExit(TimeSpan timeout)
    {
        if (!_started)
        {
            throw new InvalidOperationException("任务尚未启动");
        }

        if (!_process.WaitForExit((int)timeout.TotalMilliseconds))
        {
            throw new TimeoutException($"任务在 {timeout.TotalSeconds:0.#} 秒内未结束");
        }

        _stdoutThread?.Join(TimeSpan.FromSeconds(5));
        _stderrThread?.Join(TimeSpan.FromSeconds(5));
        FinalizeOutcome();
        return BuildOutcome();
    }

    private void ReadStdout()
    {
        try
        {
            while (_process.StandardOutput.ReadLine() is { } line)
            {
                if (string.IsNullOrWhiteSpace(line))
                {
                    continue;
                }

                Envelope envelope;
                try
                {
                    envelope = Envelope.Parse(line);
                }
                catch (ProtocolException error)
                {
                    Session.RejectUnparseable(error.Message);
                    continue;
                }

                if (!Session.Accept(envelope))
                {
                    continue;
                }

                try
                {
                    MessageReceived?.Invoke(envelope);
                }
                catch (Exception)
                {
                    // 界面回调异常不能中断消息读取。
                }
            }
        }
        catch (InvalidOperationException)
        {
            // 进程被取消时流已关闭。
        }
    }

    private void ReadStderr()
    {
        try
        {
            while (_process.StandardError.ReadLine() is { } line)
            {
                lock (_stderrGate)
                {
                    _stderr.AppendLine(line);
                }
            }
        }
        catch (InvalidOperationException)
        {
        }
    }

    private void FinalizeOutcome()
    {
        if (Session.State is not (TaskState.Running or TaskState.Cancelling))
        {
            return;
        }

        if (_cancelRequested)
        {
            Session.MarkCancelled();
            return;
        }

        Session.MarkFailed(
            "TASK_CHILD_EXITED",
            $"子进程退出码 {ExitCode?.ToString() ?? "?"} 且未发送终态消息");
    }

    private TaskOutcome BuildOutcome()
    {
        string tail;
        lock (_stderrGate)
        {
            var text = _stderr.ToString();
            tail = text.Length <= StderrTailChars ? text : text[^StderrTailChars..];
        }

        return new TaskOutcome(
            Session.State,
            Session.ResultEnvelope,
            Session.ErrorEnvelope,
            Session.ProgressSnapshot(),
            Session.RejectionsSnapshot(),
            ExitCode,
            tail);
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        try
        {
            if (!_process.HasExited)
            {
                _process.Kill(entireProcessTree: true);
            }
        }
        catch (InvalidOperationException) { }
        catch (System.ComponentModel.Win32Exception) { }

        _process.Dispose();
    }
}
