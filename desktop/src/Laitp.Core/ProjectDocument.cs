using System.IO;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Laitp.Core;

/// <summary>项目文件无法读取或校验。</summary>
public sealed class ProjectDocumentException : Exception
{
    public ProjectDocumentException(string message) : base(message) { }
}

public sealed record ProjectModelReference
{
    [JsonPropertyName("artifact_id")] public string ArtifactId { get; init; } = string.Empty;
    [JsonPropertyName("kind")] public string Kind { get; init; } = string.Empty;
    [JsonPropertyName("path")] public string Path { get; init; } = string.Empty;
    [JsonPropertyName("sha256")] public string Sha256 { get; init; } = string.Empty;
    [JsonPropertyName("created_at")] public string CreatedAt { get; init; } = string.Empty;
}

/// <summary>
/// 项目文件（project.json）的只读模型。完整校验（Schema、文件摘要）由 Python
/// 后端与项目命令负责；界面只做打开项目所需的基本结构检查。
/// </summary>
public sealed record ProjectDocument
{
    [JsonPropertyName("project_format")] public string ProjectFormat { get; init; } = string.Empty;
    [JsonPropertyName("project_id")] public string ProjectId { get; init; } = string.Empty;
    [JsonPropertyName("name")] public string Name { get; init; } = string.Empty;
    [JsonPropertyName("task")] public string Task { get; init; } = string.Empty;
    [JsonPropertyName("created_at")] public string CreatedAt { get; init; } = string.Empty;
    [JsonPropertyName("updated_at")] public string UpdatedAt { get; init; } = string.Empty;
    [JsonPropertyName("classes")] public List<string> Classes { get; init; } = new();
    [JsonPropertyName("dataset_manifest")] public string? DatasetManifest { get; init; }
    [JsonPropertyName("models")] public List<ProjectModelReference> Models { get; init; } = new();
    [JsonPropertyName("current_model_artifact_id")] public string? CurrentModelArtifactId { get; init; }

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = false,
    };

    public static ProjectDocument Load(string path)
    {
        string json;
        try
        {
            json = File.ReadAllText(path, Encoding.UTF8);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            throw new ProjectDocumentException($"无法读取项目文件：{error.Message}");
        }

        return Parse(json);
    }

    public static ProjectDocument Parse(string json)
    {
        ProjectDocument? document;
        try
        {
            document = JsonSerializer.Deserialize<ProjectDocument>(json, JsonOptions);
        }
        catch (JsonException error)
        {
            throw new ProjectDocumentException($"项目文件不是有效 JSON：{error.Message}");
        }

        if (document is null)
        {
            throw new ProjectDocumentException("项目文件为空");
        }

        document.Validate();
        return document;
    }

    public void Validate()
    {
        var parts = ProjectFormat.Split('.');
        if (parts.Length != 2 || parts[0] != "1" || parts[1] != "0")
        {
            throw new ProjectDocumentException($"不支持的项目格式 {ProjectFormat}");
        }

        if (string.IsNullOrWhiteSpace(ProjectId) || string.IsNullOrWhiteSpace(Name))
        {
            throw new ProjectDocumentException("项目缺少 ID 或名称");
        }

        if (Classes.Count < 2)
        {
            throw new ProjectDocumentException("项目至少需要 2 个类别");
        }

        if (Classes.Distinct(StringComparer.Ordinal).Count() != Classes.Count ||
            Classes.Any(string.IsNullOrWhiteSpace))
        {
            throw new ProjectDocumentException("项目类别为空或重复");
        }

        var ids = new HashSet<string>(StringComparer.Ordinal);
        foreach (var model in Models)
        {
            if (string.IsNullOrWhiteSpace(model.ArtifactId) || !ids.Add(model.ArtifactId))
            {
                throw new ProjectDocumentException("模型产物 ID 为空或重复");
            }

            if (model.Kind is not ("training" or "export"))
            {
                throw new ProjectDocumentException($"未知模型类型 {model.Kind}");
            }

            if (!IsRelativePortablePath(model.Path))
            {
                throw new ProjectDocumentException($"模型路径 {model.Path} 必须是可移植的相对路径");
            }
        }

        if (CurrentModelArtifactId is not null && !ids.Contains(CurrentModelArtifactId))
        {
            throw new ProjectDocumentException($"当前模型 {CurrentModelArtifactId} 不在模型列表中");
        }

        if (DatasetManifest is not null && !IsRelativePortablePath(DatasetManifest))
        {
            throw new ProjectDocumentException("数据清单路径必须是可移植的相对路径");
        }
    }

    public ProjectModelReference? CurrentModel()
    {
        return CurrentModelArtifactId is null
            ? null
            : Models.FirstOrDefault(item => item.ArtifactId == CurrentModelArtifactId);
    }

    /// <summary>当前模型清单所在目录（相对项目根目录，使用 / 分隔），用于定位模型包。</summary>
    public string? CurrentModelDirectory()
    {
        var model = CurrentModel();
        var directory = model is null ? null : System.IO.Path.GetDirectoryName(model.Path);
        return directory?.Replace('\\', '/');
    }

    private static bool IsRelativePortablePath(string path)
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
