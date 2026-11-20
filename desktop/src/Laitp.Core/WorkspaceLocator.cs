namespace Laitp.Core;

/// <summary>
/// 定位仓库根目录与 Python 解释器。
/// 界面不依赖安装路径：优先使用环境变量 LAITP_PYTHON 与 LAITP_HOME，
/// 否则从程序目录向上查找包含 backend/runtime 的目录。
/// </summary>
public static class WorkspaceLocator
{
    public static string? FindRepositoryRoot(string startDirectory)
    {
        var fromEnvironment = Environment.GetEnvironmentVariable("LAITP_HOME");
        if (!string.IsNullOrWhiteSpace(fromEnvironment) &&
            Directory.Exists(Path.Combine(fromEnvironment, "backend", "runtime")))
        {
            return Path.GetFullPath(fromEnvironment);
        }

        var directory = new DirectoryInfo(Path.GetFullPath(startDirectory));
        while (directory is not null)
        {
            if (Directory.Exists(Path.Combine(directory.FullName, "backend", "runtime")))
            {
                return directory.FullName;
            }

            directory = directory.Parent;
        }

        return null;
    }

    public static string? FindPython(string repositoryRoot)
    {
        var fromEnvironment = Environment.GetEnvironmentVariable("LAITP_PYTHON");
        if (!string.IsNullOrWhiteSpace(fromEnvironment) && File.Exists(fromEnvironment))
        {
            return fromEnvironment;
        }

        var candidate = Path.Combine(repositoryRoot, ".venv", "Scripts", "python.exe");
        return File.Exists(candidate) ? candidate : null;
    }
}
