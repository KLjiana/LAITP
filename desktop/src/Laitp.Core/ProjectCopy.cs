using System;
using System.IO;
using System.Linq;

namespace Laitp.Core;

/// <summary>项目目录复制（“另存为”用）。</summary>
public static class ProjectCopy
{
    public static void CopyDirectory(string source, string destination)
    {
        var sourceRoot = Path.GetFullPath(source);
        var destinationRoot = Path.GetFullPath(destination);
        if (!Directory.Exists(sourceRoot))
        {
            throw new DirectoryNotFoundException($"项目目录不存在：{sourceRoot}");
        }

        if (string.Equals(
                sourceRoot.TrimEnd(Path.DirectorySeparatorChar),
                destinationRoot.TrimEnd(Path.DirectorySeparatorChar),
                StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException("目标目录不能与当前项目相同");
        }

        if (Directory.Exists(destinationRoot) &&
            Directory.EnumerateFileSystemEntries(destinationRoot).Any())
        {
            throw new InvalidOperationException("目标目录已存在且非空，请换一个目录");
        }

        Directory.CreateDirectory(destinationRoot);
        foreach (var directory in Directory.EnumerateDirectories(
                     sourceRoot, "*", SearchOption.AllDirectories))
        {
            var relative = Path.GetRelativePath(sourceRoot, directory);
            Directory.CreateDirectory(Path.Combine(destinationRoot, relative));
        }

        foreach (var file in Directory.EnumerateFiles(
                     sourceRoot, "*", SearchOption.AllDirectories))
        {
            var relative = Path.GetRelativePath(sourceRoot, file);
            var target = Path.Combine(destinationRoot, relative);
            File.Copy(file, target, overwrite: false);
        }
    }
}
