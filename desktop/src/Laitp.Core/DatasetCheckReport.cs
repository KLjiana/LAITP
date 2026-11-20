using System.Text.Json;
using System.Text.Json.Serialization;

namespace Laitp.Core;

public sealed class DatasetCheckException : Exception
{
    public DatasetCheckException(string message) : base(message) { }
}

public sealed record DatasetCheckIssue
{
    [JsonPropertyName("code")] public string Code { get; init; } = string.Empty;
    [JsonPropertyName("stage")] public string Stage { get; init; } = string.Empty;
    [JsonPropertyName("message")] public string Message { get; init; } = string.Empty;
    [JsonPropertyName("location")] public string? Location { get; init; }
}

public sealed record DatasetCheckPolicy
{
    [JsonPropertyName("require_test_split")] public bool RequireTestSplit { get; init; }
    [JsonPropertyName("min_train_per_class")] public int MinTrainPerClass { get; init; }
    [JsonPropertyName("min_val_per_class")] public int MinValPerClass { get; init; }
    [JsonPropertyName("min_test_per_class")] public int MinTestPerClass { get; init; }
}

/// <summary>
/// `backend.project check-dataset` 输出的只读报告：训练前数据检查结果。
/// 完整校验（Schema、批次、文件摘要、图片解码）由 Python 侧完成。
/// </summary>
public sealed record DatasetCheckReport
{
    [JsonPropertyName("ok")] public bool Ok { get; init; }
    [JsonPropertyName("issues")] public List<DatasetCheckIssue> Issues { get; init; } = new();
    [JsonPropertyName("policy")] public DatasetCheckPolicy? Policy { get; init; }

    public static DatasetCheckReport Parse(string json)
    {
        DatasetCheckReport? report;
        try
        {
            report = JsonSerializer.Deserialize<DatasetCheckReport>(json);
        }
        catch (JsonException error)
        {
            throw new DatasetCheckException($"数据检查结果不是有效 JSON：{error.Message}");
        }

        if (report is null)
        {
            throw new DatasetCheckException("数据检查结果为空");
        }

        report.Validate();
        return report;
    }

    public void Validate()
    {
        if (Ok && Issues.Count > 0)
        {
            throw new DatasetCheckException("检查通过却包含问题项");
        }

        if (!Ok && Issues.Count == 0)
        {
            throw new DatasetCheckException("检查未通过但未给出问题");
        }

        foreach (var issue in Issues)
        {
            if (string.IsNullOrWhiteSpace(issue.Code))
            {
                throw new DatasetCheckException("问题项缺少错误码");
            }

            if (string.IsNullOrWhiteSpace(issue.Message))
            {
                throw new DatasetCheckException("问题项缺少说明");
            }
        }

        if (Policy is not null &&
            (Policy.MinTrainPerClass < 0 || Policy.MinValPerClass < 0 ||
             Policy.MinTestPerClass < 0))
        {
            throw new DatasetCheckException("检查策略的样本下限不能为负");
        }
    }

    public string Describe()
    {
        return Ok
            ? "数据检查通过"
            : "数据检查未通过：" + string.Join(
                "；", Issues.Take(5).Select(issue => $"{issue.Code} {issue.Message}"));
    }
}
