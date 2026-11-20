using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Laitp.Core;

public sealed class SampleListException : Exception
{
    public SampleListException(string message) : base(message) { }
}

public sealed record ProjectSampleEntry
{
    [JsonPropertyName("path")] public string Path { get; init; } = string.Empty;
    [JsonPropertyName("class_name")] public string ClassName { get; init; } = string.Empty;
    [JsonPropertyName("class_id")] public int ClassId { get; init; }
    [JsonPropertyName("split")] public string Split { get; init; } = string.Empty;
    [JsonPropertyName("capture_batch")] public string CaptureBatch { get; init; } = string.Empty;

    [JsonIgnore]
    public string DisplayName =>
        $"{ClassName}｜{Split}｜{CaptureBatch}｜{System.IO.Path.GetFileName(Path)}";
}

/// <summary>
/// `backend.project samples` 输出的只读模型：项目图片样本列表。
/// 路径按 data/ 相对路径保存，界面负责拼接绝对路径预览。
/// </summary>
public sealed record SampleList
{
    [JsonPropertyName("classes")] public List<string> Classes { get; init; } = new();
    [JsonPropertyName("samples")] public List<ProjectSampleEntry> Samples { get; init; } = new();
    [JsonPropertyName("total")] public int Total { get; init; }

    public static SampleList Parse(string json)
    {
        SampleList? list;
        try
        {
            list = JsonSerializer.Deserialize<SampleList>(json);
        }
        catch (JsonException error)
        {
            throw new SampleListException($"样本列表不是有效 JSON：{error.Message}");
        }

        if (list is null)
        {
            throw new SampleListException("样本列表为空");
        }

        list.Validate();
        return list;
    }

    public void Validate()
    {
        if (Classes.Count < 2)
        {
            throw new SampleListException("样本列表至少需要 2 个类别");
        }

        if (Total != Samples.Count)
        {
            throw new SampleListException($"total {Total} 与样本数 {Samples.Count} 不一致");
        }

        foreach (var sample in Samples)
        {
            if (sample.ClassId < 0 || sample.ClassId >= Classes.Count)
            {
                throw new SampleListException("样本类别 ID 越界");
            }

            if (sample.ClassName != Classes[sample.ClassId])
            {
                throw new SampleListException("样本类别名与类别表不一致");
            }

            if (sample.Split is not ("train" or "test"))
            {
                throw new SampleListException($"未知存储划分 {sample.Split}");
            }

            if (!IsSafeRelativePath(sample.Path))
            {
                throw new SampleListException($"样本路径非法：{sample.Path}");
            }

            var expectedPrefix = sample.Split == "test" ? "test-images/" : "images/";
            if (!sample.Path.StartsWith(expectedPrefix, StringComparison.Ordinal))
            {
                throw new SampleListException(
                    $"样本路径 {sample.Path} 与存储划分 {sample.Split} 不一致");
            }
        }
    }

    private static bool IsSafeRelativePath(string path)
    {
        if (string.IsNullOrWhiteSpace(path) || System.IO.Path.IsPathRooted(path))
        {
            return false;
        }

        if (path.Contains('\\') || path.Contains(':'))
        {
            return false;
        }

        return path.Split('/').All(segment =>
            segment.Length > 0 && segment is not ("." or ".."));
    }
}
