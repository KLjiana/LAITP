using System;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Text;
using System.Text.Json;

namespace Laitp.Core;

/// <summary>
/// 项目单文件归档（ZIP 导出/导入），对应 Python 脚本 scripts/project_archive.py。
/// 导出要求项目目录内存在可解析的 project.json；导入要求目标目录不存在或为空，
/// 并拒绝绝对路径与包含 “..” 的归档条目（zip slip 防护）。
/// </summary>
public static class ProjectArchive
{
    private const string ProjectFileName = "project.json";

    /// <summary>
    /// 把项目目录内的全部文件以相对路径写入单个 ZIP。
    /// 目标 ZIP 已存在时采用覆盖策略：先在同一目录写入临时文件，成功后再替换旧归档，
    /// 因此导出失败不会破坏已有归档；枚举文件时跳过目标归档与临时文件自身，避免把
    /// 归档套进新归档。归档写入的是文件而非空目录，与 Python 脚本行为一致。
    /// </summary>
    /// <exception cref="DirectoryNotFoundException">项目目录不存在。</exception>
    /// <exception cref="FileNotFoundException">项目目录内缺少 project.json。</exception>
    /// <exception cref="InvalidOperationException">project.json 无法解析或归档路径非法。</exception>
    public static void Export(string projectRoot, string zipPath)
    {
        var root = Path.GetFullPath(projectRoot);
        if (!Directory.Exists(root))
        {
            throw new DirectoryNotFoundException($"项目目录不存在：{root}");
        }

        var projectFile = Path.Combine(root, ProjectFileName);
        if (!File.Exists(projectFile))
        {
            throw new FileNotFoundException($"项目文件不存在：{projectFile}", projectFile);
        }

        ValidateProjectJson(projectFile, "项目文件");

        var output = Path.GetFullPath(zipPath);
        if (Directory.Exists(output))
        {
            throw new InvalidOperationException($"归档路径必须是文件而不是目录：{output}");
        }

        if (string.Equals(output, projectFile, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException("归档路径不能是项目的 project.json");
        }

        var outputDirectory = Path.GetDirectoryName(output);
        if (string.IsNullOrWhiteSpace(outputDirectory))
        {
            throw new InvalidOperationException($"无法确定归档目录：{output}");
        }

        Directory.CreateDirectory(outputDirectory);
        var temporary = Path.Combine(
            outputDirectory, $".{Path.GetFileName(output)}.{Guid.NewGuid():N}.tmp");
        try
        {
            using (var archive = ZipFile.Open(temporary, ZipArchiveMode.Create))
            {
                foreach (var file in Directory
                             .EnumerateFiles(root, "*", SearchOption.AllDirectories)
                             .OrderBy(path => path, StringComparer.Ordinal))
                {
                    if (string.Equals(file, output, StringComparison.OrdinalIgnoreCase) ||
                        string.Equals(file, temporary, StringComparison.OrdinalIgnoreCase))
                    {
                        continue;
                    }

                    var relative = Path.GetRelativePath(root, file).Replace('\\', '/');
                    var entry = archive.CreateEntry(relative, CompressionLevel.Optimal);
                    using var source = File.OpenRead(file);
                    using var destination = entry.Open();
                    source.CopyTo(destination);
                }
            }

            File.Move(temporary, output, overwrite: true);
        }
        finally
        {
            TryDeleteFile(temporary);
        }
    }

    /// <summary>
    /// 从 ZIP 恢复项目到目标目录。目标目录必须不存在或为空；归档内全部条目会在解压前
    /// 统一校验（拒绝绝对路径、盘符与 “..” 条目），解压后校验 project.json 存在且可解析。
    /// 解压或校验失败时清理本次导入的内容并删除由本次调用创建的目标目录，不留下半成品项目。
    /// </summary>
    /// <exception cref="FileNotFoundException">归档文件不存在。</exception>
    /// <exception cref="InvalidOperationException">目标目录非空、归档路径不安全或缺少 project.json。</exception>
    public static void Import(string zipPath, string targetDirectory)
    {
        var archivePath = Path.GetFullPath(zipPath);
        if (!File.Exists(archivePath))
        {
            throw new FileNotFoundException($"归档不存在：{archivePath}", archivePath);
        }

        var targetRoot = Path.GetFullPath(targetDirectory);
        if (File.Exists(targetRoot))
        {
            throw new InvalidOperationException($"目标路径已被文件占用：{targetRoot}");
        }

        var targetExisted = Directory.Exists(targetRoot);
        if (targetExisted && Directory.EnumerateFileSystemEntries(targetRoot).Any())
        {
            throw new InvalidOperationException("目标目录已存在且非空，请换一个目录");
        }

        using var bundle = ZipFile.OpenRead(archivePath);
        var entries = bundle.Entries
            .Select(entry => (Entry: entry, Name: NormalizeEntryName(entry.FullName)))
            .Where(item => item.Name.Length > 0 && item.Name != ".")
            .ToList();

        // 先检查全部条目再解压，避免解压到一半才发现危险路径。
        foreach (var item in entries)
        {
            if (IsUnsafeEntryName(item.Name))
            {
                throw new InvalidOperationException($"归档包含不安全路径：{item.Entry.FullName}");
            }
        }

        try
        {
            Directory.CreateDirectory(targetRoot);
            foreach (var item in entries)
            {
                var destination = Path.GetFullPath(Path.Combine(
                    targetRoot, item.Name.Replace('/', Path.DirectorySeparatorChar)));
                if (!IsUnder(targetRoot, destination))
                {
                    throw new InvalidOperationException(
                        $"归档包含不安全路径：{item.Entry.FullName}");
                }

                if (item.Entry.FullName.EndsWith('/') ||
                    item.Entry.FullName.EndsWith('\\'))
                {
                    Directory.CreateDirectory(destination);
                    continue;
                }

                var directory = Path.GetDirectoryName(destination);
                if (!string.IsNullOrEmpty(directory))
                {
                    Directory.CreateDirectory(directory);
                }

                item.Entry.ExtractToFile(destination, overwrite: false);
            }

            var projectFile = Path.Combine(targetRoot, ProjectFileName);
            if (!File.Exists(projectFile))
            {
                throw new InvalidOperationException($"归档内缺少 {ProjectFileName}");
            }

            ValidateProjectJson(projectFile, "归档内的项目文件");
        }
        catch
        {
            CleanupTarget(targetRoot, targetExisted);
            throw;
        }
    }

    /// <summary>读取并解析 project.json；只做 JSON 语法校验，完整 Schema 校验由后端负责。</summary>
    private static void ValidateProjectJson(string path, string description)
    {
        string json;
        try
        {
            json = File.ReadAllText(path, Encoding.UTF8);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            throw new InvalidOperationException($"无法读取{description}：{error.Message}");
        }

        try
        {
            using var document = JsonDocument.Parse(json);
        }
        catch (JsonException error)
        {
            throw new InvalidOperationException($"{description}不是有效 JSON：{error.Message}");
        }
    }

    /// <summary>归档条目统一使用 / 分隔；空名称按无效条目处理。</summary>
    private static string NormalizeEntryName(string? name)
    {
        return string.IsNullOrWhiteSpace(name) ? string.Empty : name.Replace('\\', '/');
    }

    /// <summary>拒绝绝对路径、Windows 盘符/UNC 路径与包含 .. 的条目（zip slip 防护）。</summary>
    private static bool IsUnsafeEntryName(string name)
    {
        if (name.StartsWith("/", StringComparison.Ordinal))
        {
            return true;
        }

        // 显式检查盘符，保证在任何平台上都不会把 C:/… 或 C:… 当成相对路径。
        if (name.Length >= 2 && char.IsLetter(name[0]) && name[1] == ':')
        {
            return true;
        }

        if (Path.IsPathRooted(name))
        {
            return true;
        }

        return name.Split('/').Any(segment => segment == "..");
    }

    /// <summary>解压目标是 root（含）或其子路径，防止条目跳出目标目录。</summary>
    private static bool IsUnder(string root, string candidate)
    {
        var prefix = root.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
                     + Path.DirectorySeparatorChar;
        return string.Equals(candidate, root, StringComparison.OrdinalIgnoreCase) ||
               candidate.StartsWith(prefix, StringComparison.OrdinalIgnoreCase);
    }

    /// <summary>导入失败时清理：本次创建的目标目录整体删除，调用方提供的空目录只清空内容。</summary>
    private static void CleanupTarget(string targetRoot, bool existed)
    {
        try
        {
            if (!Directory.Exists(targetRoot))
            {
                return;
            }

            if (!existed)
            {
                Directory.Delete(targetRoot, recursive: true);
                return;
            }

            foreach (var item in Directory.EnumerateFileSystemEntries(targetRoot))
            {
                if (Directory.Exists(item))
                {
                    Directory.Delete(item, recursive: true);
                }
                else
                {
                    File.Delete(item);
                }
            }
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            // 清理失败不覆盖导入失败的原始异常。
        }
    }

    private static void TryDeleteFile(string path)
    {
        try
        {
            if (File.Exists(path))
            {
                File.Delete(path);
            }
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            // 临时文件清理失败不影响导出结果。
        }
    }
}
