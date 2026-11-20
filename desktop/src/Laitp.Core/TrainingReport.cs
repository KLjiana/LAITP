using System.IO;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Laitp.Core;

/// <summary>训练报告缺失或结构非法。</summary>
public sealed class TrainingReportException : Exception
{
    public TrainingReportException(string message) : base(message) { }
}

public sealed record TrainingSampleResult
{
    [JsonPropertyName("path")] public string Path { get; init; } = string.Empty;
    [JsonPropertyName("true_class_id")] public int TrueClassId { get; init; }
    [JsonPropertyName("predicted_class_id")] public int PredictedClassId { get; init; }
}

/// <summary>
/// 训练运行 metrics.json 的只读模型。完整摘要与文件完整性校验由 Python
/// `backend.classification report` 负责；界面只做显示所需的结构检查。
/// </summary>
public sealed record TrainingReport
{
    [JsonPropertyName("run_id")] public string RunId { get; init; } = string.Empty;
    [JsonPropertyName("artifact_id")] public string ArtifactId { get; init; } = string.Empty;
    [JsonPropertyName("classes")] public List<string> Classes { get; init; } = new();
    [JsonPropertyName("accuracy")] public double Accuracy { get; init; }
    [JsonPropertyName("loss")] public double Loss { get; init; }
    [JsonPropertyName("confusion_matrix")] public List<List<int>> ConfusionMatrix { get; init; } = new();
    [JsonPropertyName("per_class_recall")] public List<double?> PerClassRecall { get; init; } = new();
    [JsonPropertyName("best_epoch")] public int BestEpoch { get; init; }
    [JsonPropertyName("epochs")] public int Epochs { get; init; }
    [JsonPropertyName("validation_samples")] public int ValidationSamples { get; init; }
    [JsonPropertyName("samples")] public List<TrainingSampleResult> Samples { get; init; } = new();

    public static TrainingReport Load(string metricsPath)
    {
        string json;
        try
        {
            json = File.ReadAllText(metricsPath, Encoding.UTF8);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            throw new TrainingReportException($"无法读取训练报告：{error.Message}");
        }

        return Parse(json);
    }

    public static TrainingReport Parse(string json)
    {
        TrainingReport? report;
        try
        {
            report = JsonSerializer.Deserialize<TrainingReport>(json);
        }
        catch (JsonException error)
        {
            throw new TrainingReportException($"训练报告不是有效 JSON：{error.Message}");
        }

        if (report is null)
        {
            throw new TrainingReportException("训练报告为空");
        }

        report.Validate();
        return report;
    }

    public IEnumerable<TrainingSampleResult> Misclassified()
    {
        return Samples.Where(item => item.TrueClassId != item.PredictedClassId);
    }

    public void Validate()
    {
        if (Classes.Count < 2)
        {
            throw new TrainingReportException("训练报告至少需要 2 个类别");
        }

        if (Accuracy is < 0 or > 1)
        {
            throw new TrainingReportException("准确率必须在 0 到 1 之间");
        }

        if (ConfusionMatrix.Count != Classes.Count ||
            ConfusionMatrix.Any(row => row.Count != Classes.Count))
        {
            throw new TrainingReportException("混淆矩阵维度与类别数不一致");
        }

        if (PerClassRecall.Count != Classes.Count)
        {
            throw new TrainingReportException("每类召回数量与类别数不一致");
        }

        foreach (var sample in Samples)
        {
            if (sample.TrueClassId < 0 || sample.TrueClassId >= Classes.Count ||
                sample.PredictedClassId < 0 || sample.PredictedClassId >= Classes.Count)
            {
                throw new TrainingReportException("样本类别 ID 越界");
            }
        }
    }
}
