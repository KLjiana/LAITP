using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;

namespace Laitp.Core;

/// <summary>最近打开的项目列表（本地持久化，供桌面外壳使用）。</summary>
public static class RecentProjects
{
    public const int DefaultMax = 5;

    private static readonly JsonSerializerOptions Options = new()
    {
        WriteIndented = true,
    };

    public static List<string> Load(string path)
    {
        try
        {
            if (!File.Exists(path))
            {
                return new List<string>();
            }

            var text = File.ReadAllText(path);
            var items = JsonSerializer.Deserialize<List<string>>(text, Options);
            return items?
                .Where(item => !string.IsNullOrWhiteSpace(item))
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToList() ?? new List<string>();
        }
        catch (Exception)
        {
            // 最近项目只是便利功能，读取失败时返回空列表。
            return new List<string>();
        }
    }

    public static void Save(string path, IEnumerable<string> items)
    {
        var directory = Path.GetDirectoryName(path);
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory);
        }

        var list = items
            .Where(item => !string.IsNullOrWhiteSpace(item))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
        File.WriteAllText(path, JsonSerializer.Serialize(list, Options));
    }

    public static List<string> Add(
        IEnumerable<string> items, string path, int max = DefaultMax)
    {
        var normalized = path.Trim();
        var result = new List<string> { normalized };
        result.AddRange(items.Where(item =>
            !string.Equals(item, normalized, StringComparison.OrdinalIgnoreCase)));
        return result.Take(Math.Max(1, max)).ToList();
    }
}
