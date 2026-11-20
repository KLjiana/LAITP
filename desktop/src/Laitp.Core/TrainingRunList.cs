using System.Text.Json;
using System.Text.Json.Serialization;

namespace Laitp.Core;

public sealed class TrainingRunListException : Exception
{
    public TrainingRunListException(string message) : base(message) { }
}

public sealed record TrainingRunEntry
{
    [JsonPropertyName("run_id")] public string RunId { get; init; } = string.Empty;
    [JsonPropertyName("training_artifact_id")] public string TrainingArtifactId { get; init; } = string.Empty;
    [JsonPropertyName("created_at")] public string? CreatedAt { get; init; }
    [JsonPropertyName("accuracy")] public double? Accuracy { get; init; }
    [JsonPropertyName("classes")] public List<string> Classes { get; init; } = new();
    [JsonPropertyName("registered")] public bool Registered { get; init; }

    [JsonIgnore]
    public string DisplayName =>
        $"{RunId}｜{(Accuracy is null ? "无准确率" : Accuracy.Value.ToString("P1"))}"
        + $"｜{(Registered ? "已登记" : "未登记")}";
}

/// <summary>
/// `backend.project runs` 输出的只读模型：项目训练运行历史。
/// </summary>
public sealed record TrainingRunList
{
    [JsonPropertyName("runs")] public List<TrainingRunEntry> Runs { get; init; } = new();
    [JsonPropertyName("total")] public int Total { get; init; }
    [JsonPropertyName("current_model_artifact_id")] public string? CurrentModelArtifactId { get; init; }

    public static TrainingRunList Parse(string json)
    {
        TrainingRunList? list;
        try
        {
            list = JsonSerializer.Deserialize<TrainingRunList>(json);
        }
        catch (JsonException error)
        {
            throw new TrainingRunListException($"训练历史不是有效 JSON：{error.Message}");
        }

        if (list is null)
        {
            throw new TrainingRunListException("训练历史为空");
        }

        list.Validate();
        return list;
    }

    public void Validate()
    {
        if (Total != Runs.Count)
        {
            throw new TrainingRunListException($"total {Total} 与运行数 {Runs.Count} 不一致");
        }

        var runIds = new HashSet<string>(StringComparer.Ordinal);
        foreach (var run in Runs)
        {
            if (string.IsNullOrWhiteSpace(run.RunId) || !runIds.Add(run.RunId))
            {
                throw new TrainingRunListException("运行 ID 为空或重复");
            }

            if (string.IsNullOrWhiteSpace(run.TrainingArtifactId))
            {
                throw new TrainingRunListException("运行缺少训练产物 ID");
            }

            if (run.Accuracy is < 0 or > 1)
            {
                throw new TrainingRunListException("运行准确率必须在 0 到 1 之间");
            }
        }
    }
}
