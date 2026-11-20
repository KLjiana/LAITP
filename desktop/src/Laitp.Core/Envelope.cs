using System.Text.Json;
using System.Text.Json.Serialization;

namespace Laitp.Core;

/// <summary>解析或校验消息失败。</summary>
public sealed class ProtocolException : Exception
{
    public ProtocolException(string message) : base(message) { }
}

/// <summary>
/// 协议 1.0 的消息信封，字段与 schemas/message-envelope.schema.json 对应。
/// C# 侧做归属、类型和结果自洽的浅层校验；完整 Schema 校验仍由 Python 工作进程负责。
/// </summary>
public sealed record Envelope
{
    [JsonPropertyName("protocol_version")] public string ProtocolVersion { get; init; } = string.Empty;
    [JsonPropertyName("request_id")] public string RequestId { get; init; } = string.Empty;
    [JsonPropertyName("project_id")] public string ProjectId { get; init; } = string.Empty;
    [JsonPropertyName("task_id")] public string TaskId { get; init; } = string.Empty;
    [JsonPropertyName("message_type")] public string MessageType { get; init; } = string.Empty;
    [JsonPropertyName("sequence")] public long Sequence { get; init; }
    [JsonPropertyName("artifact_id")] public string? ArtifactId { get; init; }
    [JsonPropertyName("payload")] public JsonElement Payload { get; init; }

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = false,
    };

    private static readonly HashSet<string> KnownTypes = new()
    {
        "progress", "result", "error", "cancelled",
    };

    public static Envelope Parse(string line)
    {
        Envelope? envelope;
        try
        {
            envelope = JsonSerializer.Deserialize<Envelope>(line, JsonOptions);
        }
        catch (JsonException error)
        {
            throw new ProtocolException($"消息不是有效 JSON：{error.Message}");
        }

        if (envelope is null)
        {
            throw new ProtocolException("消息为空");
        }

        envelope.Validate();
        return envelope;
    }

    public void Validate()
    {
        if (string.IsNullOrWhiteSpace(ProtocolVersion))
        {
            throw new ProtocolException("缺少协议版本");
        }

        if (string.IsNullOrWhiteSpace(RequestId) || string.IsNullOrWhiteSpace(ProjectId) ||
            string.IsNullOrWhiteSpace(TaskId))
        {
            throw new ProtocolException("缺少请求、项目或任务 ID");
        }

        if (!KnownTypes.Contains(MessageType))
        {
            throw new ProtocolException($"未知消息类型 {MessageType}");
        }

        if (Sequence < 0)
        {
            throw new ProtocolException("序号不能为负");
        }

        if (Payload.ValueKind != JsonValueKind.Object)
        {
            throw new ProtocolException("payload 必须是对象");
        }

        if (MessageType == "result")
        {
            if (string.IsNullOrWhiteSpace(ArtifactId))
            {
                throw new ProtocolException("result 消息必须携带 artifact_id");
            }

            if (Payload.TryGetProperty("artifact", out var artifact) &&
                artifact.ValueKind == JsonValueKind.Object &&
                artifact.TryGetProperty("artifact_id", out var artifactId) &&
                artifactId.GetString() != ArtifactId)
            {
                throw new ProtocolException("信封 artifact_id 与结果引用的产物 ID 不一致");
            }
        }
    }

    public string? PayloadString(string name)
    {
        return Payload.ValueKind == JsonValueKind.Object &&
               Payload.TryGetProperty(name, out var value) &&
               value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;
    }

    public long? PayloadInt64(string name)
    {
        return Payload.ValueKind == JsonValueKind.Object &&
               Payload.TryGetProperty(name, out var value) &&
               value.ValueKind == JsonValueKind.Number &&
               value.TryGetInt64(out var number)
            ? number
            : null;
    }

    public string? PayloadArtifactId()
    {
        return Payload.ValueKind == JsonValueKind.Object &&
               Payload.TryGetProperty("artifact", out var artifact) &&
               artifact.ValueKind == JsonValueKind.Object
            ? artifact.TryGetProperty("artifact_id", out var id) ? id.GetString() : null
            : null;
    }
}
