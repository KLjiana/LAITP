namespace Laitp.Core;

public enum TaskState
{
    Running,
    Cancelling,
    Succeeded,
    Failed,
    Cancelled,
}

public sealed record Rejection(string Code, string Reason, string Detail);

/// <summary>
/// 任务协议状态机：只接受归属一致、序号递增的消息；终态确定后拒绝迟到消息，
/// 取消后到达的成功结果不会改写任务状态。
/// </summary>
public sealed class TaskSession
{
    private readonly object _gate = new();
    private readonly List<string> _progress = new();
    private readonly List<Rejection> _rejections = new();
    private TaskState _state = TaskState.Running;
    private long? _lastSequence;
    private int _accepted;

    public TaskSession(string requestId, string projectId, string taskId)
    {
        RequestId = requestId;
        ProjectId = projectId;
        TaskId = taskId;
    }

    public string RequestId { get; }
    public string ProjectId { get; }
    public string TaskId { get; }

    public TaskState State
    {
        get { lock (_gate) return _state; }
    }

    public long? LastSequence
    {
        get { lock (_gate) return _lastSequence; }
    }

    public int AcceptedCount
    {
        get { lock (_gate) return _accepted; }
    }

    public Envelope? ResultEnvelope { get; private set; }
    public Envelope? ErrorEnvelope { get; private set; }
    public string? CancelReason { get; private set; }

    public IReadOnlyList<string> ProgressSnapshot()
    {
        lock (_gate) return _progress.ToArray();
    }

    public IReadOnlyList<Rejection> RejectionsSnapshot()
    {
        lock (_gate) return _rejections.ToArray();
    }

    public bool Accept(Envelope envelope)
    {
        try
        {
            envelope.Validate();
        }
        catch (ProtocolException error)
        {
            return Reject("TASK_ENVELOPE_INVALID", "invalid_envelope", error.Message);
        }

        lock (_gate)
        {
            if (envelope.RequestId != RequestId || envelope.ProjectId != ProjectId ||
                envelope.TaskId != TaskId)
            {
                return RejectLocked(
                    "TASK_IDENTITY_MISMATCH",
                    "identity_mismatch",
                    $"消息归属 {envelope.ProjectId}/{envelope.RequestId}/{envelope.TaskId} 与当前任务不一致");
            }

            if (_state is TaskState.Succeeded or TaskState.Failed or TaskState.Cancelled)
            {
                return RejectLocked(
                    "TASK_LATE_MESSAGE",
                    "after_terminal",
                    $"任务已处于 {_state}，忽略 {envelope.MessageType} 消息");
            }

            if (_lastSequence is long last && envelope.Sequence <= last)
            {
                return RejectLocked(
                    "TASK_SEQUENCE_INVALID",
                    "stale_sequence",
                    $"序号 {envelope.Sequence} 未大于已接收的 {last}");
            }

            _lastSequence = envelope.Sequence;
            _accepted++;
            switch (envelope.MessageType)
            {
                case "progress":
                    _progress.Add($"{envelope.PayloadString("stage") ?? "?"} "
                        + $"{envelope.PayloadInt64("completed")}/{envelope.PayloadInt64("total")?.ToString() ?? "?"}");
                    break;
                case "result":
                    ResultEnvelope = envelope;
                    _state = TaskState.Succeeded;
                    break;
                case "error":
                    ErrorEnvelope = envelope;
                    _state = TaskState.Failed;
                    break;
                case "cancelled":
                    CancelReason = envelope.PayloadString("reason") ?? "user_cancelled";
                    _state = TaskState.Cancelled;
                    break;
            }

            return true;
        }
    }

    public void MarkCancelling()
    {
        lock (_gate)
        {
            if (_state is TaskState.Running) _state = TaskState.Cancelling;
        }
    }

    public void MarkCancelled(string reason = "user_cancelled")
    {
        lock (_gate)
        {
            if (_state is TaskState.Succeeded or TaskState.Failed or TaskState.Cancelled) return;
            CancelReason = reason;
            _state = TaskState.Cancelled;
        }
    }

    public void MarkFailed(string code, string message)
    {
        lock (_gate)
        {
            if (_state is TaskState.Succeeded or TaskState.Failed or TaskState.Cancelled) return;
            ErrorEnvelope = new Envelope
            {
                ProtocolVersion = "1.0",
                RequestId = RequestId,
                ProjectId = ProjectId,
                TaskId = TaskId,
                MessageType = "error",
                ArtifactId = null,
                Sequence = _lastSequence ?? 0,
                Payload = System.Text.Json.JsonSerializer.SerializeToElement(new
                {
                    code,
                    stage = "runtime",
                    message,
                }),
            };
            _state = TaskState.Failed;
        }
    }

    public void RejectUnparseable(string detail)
    {
        Reject("TASK_ENVELOPE_INVALID", "invalid_line", detail);
    }

    private bool Reject(string code, string reason, string detail)
    {
        lock (_gate)
        {
            return RejectLocked(code, reason, detail);
        }
    }

    private bool RejectLocked(string code, string reason, string detail)
    {
        _rejections.Add(new Rejection(code, reason, detail));
        return false;
    }
}
