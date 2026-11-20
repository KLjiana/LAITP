using System.IO;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Laitp.Core;

public sealed class DatasetSummaryException : Exception
{
    public DatasetSummaryException(string message) : base(message) { }
}

public sealed record DatasetSampleEntry
{
    [JsonPropertyName("path")] public string Path { get; init; } = string.Empty;
    [JsonPropertyName("class_id")] public int ClassId { get; init; }
    [JsonPropertyName("split")] public string Split { get; init; } = string.Empty;
}

/// <summary>
/// 数据集清单（dataset-manifest.json）的只读摘要。完整 Schema 与图片/批次校验
/// 由 Python `backend.classification.dataset` 负责；界面只统计与显示。
/// </summary>
public sealed record DatasetSummary
{
    [JsonPropertyName("dataset_version")] public string DatasetVersion { get; init; } = string.Empty;
    [JsonPropertyName("dataset_id")] public string DatasetId { get; init; } = string.Empty;
    [JsonPropertyName("classes")] public List<string> Classes { get; init; } = new();
    [JsonPropertyName("samples")] public List<DatasetSampleEntry> Samples { get; init; } = new();

    private static readonly string[] KnownSplits = { "train", "val", "test" };

    public static DatasetSummary Load(string path)
    {
        string json;
        try
        {
            json = File.ReadAllText(path, Encoding.UTF8);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            throw new DatasetSummaryException($"无法读取数据清单：{error.Message}");
        }

        return Parse(json);
    }

    public static DatasetSummary Parse(string json)
    {
        DatasetSummary? summary;
        try
        {
            summary = JsonSerializer.Deserialize<DatasetSummary>(json);
        }
        catch (JsonException error)
        {
            throw new DatasetSummaryException($"数据清单不是有效 JSON：{error.Message}");
        }

        if (summary is null)
        {
            throw new DatasetSummaryException("数据清单为空");
        }

        summary.Validate();
        return summary;
    }

    public int Count(string className, string split)
    {
        var classId = Classes.IndexOf(className);
        if (classId < 0)
        {
            return 0;
        }

        return Samples.Count(sample => sample.ClassId == classId && sample.Split == split);
    }

    public int TotalFor(string split)
    {
        return Samples.Count(sample => sample.Split == split);
    }

    public string Describe()
    {
        var builder = new StringBuilder();
        foreach (var className in Classes)
        {
            builder.AppendLine(
                $"{className}：训练 {Count(className, "train")} / "
                + $"验证 {Count(className, "val")} / 测试 {Count(className, "test")}");
        }

        builder.Append(
            $"合计 {Samples.Count} 张（训练 {TotalFor("train")} / "
            + $"验证 {TotalFor("val")} / 测试 {TotalFor("test")}）");
        return builder.ToString();
    }

    public void Validate()
    {
        if (Classes.Count < 2)
        {
            throw new DatasetSummaryException("数据清单至少需要 2 个类别");
        }

        if (Classes.Distinct(StringComparer.Ordinal).Count() != Classes.Count)
        {
            throw new DatasetSummaryException("数据清单类别重复");
        }

        foreach (var sample in Samples)
        {
            if (sample.ClassId < 0 || sample.ClassId >= Classes.Count)
            {
                throw new DatasetSummaryException("样本类别 ID 越界");
            }

            if (!KnownSplits.Contains(sample.Split))
            {
                throw new DatasetSummaryException($"未知划分 {sample.Split}");
            }

            if (string.IsNullOrWhiteSpace(sample.Path))
            {
                throw new DatasetSummaryException("样本路径为空");
            }
        }
    }
}
