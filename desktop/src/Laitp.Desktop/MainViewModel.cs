using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Windows;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Laitp.Core;

namespace Laitp.Desktop;

/// <summary>
/// M1 最小界面：打开项目、训练（调用工作进程并登记训练产物）、
/// 单图预测与取消。采集与训练结果可视化尚未实现。
/// </summary>
public sealed class MainViewModel : INotifyPropertyChanged
{
    private readonly string? _repositoryRoot;
    private readonly string? _pythonPath;
    private TaskSupervisor? _supervisor;
    private bool _running;
    private string _projectPath = string.Empty;
    private string _projectSummary = "未打开项目";
    private string _classesText = string.Empty;
    private string _newProjectRoot = string.Empty;
    private string _newProjectName = string.Empty;
    private string _newProjectClasses = "水杯 书本 笔袋";
    private string _datasetManifestPath = string.Empty;
    private string _epochsText = "30";
    private string _packagePath = string.Empty;
    private string _imagePath = string.Empty;
    private string _batchImagesPath = string.Empty;
    private string _comparePackagePath = string.Empty;
    private string? _selectedComparePackage;
    private string? _selectedBatchHistory;
    // 批量预测历史显示文本 → 结果 JSON 路径；列表刷新时同步重建。
    private readonly Dictionary<string, string> _batchHistoryPaths = new();
    private string? _selectedCompareHistory;
    // 模型对比历史显示文本 → 结果 JSON 路径；列表刷新时同步重建。
    private readonly Dictionary<string, string> _compareHistoryPaths = new();
    private string _status = string.Empty;
    private string _artifact = string.Empty;
    private string _trainingSummary = "尚未加载训练结果";
    private string _datasetSummaryText = "尚未加载数据清单";
    private string _importClass = string.Empty;
    private string _importSourcePath = string.Empty;
    private string _importBatch = string.Empty;
    private string _importTreeSource = string.Empty;
    private bool _importAsTest;
    private string _editProjectName = string.Empty;
    private string _newClassName = string.Empty;
    private string _removeClassName = string.Empty;
    private bool _removeClassWithData;
    private string _renameClassOld = string.Empty;
    private string _renameClassNew = string.Empty;
    private string _sampleNewName = string.Empty;
    private bool _strictAcceptance;
    private string _minTrainText = "30";
    private string _minValText = "8";
    private string _minTestText = "10";
    private TrainingRunEntry? _selectedTrainingRun;
    private string _dataCheckStatus = "尚未检查";
    private bool _lastDataCheckOk;
    private string? _sampleRoot;
    private ProjectSampleEntry? _selectedSample;
    private ImageSource? _selectedSampleImage;
    private ImageSource? _previewImage;
    private bool _isPreviewing;
    private int _previewFrames;
    private CancellationTokenSource? _previewCancellation;
    private CameraCapture.PreviewSession? _previewSession;
    private DateTime _previewStartedAt;
    private DateTime _previewLastStatusAt;
    private string? _selectedCameraDevice;
    private readonly Dictionary<string, string> _cameraDeviceIds = new();
    private string _cameraBurstCount = "5";

    public MainViewModel()
    {
        _repositoryRoot = WorkspaceLocator.FindRepositoryRoot(AppContext.BaseDirectory);
        _pythonPath = _repositoryRoot is null ? null : WorkspaceLocator.FindPython(_repositoryRoot);
        ComparePackageOptions = new ObservableCollection<string>();

        PredictCommand = new RelayCommand(async _ => await RunPredictAsync(), _ => !_running);
        BatchPredictCommand = new RelayCommand(async _ => await RunBatchPredictAsync(), _ => !_running);
        CompareCommand = new RelayCommand(async _ => await RunCompareAsync(), _ => !_running);
        TrainCommand = new RelayCommand(async _ => await RunTrainingAsync(), _ => !_running);
        ImportCommand = new RelayCommand(async _ => await RunImportAsync(), _ => !_running);
        ImportTreeCommand = new RelayCommand(async _ => await RunImportTreeAsync(), _ => !_running);
        CameraCommand = new RelayCommand(async _ => await RunCameraCaptureAsync(), _ => !_running);
        CameraBurstCommand = new RelayCommand(async _ => await RunBurstCaptureAsync(), _ => !_running);
        CameraCheckCommand = new RelayCommand(async _ => await RunCameraCheckAsync(), _ => !_running);
        PreviewStartCommand = new RelayCommand(_ => StartPreview(), _ => !IsPreviewing);
        PreviewStopCommand = new RelayCommand(async _ => await StopPreviewAsync(), _ => IsPreviewing);
        CreateProjectCommand = new RelayCommand(async _ => await RunCreateProjectAsync(), _ => !_running);
        DeleteSampleCommand = new RelayCommand(async _ => await RunDeleteSampleAsync(), _ => !_running);
        RenameProjectCommand = new RelayCommand(async _ => await RunRenameProjectAsync(), _ => !_running);
        AddClassCommand = new RelayCommand(async _ => await RunAddClassAsync(), _ => !_running);
        RemoveClassCommand = new RelayCommand(async _ => await RunRemoveClassAsync(), _ => !_running);
        CheckDatasetCommand = new RelayCommand(async _ => await RunCheckDatasetAsync(StrictAcceptance), _ => !_running);
        DatasetReportCommand = new RelayCommand(async _ => await RunDatasetReportAsync(), _ => !_running);
        VerifyProjectCommand = new RelayCommand(async _ => await RunVerifyProjectAsync(), _ => !_running);
        OpenDatasetReportCommand = new RelayCommand(_ => OpenDatasetReport(), _ => !_running);
        SelfTestCommand = new RelayCommand(async _ => await RunSelfTestAsync(), _ => !_running);
        RenameClassCommand = new RelayCommand(async _ => await RunRenameClassAsync(), _ => !_running);
        RenameSampleCommand = new RelayCommand(async _ => await RunRenameSampleAsync(), _ => !_running);
        ExportTrainingRunCommand = new RelayCommand(async _ => await RunExportRunAsync(), _ => !_running);
        OpenRunsFolderCommand = new RelayCommand(_ => OpenRunsFolder(), _ => !_running);
        CancelCommand = new RelayCommand(_ => Cancel(), _ => _running);
        OpenProjectCommand = new RelayCommand(_ => OpenProject(), _ => !_running);
        OpenRecentCommand = new RelayCommand(_ => OpenRecentProject(), _ => !_running);
        SaveAsCommand = new RelayCommand(async _ => await RunSaveAsAsync(), _ => !_running);
        ExportArchiveCommand = new RelayCommand(async _ => await RunExportArchiveAsync(), _ => !_running);
        ImportArchiveCommand = new RelayCommand(async _ => await RunImportArchiveAsync(), _ => !_running);
        ViewBatchHistoryCommand = new RelayCommand(
            _ => ViewBatchHistoryDetail(),
            _ => !string.IsNullOrWhiteSpace(SelectedBatchHistory));
        ExportBatchHistoryCommand = new RelayCommand(
            async _ => await RunExportBatchHistoryAsync(),
            _ => !_running);
        ViewCompareHistoryCommand = new RelayCommand(
            _ => ViewCompareHistoryDetail(),
            _ => !string.IsNullOrWhiteSpace(SelectedCompareHistory));

        Status = _repositoryRoot is null
            ? "未找到仓库目录：请设置 LAITP_HOME"
            : _pythonPath is null
                ? "未找到 Python 解释器：请设置 LAITP_PYTHON 或创建 .venv"
                : "就绪";
        LoadRecentProjects();
        StartAutoSelfTest();
        _ = RefreshCameraDevicesAsync(showStatus: false);
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    public string RepositoryRoot => _repositoryRoot ?? "（未找到）";
    public string PythonPath => _pythonPath ?? "（未找到）";

    public string ProjectPath
    {
        get => _projectPath;
        set => SetField(ref _projectPath, value);
    }

    public string ProjectSummary
    {
        get => _projectSummary;
        private set => SetField(ref _projectSummary, value);
    }

    public string ClassesText
    {
        get => _classesText;
        private set => SetField(ref _classesText, value);
    }

    public string NewProjectRoot
    {
        get => _newProjectRoot;
        set => SetField(ref _newProjectRoot, value);
    }

    public string NewProjectName
    {
        get => _newProjectName;
        set => SetField(ref _newProjectName, value);
    }

    public string NewProjectClasses
    {
        get => _newProjectClasses;
        set => SetField(ref _newProjectClasses, value);
    }

    public string DatasetManifestPath
    {
        get => _datasetManifestPath;
        set => SetField(ref _datasetManifestPath, value);
    }

    public string EpochsText
    {
        get => _epochsText;
        set => SetField(ref _epochsText, value);
    }

    public string PackagePath
    {
        get => _packagePath;
        set => SetField(ref _packagePath, value);
    }

    public string ImagePath
    {
        get => _imagePath;
        set => SetField(ref _imagePath, value);
    }

    public string BatchImagesPath
    {
        get => _batchImagesPath;
        set => SetField(ref _batchImagesPath, value);
    }

    public string ComparePackagePath
    {
        get => _comparePackagePath;
        set => SetField(ref _comparePackagePath, value);
    }

    /// <summary>
    /// “模型对比”下拉框候选：项目 exports/&lt;产物 ID&gt;/model-package 的绝对路径，
    /// 新产物在前；未打开项目或项目没有可用模型包时为空。
    /// </summary>
    public ObservableCollection<string> ComparePackageOptions { get; }

    public string? SelectedComparePackage
    {
        get => _selectedComparePackage;
        set
        {
            SetField(ref _selectedComparePackage, value);
            // 下拉选择即同步对比模型包路径；清空选择时一并清空，避免残留上一个项目的路径。
            ComparePackagePath = value ?? string.Empty;
        }
    }

    public string Status
    {
        get => _status;
        private set => SetField(ref _status, value);
    }

    public string Artifact
    {
        get => _artifact;
        private set => SetField(ref _artifact, value);
    }

    public string TrainingSummary
    {
        get => _trainingSummary;
        private set => SetField(ref _trainingSummary, value);
    }

    public ObservableCollection<string> MisclassifiedSamples { get; } = new();

    public string DatasetSummaryText
    {
        get => _datasetSummaryText;
        private set => SetField(ref _datasetSummaryText, value);
    }

    public string ImportClass
    {
        get => _importClass;
        set => SetField(ref _importClass, value);
    }

    public string ImportSourcePath
    {
        get => _importSourcePath;
        set => SetField(ref _importSourcePath, value);
    }

    public string ImportBatch
    {
        get => _importBatch;
        set => SetField(ref _importBatch, value);
    }

    public string ImportTreeSource
    {
        get => _importTreeSource;
        set => SetField(ref _importTreeSource, value);
    }

    public bool ImportAsTest
    {
        get => _importAsTest;
        set => SetField(ref _importAsTest, value);
    }

    public string EditProjectName
    {
        get => _editProjectName;
        set => SetField(ref _editProjectName, value);
    }

    public string NewClassName
    {
        get => _newClassName;
        set => SetField(ref _newClassName, value);
    }

    public string RemoveClassName
    {
        get => _removeClassName;
        set => SetField(ref _removeClassName, value);
    }

    public bool RemoveClassWithData
    {
        get => _removeClassWithData;
        set => SetField(ref _removeClassWithData, value);
    }

    public string DataCheckStatus
    {
        get => _dataCheckStatus;
        private set => SetField(ref _dataCheckStatus, value);
    }

    public ObservableCollection<string> DataCheckIssues { get; } = new();

    public string RenameClassOld
    {
        get => _renameClassOld;
        set => SetField(ref _renameClassOld, value);
    }

    public string RenameClassNew
    {
        get => _renameClassNew;
        set => SetField(ref _renameClassNew, value);
    }

    public string SampleNewName
    {
        get => _sampleNewName;
        set => SetField(ref _sampleNewName, value);
    }

    public bool StrictAcceptance
    {
        get => _strictAcceptance;
        set => SetField(ref _strictAcceptance, value);
    }

    public string MinTrainText
    {
        get => _minTrainText;
        set => SetField(ref _minTrainText, value);
    }

    public string MinValText
    {
        get => _minValText;
        set => SetField(ref _minValText, value);
    }

    public string MinTestText
    {
        get => _minTestText;
        set => SetField(ref _minTestText, value);
    }

    public ObservableCollection<TrainingRunEntry> TrainingRuns { get; } = new();

    public TrainingRunEntry? SelectedTrainingRun
    {
        get => _selectedTrainingRun;
        set => SetField(ref _selectedTrainingRun, value);
    }

    /// <summary>
    /// 批量预测历史（最近 10 次），每项形如
    /// “2026-11-19 00:53 · 30 张 · 准确率 86.7%”。
    /// </summary>
    public ObservableCollection<string> BatchPredictionHistory { get; } = new();

    /// <summary>
    /// 选中的批量预测历史项（列表显示文本）；对应 runs/batch-predict-*.json，
    /// 通过 <see cref="_batchHistoryPaths"/> 反查文件路径。
    /// </summary>
    public string? SelectedBatchHistory
    {
        get => _selectedBatchHistory;
        set
        {
            SetField(ref _selectedBatchHistory, value);
            // RelayCommand 依赖 CommandManager.RequerySuggested；选择变化后主动触发重查询，
            // 使“查看选中历史”按钮的可用状态立即刷新。
            CommandManager.InvalidateRequerySuggested();
        }
    }

    /// <summary>
    /// 模型对比历史（最近 10 次），每项形如
    /// “2026-11-19 05:41 · A 76.7% / B 90.0% · 一致率 76.7%”。
    /// </summary>
    public ObservableCollection<string> CompareHistory { get; } = new();

    /// <summary>
    /// 选中的模型对比历史项（列表显示文本）；对应 runs/compare-*.json，
    /// 通过 <see cref="_compareHistoryPaths"/> 反查文件路径。
    /// </summary>
    public string? SelectedCompareHistory
    {
        get => _selectedCompareHistory;
        set
        {
            SetField(ref _selectedCompareHistory, value);
            // RelayCommand 依赖 CommandManager.RequerySuggested；选择变化后主动触发重查询，
            // 使“查看对比历史”按钮的可用状态立即刷新。
            CommandManager.InvalidateRequerySuggested();
        }
    }

    public ObservableCollection<ProjectSampleEntry> SampleEntries { get; } = new();

    public ProjectSampleEntry? SelectedSample
    {
        get => _selectedSample;
        set
        {
            if (EqualityComparer<ProjectSampleEntry?>.Default.Equals(_selectedSample, value))
            {
                return;
            }

            _selectedSample = value;
            OnPropertyChanged(nameof(SelectedSample));
            LoadSamplePreview();
        }
    }

    public ImageSource? SelectedSampleImage
    {
        get => _selectedSampleImage;
        private set => SetField(ref _selectedSampleImage, value);
    }

    public ImageSource? PreviewImage
    {
        get => _previewImage;
        private set => SetField(ref _previewImage, value);
    }

    public ObservableCollection<string> CameraDevices { get; } = new();

    public ObservableCollection<string> RecentProjectList { get; } = new();

    private string? _selectedRecentProject;

    public string? SelectedRecentProject
    {
        get => _selectedRecentProject;
        set => SetField(ref _selectedRecentProject, value);
    }

    private readonly string _recentProjectsPath = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "Laitp", "recent-projects.json");

    private string _saveAsPath = string.Empty;

    public string SaveAsPath
    {
        get => _saveAsPath;
        set => SetField(ref _saveAsPath, value);
    }

    private string _archivePath = string.Empty;

    public string ArchivePath
    {
        get => _archivePath;
        set => SetField(ref _archivePath, value);
    }

    public string? SelectedCameraDevice
    {
        get => _selectedCameraDevice;
        set => SetField(ref _selectedCameraDevice, value);
    }

    public string CameraBurstCount
    {
        get => _cameraBurstCount;
        set => SetField(ref _cameraBurstCount, value);
    }

    private string? CurrentCameraDeviceId =>
        SelectedCameraDevice is not null &&
        _cameraDeviceIds.TryGetValue(SelectedCameraDevice, out var id)
            ? id
            : null;

    public bool IsPreviewing
    {
        get => _isPreviewing;
        private set
        {
            if (_isPreviewing == value)
            {
                return;
            }

            SetField(ref _isPreviewing, value);
            System.Windows.Input.CommandManager.InvalidateRequerySuggested();
        }
    }

    public ObservableCollection<string> Messages { get; } = new();

    public ICommand PredictCommand { get; }
    public ICommand BatchPredictCommand { get; }
    public ICommand CompareCommand { get; }
    public ICommand TrainCommand { get; }
    public ICommand ImportCommand { get; }
    public ICommand ImportTreeCommand { get; }
    public ICommand CameraCommand { get; }
    public ICommand CameraBurstCommand { get; }
    public ICommand CameraCheckCommand { get; }
    public ICommand PreviewStartCommand { get; }
    public ICommand PreviewStopCommand { get; }
    public ICommand CreateProjectCommand { get; }
    public ICommand DeleteSampleCommand { get; }
    public ICommand RenameProjectCommand { get; }
    public ICommand AddClassCommand { get; }
    public ICommand RemoveClassCommand { get; }
    public ICommand CheckDatasetCommand { get; }
    public ICommand DatasetReportCommand { get; }
    public ICommand VerifyProjectCommand { get; }
    public ICommand OpenDatasetReportCommand { get; }
    public ICommand SelfTestCommand { get; }
    public ICommand RenameClassCommand { get; }
    public ICommand RenameSampleCommand { get; }
    public ICommand ExportTrainingRunCommand { get; }
    public ICommand OpenRunsFolderCommand { get; }
    public ICommand CancelCommand { get; }
    public ICommand OpenProjectCommand { get; }
    public ICommand OpenRecentCommand { get; }
    public ICommand SaveAsCommand { get; }
    public ICommand ExportArchiveCommand { get; }
    public ICommand ImportArchiveCommand { get; }
    public ICommand ViewBatchHistoryCommand { get; }
    public ICommand ExportBatchHistoryCommand { get; }
    public ICommand ViewCompareHistoryCommand { get; }

    private void LoadRecentProjects()
    {
        RecentProjectList.Clear();
        foreach (var item in RecentProjects.Load(_recentProjectsPath))
        {
            RecentProjectList.Add(item);
        }

        SelectedRecentProject = RecentProjectList.FirstOrDefault();
    }

    private void RememberRecentProject(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return;
        }

        var fullPath = Path.GetFullPath(path);
        var updated = RecentProjects.Add(RecentProjectList.ToList(), fullPath);
        RecentProjectList.Clear();
        foreach (var item in updated)
        {
            RecentProjectList.Add(item);
        }

        SelectedRecentProject = RecentProjectList.FirstOrDefault();
        try
        {
            RecentProjects.Save(_recentProjectsPath, updated);
        }
        catch (Exception)
        {
            // 最近项目只是便利功能，持久化失败不影响打开项目。
        }
    }

    private void OpenRecentProject()
    {
        if (string.IsNullOrWhiteSpace(SelectedRecentProject) ||
            !File.Exists(SelectedRecentProject))
        {
            Status = "最近项目不存在，请重新填写并打开 project.json";
            return;
        }

        ProjectPath = SelectedRecentProject;
        OpenProject();
        if (Status.StartsWith("已打开项目", StringComparison.Ordinal))
        {
            Status = "已打开最近项目：" + Status;
        }
    }

    private async Task RunSaveAsAsync()
    {
        if (string.IsNullOrWhiteSpace(ProjectPath) || !File.Exists(ProjectPath))
        {
            Status = "请先打开项目";
            return;
        }

        if (string.IsNullOrWhiteSpace(SaveAsPath))
        {
            Status = "请填写另存为的目标目录";
            return;
        }

        var sourceRoot = Path.GetDirectoryName(Path.GetFullPath(ProjectPath));
        if (string.IsNullOrWhiteSpace(sourceRoot))
        {
            Status = "无法确定项目目录";
            return;
        }

        var target = Path.GetFullPath(SaveAsPath.Trim());
        Status = "另存为中…";
        SetRunning(true);
        try
        {
            await Task.Run(() => ProjectCopy.CopyDirectory(sourceRoot, target));
            ProjectPath = Path.Combine(target, "project.json");
            OpenProject();
            Status = "已另存为：" + target;
        }
        catch (Exception error)
        {
            Status = "另存为失败：" + error.Message;
        }
        finally
        {
            SetRunning(false);
        }
    }

    private async Task RunExportArchiveAsync()
    {
        if (string.IsNullOrWhiteSpace(ProjectPath) || !File.Exists(ProjectPath))
        {
            Status = "请先打开项目";
            return;
        }

        if (string.IsNullOrWhiteSpace(ArchivePath))
        {
            Status = "请填写归档 ZIP 路径";
            return;
        }

        var projectRoot = Path.GetDirectoryName(Path.GetFullPath(ProjectPath));
        if (string.IsNullOrWhiteSpace(projectRoot))
        {
            Status = "无法确定项目目录";
            return;
        }

        Status = "导出存档中…";
        SetRunning(true);
        try
        {
            var archivePath = Path.GetFullPath(ArchivePath.Trim());
            await Task.Run(() => ProjectArchive.Export(projectRoot, archivePath));
            Messages.Add("已导出存档：" + archivePath);
            Status = "已导出存档：" + archivePath;
        }
        catch (Exception error)
        {
            Status = "导出存档失败：" + error.Message;
        }
        finally
        {
            SetRunning(false);
        }
    }

    private async Task RunImportArchiveAsync()
    {
        if (string.IsNullOrWhiteSpace(ArchivePath))
        {
            Status = "请填写归档 ZIP 路径";
            return;
        }

        Status = "导入存档中…";
        SetRunning(true);
        try
        {
            var archivePath = Path.GetFullPath(ArchivePath.Trim());
            if (!File.Exists(archivePath))
            {
                Status = "归档不存在：" + archivePath;
                return;
            }

            var archiveDirectory = Path.GetDirectoryName(archivePath);
            if (string.IsNullOrWhiteSpace(archiveDirectory))
            {
                Status = "无法确定归档目录";
                return;
            }

            // 约定恢复到与归档同名的目录（去掉 .zip 扩展名），已存在时提示换目录。
            var target = Path.Combine(
                archiveDirectory, Path.GetFileNameWithoutExtension(archivePath));
            if (Directory.Exists(target))
            {
                Status = "导入目标目录已存在，请换一个归档目录或先移走：" + target;
                return;
            }

            await Task.Run(() => ProjectArchive.Import(archivePath, target));

            // 解压只保证 project.json 是合法 JSON；Schema、数据清单与模型产物的一致性
            // 由后端 verify 校验。校验不通过时不切换当前项目，保留解压目录便于排查。
            (bool Ok, string Summary, IReadOnlyList<string> Issues) verification;
            try
            {
                verification = await Task.Run(() => VerifyImportedProject(target));
            }
            catch (Exception error)
            {
                Messages.Add("导入的存档校验失败：" + error.Message);
                Messages.Add("未切换当前项目；已保留解压目录便于排查：" + target);
                Status = "导入的存档校验失败：" + error.Message;
                return;
            }

            if (!verification.Ok)
            {
                Messages.Add("导入的存档校验失败：" + verification.Summary);
                foreach (var issue in verification.Issues.Take(10))
                {
                    Messages.Add("校验问题：" + issue);
                }

                if (verification.Issues.Count > 10)
                {
                    Messages.Add($"……其余 {verification.Issues.Count - 10} 个问题未列出");
                }

                Messages.Add("未切换当前项目；已保留解压目录便于排查：" + target);
                Status = "导入的存档校验失败：" + verification.Summary;
                return;
            }

            var projectFile = Path.Combine(target, "project.json");
            ProjectPath = projectFile;
            OpenProject();
            if (Status.StartsWith("已打开项目", StringComparison.Ordinal))
            {
                Messages.Add("已从存档导入并打开项目：" + projectFile);
                Status = "已从存档导入并打开项目";
            }
        }
        catch (Exception error)
        {
            Status = "导入存档失败：" + error.Message;
        }
        finally
        {
            SetRunning(false);
        }
    }

    /// <summary>
    /// 调用 <c>python -m backend.project verify --root &lt;项目目录&gt;</c> 校验刚解压的
    /// 项目：项目文件 Schema、数据清单类别一致性、模型文件存在性与 SHA-256 摘要。
    /// 命令只读，不会修改项目。退出码 0 表示通过；失败时解析 stdout 中的
    /// <c>issues</c> 数组，输出不是 JSON（如模块启动失败）时退回进程输出摘要。
    /// </summary>
    private (bool Ok, string Summary, IReadOnlyList<string> Issues) VerifyImportedProject(
        string projectRoot)
    {
        var arguments = new List<string>
        {
            "-m", "backend.project", "verify", "--root", projectRoot,
        };
        var (exitCode, stdout, stderr) = RunPythonCommand(arguments);
        if (exitCode == 0)
        {
            return (true, string.Empty, Array.Empty<string>());
        }

        if (exitCode < 0)
        {
            return (
                false,
                "无法启动后端校验命令：" +
                    (string.IsNullOrWhiteSpace(stderr) ? $"退出码 {exitCode}" : stderr.Trim()),
                Array.Empty<string>());
        }

        var issues = new List<string>();
        try
        {
            using var document = JsonDocument.Parse(stdout);
            issues.AddRange(ReadVerifyProjectIssues(document));
        }
        catch (JsonException)
        {
            // 非 JSON 输出时使用进程输出摘要，见下。
        }

        var summary = issues.Count > 0
            ? $"发现 {issues.Count} 个问题：" + string.Join("；", issues.Take(3))
            : SummarizeVerifyFailure(exitCode, stderr, stdout);
        return (false, Shorten(summary, 200), issues);
    }

    /// <summary>读取校验问题 JSON 对象中的字符串字段；字段缺失或类型不符时返回空串。</summary>
    private static string ReadJsonString(JsonElement element, string name)
    {
        return element.ValueKind == JsonValueKind.Object &&
               element.TryGetProperty(name, out var value) &&
               value.ValueKind == JsonValueKind.String
            ? value.GetString() ?? string.Empty
            : string.Empty;
    }

    /// <summary>校验命令异常退出但没有 JSON 报告时的摘要：优先取 stderr 末行（异常信息）。</summary>
    private static string SummarizeVerifyFailure(int exitCode, string stderr, string stdout)
    {
        var stderrLines = stderr
            .Split('\n')
            .Select(line => line.Trim())
            .Where(line => line.Length > 0)
            .ToList();
        if (stderrLines.Count > 0)
        {
            return stderrLines[^1];
        }

        var stdoutLine = stdout
            .Split('\n')
            .Select(line => line.Trim())
            .FirstOrDefault(line => line.Length > 0);
        return stdoutLine ?? $"退出码 {exitCode}";
    }

    /// <summary>状态栏/消息区显示用的长度限制。</summary>
    private static string Shorten(string text, int maxLength)
    {
        return text.Length <= maxLength ? text : text[..maxLength] + "…";
    }

    private void OpenProject()
    {
        try
        {
            var document = ProjectDocument.Load(ProjectPath);
            var projectRoot = Path.GetDirectoryName(Path.GetFullPath(ProjectPath)) ?? string.Empty;
            RefreshProjectSummary(document);
            LoadTrainingReportForProject(projectRoot, document);
            LoadDatasetSummary(projectRoot, document);
            LoadSampleList(projectRoot);
            InvalidateDataCheck();
            LoadTrainingRuns(projectRoot);
            LoadBatchPredictionHistory();
            LoadCompareHistory();
            EditProjectName = document.Name;
            if (string.IsNullOrWhiteSpace(ImportClass) && document.Classes.Count > 0)
            {
                ImportClass = document.Classes[0];
            }
            Messages.Clear();
            Artifact = string.Empty;

            if (document.DatasetManifest is not null)
            {
                DatasetManifestPath = Path.GetFullPath(
                    Path.Combine(projectRoot, document.DatasetManifest));
            }

            var current = document.CurrentModel();
            if (current is null)
            {
                RememberRecentProject(ProjectPath);
                RefreshComparePackageOptions();
                Status = "已打开项目，尚未设置当前模型";
                return;
            }

            var manifestPath = Path.GetFullPath(Path.Combine(projectRoot, current.Path));
            PackagePath = Path.GetDirectoryName(manifestPath) ?? string.Empty;
            Artifact = current.ArtifactId;
            RememberRecentProject(ProjectPath);
            RefreshComparePackageOptions();
            Status = "已打开项目，当前模型：" + current.ArtifactId;
        }
        catch (ProjectDocumentException error)
        {
            Status = "打开项目失败：" + error.Message;
        }
        catch (IOException error)
        {
            Status = "打开项目失败：" + error.Message;
        }
    }

    private void OpenRunsFolder()
    {
        if (string.IsNullOrWhiteSpace(ProjectPath) || !File.Exists(ProjectPath))
        {
            Status = "请先打开项目文件（project.json）";
            return;
        }

        try
        {
            var projectRoot =
                Path.GetDirectoryName(Path.GetFullPath(ProjectPath)) ?? string.Empty;
            var runsDir = Path.Combine(projectRoot, "runs");
            if (!Directory.Exists(runsDir))
            {
                Directory.CreateDirectory(runsDir);
            }

            Process.Start(new ProcessStartInfo
            {
                FileName = "explorer.exe",
                Arguments = "\"" + runsDir + "\"",
                UseShellExecute = true,
            });
            Status = "已打开结果目录：" + runsDir;
        }
        catch (Exception error)
        {
            Status = "打开结果目录失败：" + error.Message;
        }
    }

    private void RefreshProjectSummary(ProjectDocument document)
    {
        ProjectSummary = $"{document.Name}（{document.Classes.Count} 类，{document.Models.Count} 个模型）";
        ClassesText = string.Join(" / ", document.Classes);
    }

    private void LoadDatasetSummary(string projectRoot, ProjectDocument document)
    {
        if (document.DatasetManifest is null)
        {
            DatasetSummaryText = "尚未生成数据清单";
            return;
        }

        var path = Path.GetFullPath(Path.Combine(projectRoot, document.DatasetManifest));
        if (!File.Exists(path))
        {
            DatasetSummaryText = "数据清单不存在：" + document.DatasetManifest;
            return;
        }

        try
        {
            DatasetSummaryText = DatasetSummary.Load(path).Describe();
        }
        catch (DatasetSummaryException error)
        {
            DatasetSummaryText = "读取数据清单失败：" + error.Message;
        }
    }

    private async Task RunImportAsync()
    {
        if (_repositoryRoot is null || _pythonPath is null)
        {
            Status = "环境不完整，无法导入";
            return;
        }

        if (string.IsNullOrWhiteSpace(ProjectPath) || !File.Exists(ProjectPath))
        {
            Status = "请先打开项目文件（project.json）";
            return;
        }

        if (string.IsNullOrWhiteSpace(ImportClass))
        {
            Status = "请填写导入类别";
            return;
        }

        if (string.IsNullOrWhiteSpace(ImportSourcePath) || !Directory.Exists(ImportSourcePath))
        {
            Status = "请填写存在的图片来源目录";
            return;
        }

        var projectRoot = Path.GetDirectoryName(Path.GetFullPath(ProjectPath)) ?? string.Empty;
        var arguments = new List<string>
        {
            "-m", "backend.project", "import",
            "--root", projectRoot,
            "--class", ImportClass.Trim(),
            "--source", ImportSourcePath,
        };
        if (!string.IsNullOrWhiteSpace(ImportBatch))
        {
            arguments.Add("--batch");
            arguments.Add(ImportBatch.Trim());
        }

        if (ImportAsTest)
        {
            arguments.Add("--split");
            arguments.Add("test");
        }

        Status = "导入中…";
        SetRunning(true);
        try
        {
            var (exitCode, stdout, stderr) =
                await Task.Run(() => RunPythonCommand(arguments));
            if (exitCode != 0)
            {
                Status = "导入失败：" + (stderr.Trim().Length > 0 ? stderr.Trim() : stdout.Trim());
                return;
            }

            var document = ProjectDocument.Load(ProjectPath);
            RefreshProjectSummary(document);
            if (document.DatasetManifest is not null)
            {
                DatasetManifestPath = Path.GetFullPath(
                    Path.Combine(projectRoot, document.DatasetManifest));
            }

            LoadDatasetSummary(projectRoot, document);
            LoadSampleList(projectRoot);
            InvalidateDataCheck();
            LoadTrainingRuns(projectRoot);
            Status = DescribeImport(stdout);
        }
        catch (Exception error)
        {
            Status = "导入失败：" + error.Message;
        }
        finally
        {
            SetRunning(false);
        }
    }

    private async Task RefreshCameraDevicesAsync(bool showStatus)
    {
        try
        {
            var devices = await Task.Run(() => CameraCapture.ListDevicesAsync());
            RunOnUi(() =>
            {
                CameraDevices.Clear();
                _cameraDeviceIds.Clear();
                foreach (var device in devices)
                {
                    CameraDevices.Add(device.Name);
                    _cameraDeviceIds[device.Name] = device.Id;
                }

                if (CameraDevices.Count > 0 &&
                    (SelectedCameraDevice is null ||
                     !CameraDevices.Contains(SelectedCameraDevice)))
                {
                    SelectedCameraDevice = CameraDevices[0];
                }

                if (showStatus)
                {
                    Status = devices.Count == 0
                        ? "未找到可用摄像头（设备可能被禁用或未连接）：请在设备管理器中启用，或检查 Windows 相机隐私设置"
                        : $"摄像头：{string.Join("、", devices.Select(item => item.Name))}" +
                          $"（{devices.Count} 个可用）";
                }
            });
        }
        catch (Exception error)
        {
            if (showStatus)
            {
                RunOnUi(() => Status = "检测摄像头失败：" + CameraErrors.Describe(error));
            }
        }
    }

    private async Task RunCameraCheckAsync()
    {
        Status = "检测摄像头中…";
        await RefreshCameraDevicesAsync(showStatus: true);
    }

    private void StartPreview()
    {
        if (IsPreviewing)
        {
            return;
        }

        _previewFrames = 0;
        _previewStartedAt = DateTime.UtcNow;
        _previewLastStatusAt = DateTime.MinValue;
        IsPreviewing = true;
        Status = "预览启动中…";
        _ = StartHighFrameRatePreviewAsync();
    }

    private async Task StartHighFrameRatePreviewAsync()
    {
        try
        {
            var startTask = CameraCapture.PreviewSession.StartAsync(
                OnJpegFrame, CurrentCameraDeviceId);
            var completed = await Task.WhenAny(startTask, Task.Delay(4000));
            if (completed != startTask)
            {
                RunOnUi(() => Status = "高帧率预览启动超时，使用单帧预览");
                StartPeriodicPreview();
                return;
            }

            var session = await startTask;
            if (!IsPreviewing)
            {
                await session.DisposeAsync();
                return;
            }

            _previewSession = session;
        }
        catch (Exception error)
        {
            RunOnUi(() =>
                Status = "高帧率预览不可用（" + error.Message + "），使用单帧预览");
            StartPeriodicPreview();
        }
    }

    private void OnJpegFrame(byte[] jpeg)
    {
        var bitmap = LoadFrozenBitmap(jpeg);
        if (bitmap is null)
        {
            return;
        }

        _previewFrames++;
        runOnUiAction(bitmap);
        return;

        void runOnUiAction(System.Windows.Media.Imaging.BitmapImage frame)
        {
            RunOnUi(() =>
            {
                if (!IsPreviewing)
                {
                    return;
                }

                PreviewImage = frame;
                var now = DateTime.UtcNow;
                if ((now - _previewLastStatusAt).TotalMilliseconds < 500)
                {
                    return;
                }

                _previewLastStatusAt = now;
                var seconds = Math.Max(0.001, (now - _previewStartedAt).TotalSeconds);
                var fps = _previewFrames / seconds;
                Status = $"预览中（{fps:0.0} fps，{_previewFrames} 帧）";
            });
        }
    }

    private void StartPeriodicPreview()
    {
        _previewCancellation = new CancellationTokenSource();
        var token = _previewCancellation.Token;
        var directory = Path.Combine(
            Path.GetTempPath(), "laitp-preview", Guid.NewGuid().ToString("N"));
        _ = Task.Run(async () =>
        {
            try
            {
                while (!token.IsCancellationRequested)
                {
                    var capture = await CameraCapture.CaptureAsync(
                        directory, CurrentCameraDeviceId);
                    if (token.IsCancellationRequested)
                    {
                        File.Delete(capture.Path);
                        break;
                    }

                    var bitmap = LoadFrozenBitmap(capture.Path);
                    File.Delete(capture.Path);
                    _previewFrames++;
                    var frames = _previewFrames;
                    var device = capture.DeviceName;
                    RunOnUi(() =>
                    {
                        if (!IsPreviewing)
                        {
                            return;
                        }

                        PreviewImage = bitmap;
                        Status = $"预览中（{frames} 帧，{device}）";
                    });
                    await Task.Delay(400, token);
                }
            }
            catch (OperationCanceledException)
            {
                // 正常停止。
            }
            catch (Exception error)
            {
                RunOnUi(() =>
                {
                    IsPreviewing = false;
                    Status = "预览失败：" + error.Message;
                });
            }
        }, token);
    }

    private async Task StopPreviewAsync()
    {
        IsPreviewing = false;
        _previewCancellation?.Cancel();
        _previewCancellation?.Dispose();
        _previewCancellation = null;
        if (_previewSession is not null)
        {
            await _previewSession.DisposeAsync();
            _previewSession = null;
        }

        var seconds = Math.Max(0.001, (DateTime.UtcNow - _previewStartedAt).TotalSeconds);
        var fps = _previewFrames / seconds;
        Status = $"预览已停止（{_previewFrames} 帧，平均 {fps:0.0} fps）";
    }

    private void RunOnUi(Action action)
    {
        var dispatcher = Application.Current?.Dispatcher;
        if (dispatcher is null || dispatcher.CheckAccess())
        {
            action();
        }
        else
        {
            dispatcher.Invoke(action);
        }
    }

    private static BitmapImage? LoadFrozenBitmap(byte[] jpeg)
    {
        try
        {
            using var stream = new MemoryStream(jpeg);
            var bitmap = new BitmapImage();
            bitmap.BeginInit();
            bitmap.CacheOption = BitmapCacheOption.OnLoad;
            bitmap.StreamSource = stream;
            bitmap.EndInit();
            bitmap.Freeze();
            return bitmap;
        }
        catch (Exception)
        {
            return null;
        }
    }

    private static BitmapImage? LoadFrozenBitmap(string path)
    {
        try
        {
            var bitmap = new BitmapImage();
            bitmap.BeginInit();
            bitmap.CacheOption = BitmapCacheOption.OnLoad;
            bitmap.UriSource = new Uri(path, UriKind.Absolute);
            bitmap.EndInit();
            bitmap.Freeze();
            return bitmap;
        }
        catch (Exception)
        {
            return null;
        }
    }

    private async Task RunBurstCaptureAsync()
    {
        if (_repositoryRoot is null || _pythonPath is null)
        {
            Status = "环境不完整，无法连拍";
            return;
        }

        if (string.IsNullOrWhiteSpace(ProjectPath) || !File.Exists(ProjectPath))
        {
            Status = "请先打开项目文件（project.json）";
            return;
        }

        if (string.IsNullOrWhiteSpace(ImportClass))
        {
            Status = "请填写连拍要导入的类别";
            return;
        }

        if (!int.TryParse(CameraBurstCount.Trim(), out var count) ||
            count < 1 || count > 20)
        {
            Status = "连拍张数必须是 1–20 的整数";
            return;
        }

        var projectRoot = Path.GetDirectoryName(Path.GetFullPath(ProjectPath)) ?? string.Empty;
        var temporary = Path.Combine(
            Path.GetTempPath(), "laitp-camera-burst", Guid.NewGuid().ToString("N"));
        Status = "连拍中…";
        SetRunning(true);
        try
        {
            for (var index = 1; index <= count; index++)
            {
                Status = $"连拍 {index}/{count}…";
                await Task.Run(
                    () => CameraCapture.CaptureAsync(temporary, CurrentCameraDeviceId));
            }

            var arguments = new List<string>
            {
                "-m", "backend.project", "import",
                "--root", projectRoot,
                "--class", ImportClass.Trim(),
                "--source", temporary,
                "--batch", $"camera-burst-{DateTime.Now:yyyyMMdd-HHmmss}",
            };
            if (ImportAsTest)
            {
                arguments.Add("--split");
                arguments.Add("test");
            }

            var (exitCode, stdout, stderr) =
                await Task.Run(() => RunPythonCommand(arguments));
            if (exitCode != 0)
            {
                Status = "连拍完成，但导入失败：" +
                         (stderr.Trim().Length > 0 ? stderr.Trim() : stdout.Trim());
                return;
            }

            var document = ProjectDocument.Load(ProjectPath);
            RefreshProjectSummary(document);
            if (document.DatasetManifest is not null)
            {
                DatasetManifestPath = Path.GetFullPath(
                    Path.Combine(projectRoot, document.DatasetManifest));
            }

            LoadDatasetSummary(projectRoot, document);
            LoadSampleList(projectRoot);
            InvalidateDataCheck();
            LoadTrainingRuns(projectRoot);
            Status = $"连拍完成：拍摄 {count} 张，{DescribeImport(stdout)}";
        }
        catch (Exception error)
        {
            Status = "连拍失败：" + error.Message;
        }
        finally
        {
            try
            {
                if (Directory.Exists(temporary))
                {
                    Directory.Delete(temporary, recursive: true);
                }
            }
            catch (IOException)
            {
                // 临时目录清理失败不影响主流程。
            }

            SetRunning(false);
        }
    }

    private async Task RunCameraCaptureAsync()
    {
        if (_repositoryRoot is null || _pythonPath is null)
        {
            Status = "环境不完整，无法拍照";
            return;
        }

        if (string.IsNullOrWhiteSpace(ProjectPath) || !File.Exists(ProjectPath))
        {
            Status = "请先打开项目文件（project.json）";
            return;
        }

        if (string.IsNullOrWhiteSpace(ImportClass))
        {
            Status = "请填写拍照要导入的类别";
            return;
        }

        var projectRoot = Path.GetDirectoryName(Path.GetFullPath(ProjectPath)) ?? string.Empty;
        var temporary = Path.Combine(
            Path.GetTempPath(), "laitp-camera", Guid.NewGuid().ToString("N"));
        Status = "拍照中…";
        SetRunning(true);
        try
        {
            var capture = await Task.Run(
                () => CameraCapture.CaptureAsync(temporary, CurrentCameraDeviceId));
            var arguments = new List<string>
            {
                "-m", "backend.project", "import",
                "--root", projectRoot,
                "--class", ImportClass.Trim(),
                "--source", temporary,
                "--batch", $"camera-{DateTime.Now:yyyyMMdd-HHmmss}",
            };
            if (ImportAsTest)
            {
                arguments.Add("--split");
                arguments.Add("test");
            }

            var (exitCode, stdout, stderr) =
                await Task.Run(() => RunPythonCommand(arguments));
            if (exitCode != 0)
            {
                Status = "拍照成功，但导入失败：" +
                         (stderr.Trim().Length > 0 ? stderr.Trim() : stdout.Trim());
                return;
            }

            var document = ProjectDocument.Load(ProjectPath);
            RefreshProjectSummary(document);
            if (document.DatasetManifest is not null)
            {
                DatasetManifestPath = Path.GetFullPath(
                    Path.Combine(projectRoot, document.DatasetManifest));
            }

            LoadDatasetSummary(projectRoot, document);
            LoadSampleList(projectRoot);
            InvalidateDataCheck();
            LoadTrainingRuns(projectRoot);
            Status = $"拍照成功（{capture.DeviceName}，{capture.Bytes / 1024} KB，" +
                     $"{capture.Seconds:0.00} s），已导入类别 {ImportClass.Trim()}；" +
                     DescribeImport(stdout);
        }
        catch (Exception error)
        {
            Status = "拍照失败：" + error.Message;
        }
        finally
        {
            try
            {
                if (Directory.Exists(temporary))
                {
                    Directory.Delete(temporary, recursive: true);
                }
            }
            catch (IOException)
            {
                // 临时目录清理失败不影响主流程。
            }

            SetRunning(false);
        }
    }

    private async Task RunImportTreeAsync()
    {
        if (_repositoryRoot is null || _pythonPath is null)
        {
            Status = "环境不完整，无法批量导入";
            return;
        }

        if (string.IsNullOrWhiteSpace(ProjectPath) || !File.Exists(ProjectPath))
        {
            Status = "请先打开项目文件（project.json）";
            return;
        }

        if (string.IsNullOrWhiteSpace(ImportTreeSource) ||
            !Directory.Exists(ImportTreeSource))
        {
            Status = "请填写存在的批量来源目录（来源/类别/批次）";
            return;
        }

        var projectRoot = Path.GetDirectoryName(Path.GetFullPath(ProjectPath)) ?? string.Empty;
        var arguments = new List<string>
        {
            "-m", "backend.project", "import-tree",
            "--root", projectRoot,
            "--source", ImportTreeSource,
        };

        Status = "批量导入中…";
        SetRunning(true);
        try
        {
            var (exitCode, stdout, stderr) =
                await Task.Run(() => RunPythonCommand(arguments));
            if (exitCode != 0)
            {
                Status = "批量导入失败：" +
                         (stderr.Trim().Length > 0 ? stderr.Trim() : stdout.Trim());
                return;
            }

            var document = ProjectDocument.Load(ProjectPath);
            RefreshProjectSummary(document);
            if (document.DatasetManifest is not null)
            {
                DatasetManifestPath = Path.GetFullPath(
                    Path.Combine(projectRoot, document.DatasetManifest));
            }

            LoadDatasetSummary(projectRoot, document);
            LoadSampleList(projectRoot);
            InvalidateDataCheck();
            LoadTrainingRuns(projectRoot);
            Status = DescribeImportTree(stdout);
        }
        catch (Exception error)
        {
            Status = "批量导入失败：" + error.Message;
        }
        finally
        {
            SetRunning(false);
        }
    }

    private async Task RunCreateProjectAsync()
    {
        if (_pythonPath is null || _repositoryRoot is null)
        {
            Status = "环境不完整，无法创建项目";
            return;
        }

        if (string.IsNullOrWhiteSpace(NewProjectRoot))
        {
            Status = "请填写项目目录";
            return;
        }

        if (string.IsNullOrWhiteSpace(NewProjectName))
        {
            Status = "请填写项目名称";
            return;
        }

        var classes = SplitClasses(NewProjectClasses);
        if (classes.Count < 2)
        {
            Status = "至少填写 2 个类别（逗号或空格分隔）";
            return;
        }

        var root = NewProjectRoot.Trim();
        var arguments = new List<string>
        {
            "-m", "backend.project", "create",
            "--root", root,
            "--name", NewProjectName.Trim(),
            "--classes",
        };
        arguments.AddRange(classes);

        Status = "创建项目中…";
        SetRunning(true);
        try
        {
            var (exitCode, stdout, stderr) =
                await Task.Run(() => RunPythonCommand(arguments));
            if (exitCode != 0)
            {
                Status = "创建失败：" + (stderr.Trim().Length > 0 ? stderr.Trim() : stdout.Trim());
                return;
            }

            ProjectPath = Path.Combine(root, "project.json");
            OpenProject();
            Status = "已创建并打开项目：" + NewProjectName.Trim();
        }
        catch (Exception error)
        {
            Status = "创建失败：" + error.Message;
        }
        finally
        {
            SetRunning(false);
        }
    }

    private static List<string> SplitClasses(string text)
    {
        var separators = new[] { ',', '，', ';', '；', '、', ' ', '\t', '\r', '\n' };
        return text
            .Split(
                separators,
                StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Distinct(StringComparer.Ordinal)
            .ToList();
    }

    private async Task RunDeleteSampleAsync()
    {
        if (_pythonPath is null || _repositoryRoot is null)
        {
            Status = "环境不完整，无法删除样本";
            return;
        }

        if (string.IsNullOrWhiteSpace(ProjectPath) || !File.Exists(ProjectPath))
        {
            Status = "请先打开项目文件（project.json）";
            return;
        }

        if (SelectedSample is null)
        {
            Status = "请先选择要删除的样本";
            return;
        }

        var projectRoot = Path.GetDirectoryName(Path.GetFullPath(ProjectPath)) ?? string.Empty;
        var target = SelectedSample.Path;
        Status = "删除样本…";
        SetRunning(true);
        try
        {
            var (exitCode, stdout, stderr) = await Task.Run(() =>
                RunPythonCommand(new[]
                {
                    "-m", "backend.project", "delete-sample",
                    "--root", projectRoot,
                    "--path", target,
                }));
            if (exitCode != 0)
            {
                Status = "删除失败：" + (stderr.Trim().Length > 0 ? stderr.Trim() : stdout.Trim());
                return;
            }

            var document = ProjectDocument.Load(ProjectPath);
            LoadDatasetSummary(projectRoot, document);
            LoadSampleList(projectRoot);
            InvalidateDataCheck();
            LoadTrainingRuns(projectRoot);
            Status = "已删除样本：" + target;
        }
        catch (Exception error)
        {
            Status = "删除失败：" + error.Message;
        }
        finally
        {
            SetRunning(false);
        }
    }

    private void LoadSampleList(string projectRoot)
    {
        SampleEntries.Clear();
        SelectedSample = null;
        if (_pythonPath is null || _repositoryRoot is null)
        {
            Status = "环境不完整，无法读取样本";
            return;
        }

        var (exitCode, stdout, stderr) = RunPythonCommand(new[]
        {
            "-m", "backend.project", "samples",
            "--root", projectRoot,
        });
        if (exitCode != 0)
        {
            Status = "读取样本失败：" + (stderr.Trim().Length > 0 ? stderr.Trim() : stdout.Trim());
            return;
        }

        try
        {
            var list = SampleList.Parse(stdout);
            _sampleRoot = Path.Combine(projectRoot, "data");
            foreach (var sample in list.Samples)
            {
                SampleEntries.Add(sample);
            }

            SelectedSample = SampleEntries.FirstOrDefault();
        }
        catch (SampleListException error)
        {
            Status = "读取样本失败：" + error.Message;
        }
    }

    private void LoadSamplePreview()
    {
        if (SelectedSample is null || _sampleRoot is null)
        {
            SelectedSampleImage = null;
            return;
        }

        var path = Path.Combine(_sampleRoot, SelectedSample.Path);
        if (!File.Exists(path))
        {
            SelectedSampleImage = null;
            return;
        }

        try
        {
            var bitmap = new BitmapImage();
            bitmap.BeginInit();
            bitmap.CacheOption = BitmapCacheOption.OnLoad;
            bitmap.UriSource = new Uri(path, UriKind.Absolute);
            bitmap.EndInit();
            bitmap.Freeze();
            SelectedSampleImage = bitmap;
        }
        catch (Exception)
        {
            SelectedSampleImage = null;
        }
    }

    private async Task RunRenameProjectAsync()
    {
        if (string.IsNullOrWhiteSpace(EditProjectName))
        {
            Status = "请填写项目名称";
            return;
        }

        var projectRoot = CurrentProjectRootOrNull();
        if (projectRoot is null)
        {
            return;
        }

        await RunProjectEditAsync(
            new[]
            {
                "-m", "backend.project", "rename",
                "--root", projectRoot,
                "--name", EditProjectName.Trim(),
            },
            "项目已改名");
    }

    private async Task RunAddClassAsync()
    {
        if (string.IsNullOrWhiteSpace(NewClassName))
        {
            Status = "请填写要添加的类别";
            return;
        }

        var projectRoot = CurrentProjectRootOrNull();
        if (projectRoot is null)
        {
            return;
        }

        await RunProjectEditAsync(
            new[]
            {
                "-m", "backend.project", "add-class",
                "--root", projectRoot,
                "--name", NewClassName.Trim(),
            },
            "已添加类别");
    }

    private async Task RunRemoveClassAsync()
    {
        if (string.IsNullOrWhiteSpace(RemoveClassName))
        {
            Status = "请填写要删除的类别";
            return;
        }

        var projectRoot = CurrentProjectRootOrNull();
        if (projectRoot is null)
        {
            return;
        }

        var arguments = new List<string>
        {
            "-m", "backend.project", "remove-class",
            "--root", projectRoot,
            "--name", RemoveClassName.Trim(),
        };
        if (RemoveClassWithData)
        {
            arguments.Add("--with-data");
        }

        await RunProjectEditAsync(arguments, "已删除类别");
    }

    private string? CurrentProjectRootOrNull()
    {
        if (_pythonPath is null || _repositoryRoot is null)
        {
            Status = "环境不完整";
            return null;
        }

        if (string.IsNullOrWhiteSpace(ProjectPath) || !File.Exists(ProjectPath))
        {
            Status = "请先打开项目文件（project.json）";
            return null;
        }

        return Path.GetDirectoryName(Path.GetFullPath(ProjectPath)) ?? string.Empty;
    }

    private void LoadTrainingRuns(string projectRoot)
    {
        TrainingRuns.Clear();
        SelectedTrainingRun = null;
        if (_pythonPath is null || _repositoryRoot is null)
        {
            return;
        }

        var (exitCode, stdout, stderr) = RunPythonCommand(new[]
        {
            "-m", "backend.project", "runs",
            "--root", projectRoot,
        });
        if (exitCode != 0)
        {
            Status = "读取训练历史失败：" +
                     (stderr.Trim().Length > 0 ? stderr.Trim() : stdout.Trim());
            return;
        }

        try
        {
            var list = TrainingRunList.Parse(stdout);
            foreach (var run in list.Runs)
            {
                TrainingRuns.Add(run);
            }

            SelectedTrainingRun = TrainingRuns.FirstOrDefault();
        }
        catch (TrainingRunListException error)
        {
            Status = "读取训练历史失败：" + error.Message;
        }
    }

    /// <summary>
    /// 扫描项目根目录 runs/batch-predict-*.json，刷新批量预测历史列表
    /// （按文件名倒序保留最近 10 条）。未打开项目时清空；单个文件损坏时跳过，不抛异常。
    /// </summary>
    public void LoadBatchPredictionHistory()
    {
        BatchPredictionHistory.Clear();
        _batchHistoryPaths.Clear();
        SelectedBatchHistory = null;
        if (string.IsNullOrWhiteSpace(ProjectPath) || !File.Exists(ProjectPath))
        {
            return;
        }

        try
        {
            var projectRoot = Path.GetDirectoryName(Path.GetFullPath(ProjectPath));
            if (string.IsNullOrWhiteSpace(projectRoot))
            {
                return;
            }

            var runsDir = Path.Combine(projectRoot, "runs");
            if (!Directory.Exists(runsDir))
            {
                return;
            }

            var files = Directory
                .EnumerateFiles(runsDir, "batch-predict-*.json", SearchOption.TopDirectoryOnly)
                .OrderByDescending(path => Path.GetFileName(path), StringComparer.Ordinal)
                .Take(10);
            foreach (var file in files)
            {
                var entry = DescribeBatchPredictionFile(file);
                if (entry is not null)
                {
                    BatchPredictionHistory.Add(entry);
                    // 显示文本理论上可能重复（同一分钟、同张数、同准确率），保留较新的文件。
                    if (!_batchHistoryPaths.ContainsKey(entry))
                    {
                        _batchHistoryPaths[entry] = file;
                    }
                }
            }
        }
        catch (Exception)
        {
            // 历史列表只是回看辅助功能，扫描失败不影响项目主流程。
        }
    }

    /// <summary>
    /// 扫描项目根目录 exports/&lt;产物 ID&gt;/model-package，刷新“模型对比”下拉框候选
    /// （按产物目录名倒序，新产物在前）。只收包含 manifest.json 的完整模型包，
    /// 避免选中残缺导出目录后无法对比；当前 PackagePath 若存在也加入并去重。
    /// 未打开项目时清空；单个目录不可读等异常时静默跳过。
    /// </summary>
    public void RefreshComparePackageOptions()
    {
        var previous = _selectedComparePackage;
        ComparePackageOptions.Clear();
        if (string.IsNullOrWhiteSpace(ProjectPath) || !File.Exists(ProjectPath))
        {
            return;
        }

        try
        {
            var projectRoot = Path.GetDirectoryName(Path.GetFullPath(ProjectPath));
            if (string.IsNullOrWhiteSpace(projectRoot))
            {
                return;
            }

            var exportsRoot = Path.Combine(projectRoot, "exports");
            if (Directory.Exists(exportsRoot))
            {
                var artifactDirs = Directory
                    .EnumerateDirectories(exportsRoot)
                    .OrderByDescending(path => Path.GetFileName(path), StringComparer.Ordinal);
                foreach (var artifactDir in artifactDirs)
                {
                    var packageDir = Path.Combine(artifactDir, "model-package");
                    if (Directory.Exists(packageDir) &&
                        File.Exists(Path.Combine(packageDir, "manifest.json")))
                    {
                        ComparePackageOptions.Add(packageDir);
                    }
                }
            }

            // 正在使用的模型包可能不在 exports 下（手动填写/项目外），目录存在即可作为候选。
            if (!string.IsNullOrWhiteSpace(PackagePath) &&
                Directory.Exists(PackagePath) &&
                !ComparePackageOptions.Contains(PackagePath, StringComparer.OrdinalIgnoreCase))
            {
                ComparePackageOptions.Add(PackagePath);
            }

            // 重建集合会清空 ComboBox 选中项；原选中项仍在候选中时恢复，避免刷新丢失选择。
            if (!string.IsNullOrWhiteSpace(previous))
            {
                var restored = ComparePackageOptions.FirstOrDefault(
                    option => string.Equals(option, previous, StringComparison.OrdinalIgnoreCase));
                if (restored is not null)
                {
                    SelectedComparePackage = restored;
                }
            }
        }
        catch (Exception)
        {
            // 下拉候选只是便捷选择，扫描失败不影响项目主流程。
        }
    }

    private static string? DescribeBatchPredictionFile(string path)
    {
        try
        {
            using var document = JsonDocument.Parse(File.ReadAllText(path));
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
            {
                return null;
            }

            var count = ReadBatchPredictionInteger(root, "count");
            if (count is null)
            {
                return null;
            }

            var labeled = ReadBatchPredictionInteger(root, "labeled") ?? 0;
            var accuracy = ReadBatchPredictionNumber(root, "accuracy");
            // 时间优先取文件名时间戳（yyyyMMdd-HHmmss），取不到时退回文件修改时间。
            var timestamp = ParseBatchPredictionFileName(path) ?? File.GetLastWriteTime(path);
            var accuracyText = accuracy is null
                ? $"准确率 —（{labeled} 张有真实类别）"
                : "准确率 " +
                  (accuracy.Value * 100.0).ToString("0.0", CultureInfo.InvariantCulture) +
                  "%";
            return $"{timestamp:yyyy-MM-dd HH:mm} · {count} 张 · {accuracyText}";
        }
        catch (Exception)
        {
            // 结果文件损坏或不可读时静默跳过，不影响其它历史记录。
            return null;
        }
    }

    private static int? ReadBatchPredictionInteger(JsonElement root, string propertyName)
    {
        if (!root.TryGetProperty(propertyName, out var element) ||
            element.ValueKind != JsonValueKind.Number)
        {
            return null;
        }

        if (element.TryGetInt32(out var integer))
        {
            return integer;
        }

        return element.TryGetDouble(out var value) &&
               double.IsFinite(value) &&
               value >= int.MinValue &&
               value <= int.MaxValue
            ? (int)value
            : null;
    }

    private static double? ReadBatchPredictionNumber(JsonElement root, string propertyName)
    {
        if (!root.TryGetProperty(propertyName, out var element) ||
            element.ValueKind != JsonValueKind.Number ||
            !element.TryGetDouble(out var value) ||
            !double.IsFinite(value))
        {
            return null;
        }

        return value;
    }

    private static DateTime? ParseBatchPredictionFileName(string path)
    {
        const string prefix = "batch-predict-";
        var name = Path.GetFileNameWithoutExtension(path);
        if (!name.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
        {
            return null;
        }

        return DateTime.TryParseExact(
            name[prefix.Length..],
            "yyyyMMdd-HHmmss",
            CultureInfo.InvariantCulture,
            DateTimeStyles.None,
            out var timestamp)
            ? timestamp
            : null;
    }

    /// <summary>
    /// 查看选中的批量预测历史：读取对应的 runs/batch-predict-*.json，把该次结果摘要
    /// 追加到 Messages（总体/各类/各批次/错误数量/CSV 路径），不清空已有消息。
    /// 文件已被删除时提示“历史结果文件不存在”；文件损坏或字段缺失时提示失败，不抛异常。
    /// </summary>
    private void ViewBatchHistoryDetail()
    {
        var selected = SelectedBatchHistory;
        if (string.IsNullOrWhiteSpace(selected))
        {
            Status = "请先选择批量预测历史";
            return;
        }

        if (!_batchHistoryPaths.TryGetValue(selected, out var path) || !File.Exists(path))
        {
            Status = "历史结果文件不存在";
            return;
        }

        try
        {
            using var document = JsonDocument.Parse(File.ReadAllText(path));
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
            {
                throw new InvalidDataException("JSON 根节点不是对象");
            }

            var count = RequireBatchHistoryInteger(root, "count");
            var labeled = RequireBatchHistoryInteger(root, "labeled");
            var accuracy = ReadBatchHistoryAccuracy(root);
            var perClass = RequireBatchHistoryProperty(root, "per_class", JsonValueKind.Object);
            var perBatch = RequireBatchHistoryProperty(root, "per_batch", JsonValueKind.Object);
            var errors = RequireBatchHistoryProperty(root, "errors", JsonValueKind.Array);

            var lines = new List<string>
            {
                "—— 历史批量预测结果 ——",
                accuracy is null
                    ? $"批量预测完成：{count} 张（{labeled} 张有真实类别）"
                    : $"批量预测完成：{count} 张，准确率 {accuracy.Value:P1}（{labeled} 张有真实类别）",
            };

            // 各类/各批次沿用批量预测消息格式；单个条目字段不全时跳过，避免脏数据中断回看。
            foreach (var entry in perClass.EnumerateObject())
            {
                var line = DescribeBatchHistoryStats("各类准确率", entry);
                if (line is not null)
                {
                    lines.Add(line);
                }
            }

            foreach (var entry in perBatch.EnumerateObject()
                         .OrderBy(item => item.Name, StringComparer.Ordinal))
            {
                var line = DescribeBatchHistoryStats("各批次准确率", entry);
                if (line is not null)
                {
                    lines.Add(line);
                }
            }

            lines.Add($"错误数量：{errors.GetArrayLength()} 张");
            lines.Add("结果 CSV：" + (ReadBatchHistoryString(root, "csv") ?? "（未记录）"));

            foreach (var line in lines)
            {
                Messages.Add(line);
            }

            Status = accuracy is null
                ? $"已载入历史批量预测结果：{count} 张"
                : $"已载入历史批量预测结果：{count} 张，准确率 {accuracy.Value:P1}";
        }
        catch (Exception error)
        {
            Status = "读取历史结果失败：" + error.Message;
        }
    }

    private static string? DescribeBatchHistoryStats(string label, JsonProperty entry)
    {
        var stats = entry.Value;
        if (stats.ValueKind != JsonValueKind.Object)
        {
            return null;
        }

        var accuracy = ReadBatchPredictionNumber(stats, "accuracy");
        var correct = ReadBatchPredictionInteger(stats, "correct");
        var count = ReadBatchPredictionInteger(stats, "count");
        if (accuracy is null || correct is null || count is null)
        {
            return null;
        }

        return $"{label}：{entry.Name} {accuracy.Value:P1}（{correct}/{count}）";
    }

    private static int RequireBatchHistoryInteger(JsonElement root, string propertyName) =>
        ReadBatchPredictionInteger(root, propertyName)
        ?? throw new InvalidDataException($"缺少字段 {propertyName} 或格式不正确");

    private static double? ReadBatchHistoryAccuracy(JsonElement root)
    {
        if (!root.TryGetProperty("accuracy", out var element) ||
            element.ValueKind == JsonValueKind.Null)
        {
            return null;
        }

        if (element.ValueKind != JsonValueKind.Number ||
            !element.TryGetDouble(out var accuracy) ||
            !double.IsFinite(accuracy))
        {
            throw new InvalidDataException("字段 accuracy 格式不正确");
        }

        return accuracy;
    }

    private static JsonElement RequireBatchHistoryProperty(
        JsonElement root,
        string propertyName,
        JsonValueKind kind)
    {
        if (!root.TryGetProperty(propertyName, out var element) || element.ValueKind != kind)
        {
            throw new InvalidDataException($"缺少字段 {propertyName} 或格式不正确");
        }

        return element;
    }

    private static string? ReadBatchHistoryString(JsonElement root, string propertyName)
    {
        if (!root.TryGetProperty(propertyName, out var element) ||
            element.ValueKind != JsonValueKind.String)
        {
            return null;
        }

        return element.GetString();
    }

    /// <summary>
    /// 扫描项目根目录 runs/compare-*.json，刷新模型对比历史列表
    /// （按文件名倒序保留最近 10 条，显示两包准确率与一致率）。
    /// 未打开项目时清空；accuracy/agreement 缺失时显示“—”；单个文件损坏时跳过，不抛异常。
    /// </summary>
    public void LoadCompareHistory()
    {
        CompareHistory.Clear();
        _compareHistoryPaths.Clear();
        SelectedCompareHistory = null;
        if (string.IsNullOrWhiteSpace(ProjectPath) || !File.Exists(ProjectPath))
        {
            return;
        }

        try
        {
            var projectRoot = Path.GetDirectoryName(Path.GetFullPath(ProjectPath));
            if (string.IsNullOrWhiteSpace(projectRoot))
            {
                return;
            }

            var runsDir = Path.Combine(projectRoot, "runs");
            if (!Directory.Exists(runsDir))
            {
                return;
            }

            var files = Directory
                .EnumerateFiles(runsDir, "compare-*.json", SearchOption.TopDirectoryOnly)
                .OrderByDescending(path => Path.GetFileName(path), StringComparer.Ordinal)
                .Take(10);
            foreach (var file in files)
            {
                var entry = DescribeCompareHistoryFile(file);
                if (entry is not null)
                {
                    CompareHistory.Add(entry);
                    // 显示文本理论上可能重复（同一分钟、同样的准确率），保留较新的文件。
                    if (!_compareHistoryPaths.ContainsKey(entry))
                    {
                        _compareHistoryPaths[entry] = file;
                    }
                }
            }
        }
        catch (Exception)
        {
            // 历史列表只是回看辅助功能，扫描失败不影响项目主流程。
        }
    }

    /// <summary>
    /// 读取单个 runs/compare-*.json，生成“时间 · A 准确率 / B 准确率 · 一致率”显示文本。
    /// 文件损坏或顶层不是对象时返回 null；字段缺失按“—”显示，不把文件当作损坏。
    /// </summary>
    private static string? DescribeCompareHistoryFile(string path)
    {
        try
        {
            using var document = JsonDocument.Parse(File.ReadAllText(path));
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
            {
                return null;
            }

            var accuracyA = ReadCompareHistoryPackageAccuracy(root, 0);
            var accuracyB = ReadCompareHistoryPackageAccuracy(root, 1);
            var ratio = ReadCompareAgreementRatio(root);
            // 时间优先取文件名时间戳（yyyyMMdd-HHmmss），取不到时退回文件修改时间。
            var timestamp = ParseCompareHistoryFileName(path) ?? File.GetLastWriteTime(path);
            return $"{timestamp:yyyy-MM-dd HH:mm} · "
                   + $"A {FormatCompareAccuracy(accuracyA, "—")} / "
                   + $"B {FormatCompareAccuracy(accuracyB, "—")} · "
                   + $"一致率 {(ratio is null ? "—" : FormatComparePercent(ratio.Value))}";
        }
        catch (Exception)
        {
            // 结果文件损坏或不可读时静默跳过，不影响其它历史记录。
            return null;
        }
    }

    private static double? ReadCompareHistoryPackageAccuracy(JsonElement root, int index)
    {
        return TryReadCompareHistoryPackage(root, index, out var package)
            ? ReadBatchPredictionNumber(package, "accuracy")
            : null;
    }

    private static string? ReadCompareHistoryPackageString(
        JsonElement root, int index, string propertyName)
    {
        return TryReadCompareHistoryPackage(root, index, out var package)
            ? ReadJsonStringOrNull(package, propertyName)
            : null;
    }

    private static List<string> ReadCompareHistoryPackageLabels(JsonElement root, int index)
    {
        return TryReadCompareHistoryPackage(root, index, out var package)
            ? ReadJsonStringArray(package, "labels")
            : new List<string>();
    }

    private static bool TryReadCompareHistoryPackage(
        JsonElement root, int index, out JsonElement package)
    {
        package = default;
        if (!root.TryGetProperty("packages", out var packages) ||
            packages.ValueKind != JsonValueKind.Array ||
            packages.GetArrayLength() <= index)
        {
            return false;
        }

        package = packages[index];
        return package.ValueKind == JsonValueKind.Object;
    }

    private static double? ReadCompareAgreementRatio(JsonElement root)
    {
        return root.TryGetProperty("agreement", out var agreement) &&
               agreement.ValueKind == JsonValueKind.Object
            ? ReadBatchPredictionNumber(agreement, "ratio")
            : null;
    }

    private static DateTime? ParseCompareHistoryFileName(string path)
    {
        const string prefix = "compare-";
        var name = Path.GetFileNameWithoutExtension(path);
        if (!name.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
        {
            return null;
        }

        return DateTime.TryParseExact(
            name[prefix.Length..],
            "yyyyMMdd-HHmmss",
            CultureInfo.InvariantCulture,
            DateTimeStyles.None,
            out var timestamp)
            ? timestamp
            : null;
    }

    private static string FormatComparePercent(double ratio) =>
        (ratio * 100.0).ToString("0.0", CultureInfo.InvariantCulture) + "%";

    private static string FormatCompareAccuracy(double? accuracy, string missing) =>
        accuracy is null ? missing : FormatComparePercent(accuracy.Value);

    private static List<string> ReadJsonStringArray(JsonElement element, string propertyName)
    {
        var values = new List<string>();
        if (element.ValueKind != JsonValueKind.Object ||
            !element.TryGetProperty(propertyName, out var array) ||
            array.ValueKind != JsonValueKind.Array)
        {
            return values;
        }

        foreach (var item in array.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.String)
            {
                continue;
            }

            var text = item.GetString()?.Trim();
            if (!string.IsNullOrEmpty(text))
            {
                values.Add(text);
            }
        }

        return values;
    }

    private static string? ReadJsonStringOrNull(JsonElement element, string propertyName)
    {
        if (element.ValueKind != JsonValueKind.Object ||
            !element.TryGetProperty(propertyName, out var value) ||
            value.ValueKind != JsonValueKind.String)
        {
            return null;
        }

        return value.GetString();
    }

    /// <summary>
    /// 查看选中的模型对比历史：读取对应的 runs/compare-*.json，把两包产物/准确率、
    /// 一致率、标签一致性、警告与最多 5 条分歧样本追加到 Messages，不清空已有消息。
    /// 文件已被删除或损坏时只在状态栏提示，不抛异常。
    /// </summary>
    private void ViewCompareHistoryDetail()
    {
        var selected = SelectedCompareHistory;
        if (string.IsNullOrWhiteSpace(selected))
        {
            Status = "请先选择对比历史";
            return;
        }

        if (!_compareHistoryPaths.TryGetValue(selected, out var path) || !File.Exists(path))
        {
            Status = "历史对比结果文件不存在";
            return;
        }

        try
        {
            using var document = JsonDocument.Parse(File.ReadAllText(path));
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
            {
                throw new InvalidDataException("JSON 根节点不是对象");
            }

            var count = ReadBatchPredictionInteger(root, "count") ?? 0;
            var labeled = ReadBatchPredictionInteger(root, "labeled") ?? 0;
            var ratio = ReadCompareAgreementRatio(root);
            // 标签一致性是后端提示字段，缺失时按“一致”处理（与实时对比一致）。
            var labelsMatch = !root.TryGetProperty("labels_match", out var labelsMatchElement) ||
                              labelsMatchElement.ValueKind != JsonValueKind.False;
            var accuracyA = ReadCompareHistoryPackageAccuracy(root, 0);
            var accuracyB = ReadCompareHistoryPackageAccuracy(root, 1);
            var artifactA = ReadCompareHistoryPackageString(root, 0, "artifact_id") ?? "（未知）";
            var artifactB = ReadCompareHistoryPackageString(root, 1, "artifact_id") ?? "（未知）";

            var lines = new List<string>
            {
                "—— 历史模型对比结果 ——",
                $"模型对比：A {FormatCompareAccuracy(accuracyA, "无真实标签")} / "
                + $"B {FormatCompareAccuracy(accuracyB, "无真实标签")}，"
                + (ratio is null ? "一致率 —" : $"一致率 {FormatComparePercent(ratio.Value)}")
                + $"（{count} 张）",
                DescribeCompareHistoryPackage("模型 A", artifactA, accuracyA, labeled),
                DescribeCompareHistoryPackage("模型 B", artifactB, accuracyB, labeled),
                labelsMatch
                    ? "标签一致性：一致"
                    : "标签一致性：不一致（两包标签顺序/内容不同，准确率/一致率不可比；"
                      + $"A：{DescribeCompareHistoryLabels(ReadCompareHistoryPackageLabels(root, 0))}"
                      + $" / B：{DescribeCompareHistoryLabels(ReadCompareHistoryPackageLabels(root, 1))}）",
            };

            var warnings = ReadJsonStringArray(root, "warnings");
            foreach (var warning in warnings.Take(5))
            {
                lines.Add("警告：" + warning);
            }

            if (warnings.Count > 5)
            {
                lines.Add($"（其余 {warnings.Count - 5} 条警告未显示）");
            }

            AppendCompareHistoryDisagreements(lines, root);

            foreach (var line in lines)
            {
                Messages.Add(line);
            }

            Status = "已载入历史模型对比结果";
        }
        catch (Exception error)
        {
            Status = "读取历史对比结果失败：" + error.Message;
        }
    }

    private static string DescribeCompareHistoryPackage(
        string name, string artifact, double? accuracy, int labeled) =>
        accuracy is null
            ? $"{name}：产物 {artifact}，无真实标签（平铺目录未统计准确率）"
            : $"{name}：产物 {artifact}，准确率 {FormatComparePercent(accuracy.Value)}"
              + $"（{labeled} 张有真实标签）";

    private static string DescribeCompareHistoryLabels(List<string> labels)
    {
        if (labels.Count == 0)
        {
            return "（无）";
        }

        return labels.Count <= 5
            ? string.Join("、", labels)
            : string.Join("、", labels.Take(5)) + "等";
    }

    private static void AppendCompareHistoryDisagreements(
        List<string> lines, JsonElement root)
    {
        if (!root.TryGetProperty("disagreements", out var disagreements) ||
            disagreements.ValueKind != JsonValueKind.Array)
        {
            return;
        }

        var total = disagreements.GetArrayLength();
        if (total == 0)
        {
            lines.Add("分歧样本：无");
            return;
        }

        var shown = 0;
        foreach (var item in disagreements.EnumerateArray())
        {
            if (shown >= 5)
            {
                break;
            }

            var image = ReadJsonStringOrNull(item, "image") ?? "（未知图片）";
            var predictedA = ReadJsonStringOrNull(item, "pred_a") ?? "（未知）";
            var predictedB = ReadJsonStringOrNull(item, "pred_b") ?? "（未知）";
            var trueLabel = ReadJsonStringOrNull(item, "true_label") ?? "无真实标签";
            lines.Add($"分歧：{image}｜A {predictedA} / B {predictedB}｜真实 {trueLabel}");
            shown++;
        }

        if (total > shown)
        {
            lines.Add($"（其余 {total - shown} 条分歧未显示）");
        }
    }

    private async Task RunExportRunAsync()
    {
        if (SelectedTrainingRun is null)
        {
            Status = "请先选择要导出的训练运行";
            return;
        }

        var projectRoot = CurrentProjectRootOrNull();
        if (projectRoot is null)
        {
            return;
        }

        var runId = SelectedTrainingRun.RunId;
        Status = "导出训练运行…";
        SetRunning(true);
        try
        {
            var (exitCode, stdout, stderr) = await Task.Run(() =>
                RunPythonCommand(new[]
                {
                    "-m", "backend.project", "export-run",
                    "--root", projectRoot,
                    "--run", runId,
                }));
            if (exitCode != 0)
            {
                Status = "导出失败：" +
                         (stderr.Trim().Length > 0 ? stderr.Trim() : stdout.Trim());
                return;
            }

            var document = ProjectDocument.Load(ProjectPath);
            RefreshProjectSummary(document);
            LoadTrainingReportForProject(projectRoot, document);
            LoadTrainingRuns(projectRoot);
            var current = document.CurrentModel();
            if (current is not null)
            {
                var manifestPath = Path.GetFullPath(
                    Path.Combine(projectRoot, current.Path));
                PackagePath = Path.GetDirectoryName(manifestPath) ?? string.Empty;
                Artifact = current.ArtifactId;
                Status = $"已导出运行 {runId}，当前模型：{current.ArtifactId}";
            }
            else
            {
                Status = "已导出运行，但项目未记录当前模型";
            }
        }
        catch (Exception error)
        {
            Status = "导出失败：" + error.Message;
        }
        finally
        {
            SetRunning(false);
        }
    }

    /// <summary>
    /// 导出批量预测历史汇总：调用 scripts/batch_history_export.py 生成
    /// runs/batch-history.md 与 runs/batch-history.csv，并把输出路径追加到消息区。
    /// 需先打开项目；脚本失败时取 JSON error 或 stderr 写入状态栏。
    /// </summary>
    private async Task RunExportBatchHistoryAsync()
    {
        if (_repositoryRoot is null || _pythonPath is null)
        {
            Status = "环境不完整，无法导出批量历史";
            return;
        }

        if (string.IsNullOrWhiteSpace(ProjectPath) || !File.Exists(ProjectPath))
        {
            Status = "请先打开项目文件（project.json）";
            return;
        }

        var projectRoot = Path.GetDirectoryName(Path.GetFullPath(ProjectPath));
        if (string.IsNullOrWhiteSpace(projectRoot))
        {
            Status = "无法确定项目目录";
            return;
        }

        var markdownPath = Path.Combine(projectRoot, "runs", "batch-history.md");
        var csvPath = Path.Combine(projectRoot, "runs", "batch-history.csv");
        Status = "导出批量历史…";
        SetRunning(true);
        try
        {
            var (exitCode, stdout, stderr) = await Task.Run(() =>
                RunPythonCommand(new[]
                {
                    "scripts/batch_history_export.py",
                    "--project", ProjectPath.Trim(),
                    "--markdown", markdownPath,
                    "--csv", csvPath,
                }));

            var parsed = TryReadBatchHistoryExport(
                stdout,
                out var runs,
                out var skipped,
                out var markdown,
                out var csv,
                out var error);
            if (exitCode != 0 || !parsed)
            {
                Status = "导出批量历史失败：" +
                         DescribeBatchHistoryExportFailure(error, stderr);
                return;
            }

            Messages.Add("—— 批量历史汇总导出 ——");
            Messages.Add("Markdown 汇总：" + (markdown ?? markdownPath));
            Messages.Add("CSV 汇总：" + (csv ?? csvPath));
            Status = $"已导出批量历史：{runs} 次运行（跳过 {skipped} 个）";
        }
        catch (Exception error)
        {
            Status = "导出批量历史失败：" + error.Message;
        }
        finally
        {
            SetRunning(false);
        }
    }

    /// <summary>
    /// 解析 batch_history_export.py 的标准输出 JSON 摘要。成功时带出 runs/skipped 与
    /// 报告路径；失败（JSON error）或输出不是 JSON 对象时返回 false 并带出 error（可能为 null）。
    /// </summary>
    private static bool TryReadBatchHistoryExport(
        string stdout,
        out int runs,
        out int skipped,
        out string? markdown,
        out string? csv,
        out string? error)
    {
        runs = 0;
        skipped = 0;
        markdown = null;
        csv = null;
        error = null;
        try
        {
            using var document = JsonDocument.Parse(stdout);
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
            {
                return false;
            }

            if (root.TryGetProperty("ok", out var ok) && ok.ValueKind == JsonValueKind.False)
            {
                error = ReadBatchHistoryString(root, "error");
                return false;
            }

            runs = root.TryGetProperty("runs", out var runsElement) &&
                   runsElement.ValueKind == JsonValueKind.Array
                ? runsElement.GetArrayLength()
                : 0;
            skipped = ReadBatchPredictionInteger(root, "skipped") ?? 0;
            markdown = ReadBatchHistoryString(root, "markdown");
            csv = ReadBatchHistoryString(root, "csv");
            return true;
        }
        catch (JsonException)
        {
            return false;
        }
    }

    private static string DescribeBatchHistoryExportFailure(string? jsonError, string stderr)
    {
        if (!string.IsNullOrWhiteSpace(jsonError))
        {
            return jsonError;
        }

        return stderr.Trim().Length > 0 ? stderr.Trim() : "未知错误";
    }

    private void StartAutoSelfTest()
    {
        var initialStatus = Status;
        Task.Run(() =>
        {
            SelfTestReport report;
            try
            {
                report = SelfTest.RunChecks();
            }
            catch (Exception error)
            {
                report = new SelfTestReport
                {
                    Ok = false,
                    Checks = new List<SelfTestCheck>
                    {
                        new() { Name = "self_test", Ok = false, Detail = error.Message },
                    },
                };
            }

            var dispatcher = Application.Current?.Dispatcher;
            void Apply() => ApplyAutoSelfTest(report, initialStatus);
            if (dispatcher is null || dispatcher.CheckAccess())
            {
                Apply();
            }
            else
            {
                dispatcher.Invoke(Apply);
            }
        });
    }

    private void ApplyAutoSelfTest(SelfTestReport report, string initialStatus)
    {
        if (report.Ok)
        {
            if (Status == initialStatus)
            {
                Status = "就绪（环境自检通过）";
            }

            return;
        }

        Messages.Add("—— 环境自检（自动） ——");
        foreach (var check in report.Checks.Where(item => !item.Ok))
        {
            Messages.Add($"失败 {check.Name}：{check.Detail}");
        }

        Messages.Add(
            "提示：确认 LAITP_HOME/LAITP_PYTHON 或使用离线包 start-desktop.bat；" +
            "也可点击“环境自检”重试。");
        if (Status == initialStatus)
        {
            Status = "环境自检未通过，请检查运行环境";
        }
    }

    private async Task RunSelfTestAsync()
    {
        Status = "环境自检中…";
        SetRunning(true);
        try
        {
            var report = await Task.Run(SelfTest.RunChecks);
            Messages.Add("—— 环境自检 ——");
            foreach (var check in report.Checks)
            {
                Messages.Add($"{(check.Ok ? "通过" : "失败")} {check.Name}：{check.Detail}");
            }

            var failed = report.Checks.Count(check => !check.Ok);
            Status = report.Ok
                ? "环境自检通过，可以开始使用"
                : $"环境自检未通过（{failed} 项失败）";
        }
        catch (Exception error)
        {
            Status = "环境自检失败：" + error.Message;
        }
        finally
        {
            SetRunning(false);
        }
    }

    private async Task RunCheckDatasetAsync(bool strict = false)
    {
        if (_pythonPath is null || _repositoryRoot is null)
        {
            Status = "环境不完整，无法检查数据";
            return;
        }

        if (string.IsNullOrWhiteSpace(ProjectPath) || !File.Exists(ProjectPath))
        {
            Status = "请先打开项目文件（project.json）";
            return;
        }

        var arguments = new List<string>
        {
            "-m", "backend.project", "check-dataset",
            "--root", Path.GetDirectoryName(Path.GetFullPath(ProjectPath)) ?? string.Empty,
        };
        if (strict)
        {
            if (!int.TryParse(MinTrainText, out var minTrain) || minTrain < 0 ||
                !int.TryParse(MinValText, out var minVal) || minVal < 0 ||
                !int.TryParse(MinTestText, out var minTest) || minTest < 0)
            {
                Status = "严格检查的样本下限必须是非负整数";
                return;
            }

            arguments.AddRange(new[]
            {
                "--require-test",
                "--min-train", minTrain.ToString(),
                "--min-val", minVal.ToString(),
                "--min-test", minTest.ToString(),
            });
        }

        Status = strict ? "严格验收检查中…" : "数据检查中…";
        try
        {
            var (exitCode, stdout, stderr) =
                await Task.Run(() => RunPythonCommand(arguments));
            if (string.IsNullOrWhiteSpace(stdout))
            {
                Status = "数据检查失败：" +
                         (stderr.Trim().Length > 0 ? stderr.Trim() : $"退出码 {exitCode}");
                return;
            }

            var report = DatasetCheckReport.Parse(stdout);
            UpdateDataCheck(report);
            Status = report.Ok
                ? (strict ? "严格验收检查通过" : "数据检查通过，可以开始训练")
                : $"数据检查未通过：{report.Issues.Count} 个问题";
        }
        catch (Exception error)
        {
            Status = "数据检查失败：" + error.Message;
        }
    }

    private void UpdateDataCheck(DatasetCheckReport report)
    {
        _lastDataCheckOk = report.Ok;
        DataCheckIssues.Clear();
        foreach (var issue in report.Issues)
        {
            DataCheckIssues.Add($"{issue.Code}：{issue.Message}");
        }

        DataCheckStatus = report.Ok
            ? "数据检查通过" + (report.Policy is { RequireTestSplit: true }
                ? $"（严格：每类 ≥ {report.Policy.MinTrainPerClass}/"
                  + $"{report.Policy.MinValPerClass}/{report.Policy.MinTestPerClass}）"
                : string.Empty)
            : $"数据检查未通过（{report.Issues.Count} 个问题）";
    }

    private void InvalidateDataCheck()
    {
        _lastDataCheckOk = false;
        DataCheckIssues.Clear();
        DataCheckStatus = "尚未检查";
    }

    /// <summary>
    /// 数据体检：生成 <c>runs/dataset-report.md</c> 与 <c>runs/dataset-samples.csv</c>。
    /// 后端脚本标准输出为 JSON 摘要（可能美化多行，也可能混有其它输出，见
    /// <see cref="FindJsonSummary"/>）。
    /// </summary>
    private async Task RunDatasetReportAsync()
    {
        if (_repositoryRoot is null || _pythonPath is null)
        {
            Status = "环境不完整，无法启动后端";
            return;
        }

        if (string.IsNullOrWhiteSpace(ProjectPath) || !File.Exists(ProjectPath))
        {
            Status = "请先打开项目文件（project.json）";
            return;
        }

        var projectFile = ProjectPath.Trim();
        var projectRoot = Path.GetDirectoryName(Path.GetFullPath(projectFile));
        if (string.IsNullOrWhiteSpace(projectRoot))
        {
            Status = "数据体检失败：无法确定项目目录";
            return;
        }

        var runsDir = Path.Combine(projectRoot, "runs");
        var reportPath = Path.Combine(runsDir, "dataset-report.md");
        var csvPath = Path.Combine(runsDir, "dataset-samples.csv");
        var arguments = new[]
        {
            "scripts/dataset_report.py",
            "--project", projectFile,
            "--output", reportPath,
            "--csv", csvPath,
        };

        Status = "数据体检中…";
        SetRunning(true);
        try
        {
            Directory.CreateDirectory(runsDir);
            var (exitCode, stdout, stderr) =
                await Task.Run(() => RunPythonCommand(arguments));
            var jsonText = FindJsonSummary(stdout);
            if (exitCode != 0)
            {
                Status = "数据体检失败：" +
                         DescribeDatasetReportError(jsonText, stdout, stderr, exitCode);
                return;
            }

            if (jsonText is null)
            {
                Status = "数据体检失败：" +
                         (stderr.Trim().Length > 0
                             ? stderr.Trim()
                             : $"命令未输出 JSON 摘要（退出码 {exitCode}）");
                return;
            }

            JsonDocument document;
            try
            {
                document = JsonDocument.Parse(jsonText);
            }
            catch (JsonException error)
            {
                Status = "数据体检失败：摘要 JSON 无法解析（" + error.Message + "）";
                return;
            }

            using (document)
            {
                var root = document.RootElement;
                if (!root.TryGetProperty("ok", out var okValue) ||
                    okValue.ValueKind != JsonValueKind.True)
                {
                    var message = JsonString(root, "error");
                    Status = "数据体检失败：" +
                             (string.IsNullOrWhiteSpace(message)
                                 ? DescribeDatasetReportError(jsonText, stdout, stderr, exitCode)
                                 : message);
                    return;
                }

                var samples = JsonInt32(root, "samples");
                var duplicates = JsonInt32(root, "duplicates");
                var invalid = JsonInt32(root, "invalid");
                var warnings = JsonInt32(root, "warnings");
                Messages.Add("数据体检报告：" + (JsonString(root, "report") ?? reportPath));
                Messages.Add("样本明细 CSV：" + (JsonString(root, "csv") ?? csvPath));
                Status = $"数据体检完成：{samples} 张样本，{duplicates} 组重复，"
                         + $"{invalid} 张无效，{warnings} 条风险"
                         + (warnings > 0 ? "，详见报告" : string.Empty);
            }
        }
        catch (Exception error)
        {
            Status = "数据体检失败：" + error.Message;
        }
        finally
        {
            SetRunning(false);
        }
    }

    /// <summary>
    /// 项目校验（课前自检）：调用
    /// <c>python -m backend.project verify --root &lt;项目目录&gt;</c>，
    /// 检查 project.json、数据清单类别一致性以及模型产物存在性与 SHA-256 摘要。
    /// 命令只读，不修改项目；失败时消息区最多列出 10 条问题，其余只报数量。
    /// </summary>
    private async Task RunVerifyProjectAsync()
    {
        if (_repositoryRoot is null || _pythonPath is null)
        {
            Status = "环境不完整，无法启动后端";
            return;
        }

        if (string.IsNullOrWhiteSpace(ProjectPath) || !File.Exists(ProjectPath))
        {
            Status = "请先打开项目文件（project.json）";
            return;
        }

        var projectRoot = Path.GetDirectoryName(Path.GetFullPath(ProjectPath.Trim()));
        if (string.IsNullOrWhiteSpace(projectRoot))
        {
            Status = "项目校验失败：无法确定项目目录";
            return;
        }

        var arguments = new[]
        {
            "-m", "backend.project", "verify",
            "--root", projectRoot,
        };

        Status = "项目校验中…";
        SetRunning(true);
        try
        {
            var (exitCode, stdout, stderr) =
                await Task.Run(() => RunPythonCommand(arguments));
            var jsonText = FindJsonSummary(stdout);
            JsonDocument? document = null;
            if (jsonText is not null)
            {
                try
                {
                    document = JsonDocument.Parse(jsonText);
                }
                catch (JsonException)
                {
                    // 摘要不是合法 JSON：按失败处理，错误信息退回进程输出。
                }
            }

            using (document)
            {
                // 命令退出码 0 且摘要明确 ok:true 才算通过；避免把“退出码 0
                // 但报告失败/无摘要”误判为通过。
                if (exitCode == 0 && IsVerifyProjectOk(document))
                {
                    Messages.Add("—— 项目校验 ——");
                    Messages.Add("项目校验通过");
                    Status = "项目校验通过：" + projectRoot;
                    return;
                }

                var issues = ReadVerifyProjectIssues(document);
                if (issues.Count > 0)
                {
                    Messages.Add("—— 项目校验 ——");
                    Messages.Add($"项目校验失败：{issues.Count} 个问题");
                    foreach (var issue in issues.Take(10))
                    {
                        Messages.Add(issue);
                    }

                    if (issues.Count > 10)
                    {
                        Messages.Add($"……其余 {issues.Count - 10} 个问题未列出");
                    }

                    Status = $"项目校验失败：{issues.Count} 个问题";
                    return;
                }

                var detail = DescribeVerifyProjectError(document, stdout, stderr, exitCode);
                Messages.Add("—— 项目校验 ——");
                Messages.Add("项目校验失败：" + detail);
                Status = "项目校验失败：" + detail;
            }
        }
        catch (Exception error)
        {
            Status = "项目校验失败：" + error.Message;
        }
        finally
        {
            SetRunning(false);
        }
    }

    /// <summary>
    /// 打开“数据体检”生成的 <c>runs/dataset-report.md</c>：优先交给 .md 关联程序，
    /// 失败时回退到在资源管理器中选中该文件。
    /// </summary>
    private void OpenDatasetReport()
    {
        if (string.IsNullOrWhiteSpace(ProjectPath) || !File.Exists(ProjectPath))
        {
            Status = "请先打开项目文件（project.json）";
            return;
        }

        string reportPath;
        try
        {
            var projectRoot = Path.GetDirectoryName(Path.GetFullPath(ProjectPath.Trim()));
            if (string.IsNullOrWhiteSpace(projectRoot))
            {
                Status = "打开报告失败：无法确定项目目录";
                return;
            }

            reportPath = Path.Combine(projectRoot, "runs", "dataset-report.md");
        }
        catch (Exception error)
        {
            Status = "打开报告失败：" + error.Message;
            return;
        }

        if (!File.Exists(reportPath))
        {
            Status = "未找到数据体检报告，请先点“数据体检”";
            return;
        }

        try
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = reportPath,
                UseShellExecute = true,
            });
            Status = "已打开数据体检报告：" + reportPath;
        }
        catch (Exception error)
        {
            try
            {
                Process.Start(new ProcessStartInfo
                {
                    FileName = "explorer.exe",
                    Arguments = "/select,\"" + reportPath + "\"",
                    UseShellExecute = true,
                });
                Status = "打开报告失败：" + error.Message
                         + "；已打开报告所在目录：" + Path.GetDirectoryName(reportPath);
            }
            catch (Exception fallbackError)
            {
                Status = "打开报告失败：" + error.Message
                         + "；打开报告所在目录也失败：" + fallbackError.Message;
            }
        }
    }

    /// <summary>
    /// 从标准输出中提取 JSON 摘要对象。CLI 的 <c>emit_json</c> 会美化输出为多行，
    /// 也可能在摘要前混有其它输出：先尝试整体解析，再取最后一个以 <c>{</c> 开头的
    /// 行到末尾的片段逐段尝试。
    /// </summary>
    private static string? FindJsonSummary(string text)
    {
        var trimmed = text.Trim();
        if (trimmed.Length == 0)
        {
            return null;
        }

        if (IsJsonObject(trimmed))
        {
            return trimmed;
        }

        var lines = text.Split('\n');
        for (var index = lines.Length - 1; index >= 0; index--)
        {
            if (!lines[index].TrimStart().StartsWith('{'))
            {
                continue;
            }

            var candidate = string.Join('\n', lines[index..]).Trim();
            if (IsJsonObject(candidate))
            {
                return candidate;
            }
        }

        return null;
    }

    private static bool IsJsonObject(string text)
    {
        try
        {
            using var document = JsonDocument.Parse(text);
            return document.RootElement.ValueKind == JsonValueKind.Object;
        }
        catch (JsonException)
        {
            return false;
        }
    }

    private static string? JsonString(JsonElement root, string property)
    {
        return root.ValueKind == JsonValueKind.Object &&
               root.TryGetProperty(property, out var value) &&
               value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;
    }

    private static int JsonInt32(JsonElement root, string property)
    {
        return root.ValueKind == JsonValueKind.Object &&
               root.TryGetProperty(property, out var value) &&
               value.ValueKind == JsonValueKind.Number &&
               value.TryGetInt32(out var result)
            ? result
            : 0;
    }

    /// <summary>
    /// 从错误 JSON 摘要中取 <c>error</c>；摘要不可用时退回 stderr/stdout 与退出码信息。
    /// </summary>
    private static string DescribeDatasetReportError(
        string? jsonText, string stdout, string stderr, int exitCode)
    {
        if (jsonText is not null)
        {
            try
            {
                using var document = JsonDocument.Parse(jsonText);
                var message = JsonString(document.RootElement, "error");
                if (!string.IsNullOrWhiteSpace(message))
                {
                    return message;
                }
            }
            catch (JsonException)
            {
                // 摘要不是合法 JSON，退回进程输出。
            }
        }

        if (!string.IsNullOrWhiteSpace(stderr))
        {
            return stderr.Trim();
        }

        if (!string.IsNullOrWhiteSpace(stdout))
        {
            return stdout.Trim();
        }

        return $"命令退出码 {exitCode}，没有输出错误信息";
    }

    /// <summary>校验 JSON 摘要是否明确报告 <c>ok:true</c>（摘要缺失或格式不符时为 false）。</summary>
    private static bool IsVerifyProjectOk(JsonDocument? document)
    {
        return document is not null &&
               document.RootElement.ValueKind == JsonValueKind.Object &&
               document.RootElement.TryGetProperty("ok", out var value) &&
               value.ValueKind == JsonValueKind.True;
    }

    /// <summary>
    /// 把校验 JSON 摘要中的 <c>issues</c> 数组整理成“code：message”行；
    /// 缺少 code 时只保留 message。摘要缺失或结构不符时返回空列表。
    /// </summary>
    private static List<string> ReadVerifyProjectIssues(JsonDocument? document)
    {
        var issues = new List<string>();
        if (document is null ||
            document.RootElement.ValueKind != JsonValueKind.Object ||
            !document.RootElement.TryGetProperty("issues", out var array) ||
            array.ValueKind != JsonValueKind.Array)
        {
            return issues;
        }

        foreach (var item in array.EnumerateArray())
        {
            var code = ReadJsonString(item, "code");
            var message = ReadJsonString(item, "message");
            if (code.Length == 0 && message.Length == 0)
            {
                continue;
            }

            issues.Add(code.Length == 0 ? message : $"{code}：{message}");
        }

        return issues;
    }

    /// <summary>
    /// 项目校验失败但没有可列问题时的错误摘要：优先取 JSON 报告中的
    /// <c>error</c>，其次 stderr/stdout，最后说明退出码。
    /// </summary>
    private static string DescribeVerifyProjectError(
        JsonDocument? document, string stdout, string stderr, int exitCode)
    {
        var message = document is null ? null : JsonString(document.RootElement, "error");
        if (!string.IsNullOrWhiteSpace(message))
        {
            return message;
        }

        if (!string.IsNullOrWhiteSpace(stderr))
        {
            return stderr.Trim();
        }

        if (!string.IsNullOrWhiteSpace(stdout))
        {
            return stdout.Trim();
        }

        return $"命令退出码 {exitCode}，没有输出错误信息";
    }

    private async Task RunRenameClassAsync()
    {
        if (string.IsNullOrWhiteSpace(RenameClassOld) || string.IsNullOrWhiteSpace(RenameClassNew))
        {
            Status = "请填写原类别与新类别名称";
            return;
        }

        var projectRoot = CurrentProjectRootOrNull();
        if (projectRoot is null)
        {
            return;
        }

        await RunProjectEditAsync(
            new[]
            {
                "-m", "backend.project", "rename-class",
                "--root", projectRoot,
                "--old", RenameClassOld.Trim(),
                "--new", RenameClassNew.Trim(),
            },
            "已重命名类别");
    }

    private async Task RunRenameSampleAsync()
    {
        if (SelectedSample is null)
        {
            Status = "请先选择要重命名的样本";
            return;
        }

        if (string.IsNullOrWhiteSpace(SampleNewName))
        {
            Status = "请填写样本新文件名";
            return;
        }

        var projectRoot = CurrentProjectRootOrNull();
        if (projectRoot is null)
        {
            return;
        }

        var target = SelectedSample.Path;
        Status = "重命名样本…";
        SetRunning(true);
        try
        {
            var (exitCode, stdout, stderr) = await Task.Run(() =>
                RunPythonCommand(new[]
                {
                    "-m", "backend.project", "rename-sample",
                    "--root", projectRoot,
                    "--path", target,
                    "--name", SampleNewName.Trim(),
                }));
            if (exitCode != 0)
            {
                Status = "重命名失败：" +
                         (stderr.Trim().Length > 0 ? stderr.Trim() : stdout.Trim());
                return;
            }

            var newPath = ExtractString(stdout, "new_path");
            LoadSampleList(projectRoot);
            InvalidateDataCheck();
            LoadTrainingRuns(projectRoot);
            var renamed = SampleEntries.FirstOrDefault(
                sample => sample.Path == newPath);
            if (renamed is not null)
            {
                SelectedSample = renamed;
            }

            Status = "已重命名样本：" + (newPath ?? target);
        }
        catch (Exception error)
        {
            Status = "重命名失败：" + error.Message;
        }
        finally
        {
            SetRunning(false);
        }
    }

    private static string? ExtractString(string json, string property)
    {
        try
        {
            using var document = JsonDocument.Parse(json);
            return document.RootElement.TryGetProperty(property, out var value) &&
                   value.ValueKind == JsonValueKind.String
                ? value.GetString()
                : null;
        }
        catch (JsonException)
        {
            return null;
        }
    }

    private async Task RunProjectEditAsync(
        IReadOnlyList<string> arguments, string successMessage)
    {
        Status = "处理中…";
        SetRunning(true);
        try
        {
            var (exitCode, stdout, stderr) =
                await Task.Run(() => RunPythonCommand(arguments));
            if (exitCode != 0)
            {
                Status = "操作失败：" + (stderr.Trim().Length > 0 ? stderr.Trim() : stdout.Trim());
                return;
            }

            ReloadProjectAfterEdit();
            Status = successMessage + (HasManifestWarning(stdout)
                ? "；数据清单未重建（需导入该类别数据后重建）"
                : string.Empty);
        }
        catch (Exception error)
        {
            Status = "操作失败：" + error.Message;
        }
        finally
        {
            SetRunning(false);
        }
    }

    private void ReloadProjectAfterEdit()
    {
        try
        {
            var document = ProjectDocument.Load(ProjectPath);
            var projectRoot = Path.GetDirectoryName(Path.GetFullPath(ProjectPath)) ?? string.Empty;
            RefreshProjectSummary(document);
            LoadDatasetSummary(projectRoot, document);
            LoadSampleList(projectRoot);
            InvalidateDataCheck();
            LoadTrainingRuns(projectRoot);
            EditProjectName = document.Name;
            if (document.Classes.Count > 0 && !document.Classes.Contains(ImportClass))
            {
                ImportClass = document.Classes[0];
            }
        }
        catch (ProjectDocumentException error)
        {
            Status = "重新加载项目失败：" + error.Message;
        }
    }

    private static bool HasManifestWarning(string stdout)
    {
        try
        {
            using var document = JsonDocument.Parse(stdout);
            return document.RootElement.TryGetProperty("manifest_error", out var error)
                && error.ValueKind == JsonValueKind.String
                && !string.IsNullOrWhiteSpace(error.GetString());
        }
        catch (JsonException)
        {
            return false;
        }
    }

    private static string DescribeImportTree(string stdout)
    {
        try
        {
            using var document = JsonDocument.Parse(stdout);
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
            {
                return "批量导入完成";
            }

            var imported = root.TryGetProperty("imported", out var value) ? value.GetInt32() : 0;
            var duplicates = root.TryGetProperty("duplicates", out var duplicateValue)
                ? duplicateValue.GetInt32()
                : 0;
            var invalid = root.TryGetProperty("invalid", out var invalidValue)
                ? invalidValue.GetInt32()
                : 0;
            var batches = root.TryGetProperty("batches", out var batchValue)
                ? batchValue.GetInt32()
                : 0;
            var message = $"批量导入完成：新增 {imported}，重复 {duplicates}，无效 {invalid}；批次 {batches}";
            var manifestMissing = !root.TryGetProperty("manifest_path", out var manifestPath) ||
                                  manifestPath.ValueKind == JsonValueKind.Null;
            if (manifestMissing &&
                root.TryGetProperty("items", out var items) &&
                items.ValueKind == JsonValueKind.Array)
            {
                foreach (var item in items.EnumerateArray())
                {
                    if (item.TryGetProperty("manifest_error", out var manifestError) &&
                        manifestError.ValueKind == JsonValueKind.String &&
                        !string.IsNullOrWhiteSpace(manifestError.GetString()))
                    {
                        message += "；数据清单未重建：" + manifestError.GetString();
                        break;
                    }
                }
            }

            return message;
        }
        catch (JsonException)
        {
            return "批量导入完成";
        }
    }

    private static string DescribeImport(string stdout)
    {
        try
        {
            using var document = JsonDocument.Parse(stdout);
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
            {
                return "导入完成";
            }

            var imported = root.TryGetProperty("imported", out var value) ? value.GetInt32() : 0;
            var duplicates = root.TryGetProperty("duplicates", out var duplicateValue)
                ? duplicateValue.GetInt32()
                : 0;
            var invalid = root.TryGetProperty("invalid", out var invalidValue)
                ? invalidValue.GetInt32()
                : 0;
            var message = $"导入完成：新增 {imported}，重复 {duplicates}，无效 {invalid}";
            if (root.TryGetProperty("manifest_error", out var manifestError) &&
                manifestError.ValueKind == JsonValueKind.String &&
                !string.IsNullOrWhiteSpace(manifestError.GetString()))
            {
                message += "；数据清单未重建：" + manifestError.GetString();
            }

            return message;
        }
        catch (JsonException)
        {
            return "导入完成";
        }
    }

    private (int ExitCode, string Stdout, string Stderr) RunPythonCommand(
        IReadOnlyList<string> arguments)
    {
        if (_pythonPath is null || _repositoryRoot is null)
        {
            return (-1, string.Empty, "环境不完整");
        }

        var startInfo = new ProcessStartInfo
        {
            FileName = _pythonPath,
            WorkingDirectory = _repositoryRoot,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
            StandardOutputEncoding = new UTF8Encoding(false),
            StandardErrorEncoding = new UTF8Encoding(false),
        };
        foreach (var argument in arguments)
        {
            startInfo.ArgumentList.Add(argument);
        }

        using var process = Process.Start(startInfo);
        if (process is null)
        {
            return (-1, string.Empty, "无法启动 Python 命令");
        }

        var stdout = process.StandardOutput.ReadToEnd();
        var stderr = process.StandardError.ReadToEnd();
        process.WaitForExit();
        return (process.ExitCode, stdout, stderr);
    }

    private void LoadTrainingReportForProject(string projectRoot, ProjectDocument document)
    {
        MisclassifiedSamples.Clear();
        var training = document.Models.LastOrDefault(model => model.Kind == "training");
        if (training is null)
        {
            TrainingSummary = "项目暂无训练记录";
            return;
        }

        var runDir = Path.GetDirectoryName(
            Path.GetFullPath(Path.Combine(projectRoot, training.Path))) ?? string.Empty;
        var metricsPath = Path.Combine(runDir, "metrics.json");
        if (!File.Exists(metricsPath))
        {
            TrainingSummary = "训练记录缺少 metrics.json：" + metricsPath;
            return;
        }

        try
        {
            var report = TrainingReport.Load(metricsPath);
            TrainingSummary = FormatTrainingReport(report);
            foreach (var sample in report.Misclassified())
            {
                MisclassifiedSamples.Add(
                    $"{sample.Path}｜预测 {report.Classes[sample.PredictedClassId]}"
                    + $"（真实 {report.Classes[sample.TrueClassId]}）");
            }

            if (MisclassifiedSamples.Count == 0)
            {
                MisclassifiedSamples.Add("（验证集全部正确）");
            }
        }
        catch (TrainingReportException error)
        {
            TrainingSummary = "读取训练结果失败：" + error.Message;
        }
    }

    private static string FormatTrainingReport(TrainingReport report)
    {
        var builder = new StringBuilder();
        builder.AppendLine($"运行 {report.RunId}（产物 {report.ArtifactId}）");
        builder.AppendLine(
            $"验证准确率 {report.Accuracy:P1}；最佳轮次 {report.BestEpoch}/{report.Epochs}；"
            + $"验证样本 {report.ValidationSamples}");
        for (var index = 0; index < report.Classes.Count; index++)
        {
            var recall = report.PerClassRecall[index];
            builder.AppendLine(
                $"{report.Classes[index]} 召回：{(recall is null ? "无验证样本" : recall.Value.ToString("P1"))}");
        }

        builder.AppendLine("混淆矩阵（行=真实，列=预测）：");
        for (var row = 0; row < report.Classes.Count; row++)
        {
            builder.AppendLine($"{report.Classes[row]}：{string.Join(" / ", report.ConfusionMatrix[row])}");
        }

        return builder.ToString().TrimEnd();
    }

    private async Task RunTrainingAsync()
    {
        if (_repositoryRoot is null || _pythonPath is null)
        {
            Status = "环境不完整，无法启动后端";
            return;
        }

        if (string.IsNullOrWhiteSpace(ProjectPath) || !File.Exists(ProjectPath))
        {
            Status = "请先打开项目文件（project.json）";
            return;
        }

        if (string.IsNullOrWhiteSpace(DatasetManifestPath) || !File.Exists(DatasetManifestPath))
        {
            Status = "请填写存在的数据清单（dataset-manifest.json）";
            return;
        }

        var weightsConfig = Path.Combine(_repositoryRoot, "configs", "weights.v1.json");
        if (!File.Exists(weightsConfig))
        {
            Status = "缺少预训练权重配置：" + weightsConfig;
            return;
        }

        if (!int.TryParse(EpochsText, out var epochs) || epochs < 1)
        {
            Status = "训练轮数必须是正整数";
            return;
        }

        await RunCheckDatasetAsync();
        if (!_lastDataCheckOk)
        {
            Status = "数据检查未通过，已取消训练；请先修正数据问题";
            return;
        }

        var projectRoot = Path.GetDirectoryName(Path.GetFullPath(ProjectPath)) ?? string.Empty;
        var dataRoot = Path.GetDirectoryName(Path.GetFullPath(DatasetManifestPath)) ?? projectRoot;
        var runsRoot = Path.Combine(projectRoot, "runs");
        var runId = "run-" + DateTime.Now.ToString("yyyyMMddHHmmss");
        var runDir = Path.Combine(runsRoot, runId);
        if (Directory.Exists(runDir))
        {
            runId += "-" + Guid.NewGuid().ToString("N")[..6];
            runDir = Path.Combine(runsRoot, runId);
        }

        var requestId = "req-" + Guid.NewGuid().ToString("N")[..12];
        var taskId = "task-" + Guid.NewGuid().ToString("N")[..12];
        var supervisor = new TaskSupervisor(
            _pythonPath,
            new[]
            {
                "-m", "backend.runtime.worker", "train",
                "--dataset", DatasetManifestPath,
                "--data-root", dataRoot,
                "--output", runsRoot,
                "--run-id", runId,
                "--weights-config", weightsConfig,
                "--epochs", epochs.ToString(),
                "--batch-size", "16",
                "--request-id", requestId,
                "--project-id", "proj-local",
                "--task-id", taskId,
            },
            _repositoryRoot,
            requestId,
            "proj-local",
            taskId);

        _supervisor = supervisor;
        Messages.Clear();
        Status = "训练中…";
        SetRunning(true);
        supervisor.MessageReceived += OnMessage;

        try
        {
            supervisor.Start();
            var outcome = await Task.Run(() => supervisor.WaitForExit(TimeSpan.FromMinutes(30)));
            if (outcome.State != TaskState.Succeeded)
            {
                ApplyOutcome(outcome);
                return;
            }

            var artifactId = outcome.ArtifactId ?? "（未知产物）";
            if (PublishTraining(projectRoot, runDir, out var message))
            {
                try
                {
                    var document = ProjectDocument.Load(ProjectPath);
                    RefreshProjectSummary(document);
                    LoadTrainingReportForProject(projectRoot, document);
                    LoadTrainingRuns(projectRoot);
                    LoadBatchPredictionHistory();
                    LoadCompareHistory();
                    var current = document.CurrentModel();
                    if (current is null)
                    {
                        RefreshComparePackageOptions();
                        Status = "训练与导出完成，但项目未记录当前模型";
                        return;
                    }

                    var manifestPath = Path.GetFullPath(
                        Path.Combine(projectRoot, current.Path));
                    PackagePath = Path.GetDirectoryName(manifestPath) ?? string.Empty;
                    Artifact = current.ArtifactId;
                    RefreshComparePackageOptions();
                    Status = $"训练与导出完成，当前模型：{current.ArtifactId}";
                }
                catch (ProjectDocumentException error)
                {
                    Status = "训练与导出完成，但刷新项目失败：" + error.Message;
                }
            }
            else
            {
                Status = $"训练完成（{artifactId}），但发布失败：{message}";
            }
        }
        catch (TimeoutException)
        {
            supervisor.Cancel("timeout");
            Status = "训练超时，已取消";
        }
        catch (Exception error)
        {
            Status = "训练失败：" + error.Message;
        }
        finally
        {
            supervisor.MessageReceived -= OnMessage;
            supervisor.Dispose();
            _supervisor = null;
            SetRunning(false);
        }
    }

    private bool PublishTraining(string projectRoot, string runDir, out string message)
    {
        if (_pythonPath is null || _repositoryRoot is null)
        {
            message = "环境不完整";
            return false;
        }

        var startInfo = new ProcessStartInfo
        {
            FileName = _pythonPath,
            WorkingDirectory = _repositoryRoot,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
            StandardOutputEncoding = new UTF8Encoding(false),
            StandardErrorEncoding = new UTF8Encoding(false),
        };
        foreach (var argument in new[]
                 {
                     "-m", "backend.project", "publish-training",
                     "--root", projectRoot,
                     "--run", runDir,
                 })
        {
            startInfo.ArgumentList.Add(argument);
        }

        using var process = Process.Start(startInfo);
        if (process is null)
        {
            message = "无法启动项目发布命令";
            return false;
        }

        var stdout = process.StandardOutput.ReadToEnd();
        var stderr = process.StandardError.ReadToEnd();
        process.WaitForExit();
        if (process.ExitCode != 0)
        {
            message = stderr.Trim().Length > 0 ? stderr.Trim() : stdout.Trim();
            return false;
        }

        message = stdout.Trim();
        return true;
    }

    private async Task RunBatchPredictAsync()
    {
        if (_repositoryRoot is null || _pythonPath is null)
        {
            Status = "环境不完整，无法启动后端";
            return;
        }

        if (string.IsNullOrWhiteSpace(PackagePath) || !Directory.Exists(PackagePath))
        {
            Status = "请先训练发布或填写有效的模型包目录";
            return;
        }

        if (string.IsNullOrWhiteSpace(BatchImagesPath) ||
            !Directory.Exists(BatchImagesPath))
        {
            Status = "请填写存在的批量图片目录（按 类别/… 组织可统计准确率）";
            return;
        }

        // 项目已打开时把逐张结果 JSON 留在项目 runs 下，便于课后复盘；
        // 未打开项目则退回临时文件，结束后清理。
        var projectOpened =
            !string.IsNullOrWhiteSpace(ProjectPath) && File.Exists(ProjectPath);
        var projectRoot = projectOpened
            ? Path.GetDirectoryName(Path.GetFullPath(ProjectPath)) ?? string.Empty
            : Path.GetTempPath();
        var timestamp = DateTime.Now.ToString("yyyyMMdd-HHmmss");
        var output = projectOpened
            ? Path.Combine(projectRoot, "runs", $"batch-predict-{timestamp}.json")
            : Path.Combine(Path.GetTempPath(), $"laitp-batch-{Guid.NewGuid():N}.json");
        var csvPath = Path.Combine(
            string.IsNullOrWhiteSpace(ProjectPath)
                ? Path.GetTempPath()
                : Path.GetDirectoryName(Path.GetFullPath(ProjectPath)) ?? Path.GetTempPath(),
            "runs",
            $"batch-predict-{timestamp}.csv");
        Status = "批量预测中…";
        SetRunning(true);
        try
        {
            if (projectOpened)
            {
                Directory.CreateDirectory(Path.Combine(projectRoot, "runs"));
            }

            var arguments = new List<string>
            {
                "-m", "backend.runtime.batch",
                "--package", PackagePath.Trim(),
                "--images", BatchImagesPath.Trim(),
                "--output", output,
                "--csv", csvPath,
            };
            var (exitCode, stdout, stderr) =
                await Task.Run(() => RunPythonCommand(arguments));
            if (!File.Exists(output))
            {
                Status = "批量预测失败：" +
                         (stderr.Trim().Length > 0 ? stderr.Trim() : stdout.Trim());
                return;
            }

            using var document = JsonDocument.Parse(await File.ReadAllTextAsync(output));
            var root = document.RootElement;
            var count = root.GetProperty("count").GetInt32();
            var labeled = root.GetProperty("labeled").GetInt32();
            double? accuracy = null;
            if (root.TryGetProperty("accuracy", out var accuracyElement) &&
                accuracyElement.ValueKind == JsonValueKind.Number)
            {
                accuracy = accuracyElement.GetDouble();
            }

            var lines = new List<string>
            {
                accuracy is null
                    ? $"批量预测完成：{count} 张（{labeled} 张有真实类别）"
                    : $"批量预测完成：{count} 张，准确率 {accuracy:P1}（{labeled} 张有真实类别）",
            };
            if (root.TryGetProperty("per_class", out var perClass) &&
                perClass.ValueKind == JsonValueKind.Object)
            {
                foreach (var entry in perClass.EnumerateObject())
                {
                    var stats = entry.Value;
                    if (stats.TryGetProperty("accuracy", out var classAccuracy) &&
                        classAccuracy.ValueKind == JsonValueKind.Number)
                    {
                        lines.Add(
                            $"各类准确率：{entry.Name} {classAccuracy.GetDouble():P1}" +
                            $"（{stats.GetProperty("correct").GetInt32()}/" +
                            $"{stats.GetProperty("count").GetInt32()}）");
                    }
                }
            }

            // 批次维度（类别/批次/*.png）按批次名排序输出；字段缺失时跳过该批次。
            if (root.TryGetProperty("per_batch", out var perBatch) &&
                perBatch.ValueKind == JsonValueKind.Object)
            {
                foreach (var entry in perBatch.EnumerateObject()
                             .OrderBy(item => item.Name, StringComparer.Ordinal))
                {
                    var stats = entry.Value;
                    if (stats.ValueKind == JsonValueKind.Object &&
                        stats.TryGetProperty("accuracy", out var batchAccuracy) &&
                        batchAccuracy.ValueKind == JsonValueKind.Number &&
                        stats.TryGetProperty("correct", out var batchCorrect) &&
                        batchCorrect.ValueKind == JsonValueKind.Number &&
                        stats.TryGetProperty("count", out var batchCount) &&
                        batchCount.ValueKind == JsonValueKind.Number)
                    {
                        lines.Add(
                            $"各批次准确率：{entry.Name} {batchAccuracy.GetDouble():P1}" +
                            $"（{batchCorrect.GetInt32()}/{batchCount.GetInt32()}）");
                    }
                }
            }

            var misjudged = new List<string>();
            foreach (var item in root.GetProperty("images").EnumerateArray())
            {
                if (item.TryGetProperty("correct", out var correct) &&
                    correct.ValueKind == JsonValueKind.False)
                {
                    misjudged.Add(
                        $"{item.GetProperty("image").GetString()}：" +
                        $"预测 {item.GetProperty("predicted_label").GetString()}，" +
                        $"真实 {item.GetProperty("true_label").GetString()}");
                }
            }

            lines.AddRange(misjudged.Take(10).Select(line => "误判：" + line));
            if (misjudged.Count > 10)
            {
                lines.Add($"（其余 {misjudged.Count - 10} 张误判未显示）");
            }

            lines.Add("结果 CSV：" + csvPath);
            lines.Add("结果 JSON：" + output);

            Messages.Clear();
            foreach (var line in lines)
            {
                Messages.Add(line);
            }

            Status = lines[0];
            if (exitCode != 0)
            {
                Status += "（存在单张失败）";
            }
        }
        catch (Exception error)
        {
            Status = "批量预测失败：" + error.Message;
        }
        finally
        {
            try
            {
                // 项目内的结果 JSON 保留；仅清理未打开项目时的临时文件。
                if (!projectOpened && File.Exists(output))
                {
                    File.Delete(output);
                }
            }
            catch (IOException)
            {
                // 临时文件清理失败不影响主流程。
            }

            LoadBatchPredictionHistory();
            SetRunning(false);
        }
    }

    private async Task RunCompareAsync()
    {
        if (_repositoryRoot is null || _pythonPath is null)
        {
            Status = "环境不完整，无法启动后端";
            return;
        }

        if (string.IsNullOrWhiteSpace(PackagePath) || !Directory.Exists(PackagePath))
        {
            Status = "请填写存在的模型包目录";
            return;
        }

        if (string.IsNullOrWhiteSpace(BatchImagesPath) ||
            !Directory.Exists(BatchImagesPath))
        {
            Status = "请填写存在的批量图片目录（按 类别/… 组织可统计准确率）";
            return;
        }

        if (string.IsNullOrWhiteSpace(ComparePackagePath) ||
            !Directory.Exists(ComparePackagePath))
        {
            Status = "请填写存在的对比模型包目录";
            return;
        }

        // 项目已打开时把对比结果 JSON 留在项目 runs 下，便于课后复盘；
        // 未打开项目则退回临时文件，结束后清理。
        var projectOpened =
            !string.IsNullOrWhiteSpace(ProjectPath) && File.Exists(ProjectPath);
        var projectRoot = projectOpened
            ? Path.GetDirectoryName(Path.GetFullPath(ProjectPath)) ?? string.Empty
            : Path.GetTempPath();
        var timestamp = DateTime.Now.ToString("yyyyMMdd-HHmmss");
        var output = projectOpened
            ? Path.Combine(projectRoot, "runs", $"compare-{timestamp}.json")
            : Path.Combine(Path.GetTempPath(), $"laitp-compare-{Guid.NewGuid():N}.json");
        Status = "模型对比中…";
        SetRunning(true);
        try
        {
            if (projectOpened)
            {
                Directory.CreateDirectory(Path.Combine(projectRoot, "runs"));
            }

            var arguments = new List<string>
            {
                "-m", "backend.runtime.compare",
                "--packages", PackagePath.Trim(), ComparePackagePath.Trim(),
                "--images", BatchImagesPath.Trim(),
                "--output", output,
            };
            var (exitCode, stdout, stderr) =
                await Task.Run(() => RunPythonCommand(arguments));
            if (!File.Exists(output))
            {
                Status = $"模型对比失败（退出码 {exitCode}）：" +
                         DescribeCommandFailure(stdout, stderr);
                return;
            }

            using var document =
                JsonDocument.Parse(await File.ReadAllTextAsync(output));
            var root = document.RootElement;
            var ok = !root.TryGetProperty("ok", out var okElement) ||
                     okElement.ValueKind != JsonValueKind.False;
            // 标签一致性与告警是后端新增的提示字段，缺失或格式异常时按“一致、无告警”处理。
            var labelsMatch = ReadBoolean(root, "labels_match", true);
            var labelsA = ReadStringArray(root, "labels_a");
            var labelsB = ReadStringArray(root, "labels_b");
            var warnings = ReadStringArray(root, "warnings");
            var lines = new List<string>();
            string? summaryLine = null;
            if (root.TryGetProperty("packages", out var packages) &&
                packages.ValueKind == JsonValueKind.Array &&
                packages.GetArrayLength() >= 2)
            {
                var count = ReadInteger(root, "count") ?? 0;
                var labeled = ReadInteger(root, "labeled") ?? 0;
                var packageA = packages[0];
                var packageB = packages[1];
                var artifactA = ReadString(packageA, "artifact_id") ?? "（未知）";
                var artifactB = ReadString(packageB, "artifact_id") ?? "（未知）";
                var accuracyA = ReadNumber(packageA, "accuracy");
                var accuracyB = ReadNumber(packageB, "accuracy");
                string? agreementRatio = null;
                var agreementTotal = count;
                if (root.TryGetProperty("agreement", out var agreement) &&
                    agreement.ValueKind == JsonValueKind.Object)
                {
                    agreementTotal = ReadInteger(agreement, "total") ?? count;
                    agreementRatio = ReadNumber(agreement, "ratio")?.ToString("P1");
                }

                summaryLine =
                    $"模型对比：A {DescribeAccuracy(accuracyA)} / "
                    + $"B {DescribeAccuracy(accuracyB)}，"
                    + (agreementRatio is null
                        ? "一致率 无可用图片"
                        : $"一致率 {agreementRatio}")
                    + $"（{agreementTotal} 张）";
                lines.Add(summaryLine);
                lines.Add(DescribePackage("模型 A", artifactA, accuracyA, labeled));
                lines.Add(DescribePackage("模型 B", artifactB, accuracyB, labeled));
                AddDisagreementLines(lines, root);
            }

            // 标签不一致时把不可比提示排在汇总行之后（无汇总行时置顶），
            // 不影响成功状态；后端 warnings 逐条追加，避免与失败混淆。
            if (!labelsMatch)
            {
                lines.Insert(
                    Math.Min(1, lines.Count),
                    "警告：两个模型包标签不一致，准确率/一致率不可比"
                    + $"（A：{DescribeLabels(labelsA)} / B：{DescribeLabels(labelsB)}）");
            }

            foreach (var warning in warnings.Take(5))
            {
                lines.Add("警告：" + warning);
            }

            if (warnings.Count > 5)
            {
                lines.Add($"（其余 {warnings.Count - 5} 条警告未显示）");
            }

            if (projectOpened)
            {
                lines.Add("结果 JSON：" + output);
            }

            Messages.Clear();
            foreach (var line in lines)
            {
                Messages.Add(line);
            }

            if (!ok)
            {
                var message = DescribeCompareFailure(root);
                Messages.Add("错误：" + message);
                Status = "模型对比失败：" + message;
                return;
            }

            Status = summaryLine is not null
                ? "模型对比完成：" + summaryLine.Replace("模型对比：", string.Empty)
                : "模型对比完成";
        }
        catch (Exception error)
        {
            Status = "模型对比失败：" + error.Message;
        }
        finally
        {
            try
            {
                // 项目内的结果 JSON 保留；仅清理未打开项目时的临时文件。
                if (!projectOpened && File.Exists(output))
                {
                    File.Delete(output);
                }
            }
            catch (IOException)
            {
                // 临时文件清理失败不影响主流程。
            }

            LoadCompareHistory();
            SetRunning(false);
        }

        static string? ReadString(JsonElement element, string property) =>
            element.TryGetProperty(property, out var value) &&
            value.ValueKind == JsonValueKind.String
                ? value.GetString()
                : null;

        static double? ReadNumber(JsonElement element, string property) =>
            element.TryGetProperty(property, out var value) &&
            value.ValueKind == JsonValueKind.Number
                ? value.GetDouble()
                : null;

        static int? ReadInteger(JsonElement element, string property) =>
            element.TryGetProperty(property, out var value) &&
            value.ValueKind == JsonValueKind.Number &&
            value.TryGetInt32(out var number)
                ? number
                : null;

        static bool ReadBoolean(JsonElement element, string property, bool fallback) =>
            element.ValueKind == JsonValueKind.Object &&
            element.TryGetProperty(property, out var value) &&
            (value.ValueKind == JsonValueKind.True ||
             value.ValueKind == JsonValueKind.False)
                ? value.GetBoolean()
                : fallback;

        static List<string> ReadStringArray(JsonElement element, string property)
        {
            var values = new List<string>();
            if (element.ValueKind != JsonValueKind.Object ||
                !element.TryGetProperty(property, out var array) ||
                array.ValueKind != JsonValueKind.Array)
            {
                return values;
            }

            foreach (var item in array.EnumerateArray())
            {
                if (item.ValueKind != JsonValueKind.String)
                {
                    continue;
                }

                var text = item.GetString()?.Trim();
                if (!string.IsNullOrEmpty(text))
                {
                    values.Add(text);
                }
            }

            return values;
        }

        static string DescribeLabels(List<string> labels)
        {
            if (labels.Count == 0)
            {
                return "（无）";
            }

            return labels.Count <= 5
                ? string.Join("、", labels)
                : string.Join("、", labels.Take(5)) + "等";
        }

        static string DescribeAccuracy(double? accuracy) =>
            accuracy is null ? "无真实标签" : accuracy.Value.ToString("P1");

        static string DescribePackage(
            string name, string artifact, double? accuracy, int labeled) =>
            accuracy is null
                ? $"{name}：产物 {artifact}，无真实标签（平铺目录未统计准确率）"
                : $"{name}：产物 {artifact}，准确率 {accuracy.Value:P1}"
                  + $"（{labeled} 张有真实标签）";

        static void AddDisagreementLines(List<string> lines, JsonElement root)
        {
            if (!root.TryGetProperty("disagreements", out var disagreements) ||
                disagreements.ValueKind != JsonValueKind.Array)
            {
                return;
            }

            var total = disagreements.GetArrayLength();
            if (total == 0)
            {
                lines.Add("分歧样本：无");
                return;
            }

            var shown = 0;
            foreach (var item in disagreements.EnumerateArray())
            {
                if (shown >= 5)
                {
                    break;
                }

                var image = ReadString(item, "image") ?? "（未知图片）";
                var predictedA = ReadString(item, "pred_a") ?? "（未知）";
                var predictedB = ReadString(item, "pred_b") ?? "（未知）";
                var trueLabel = ReadString(item, "true_label") ?? "无真实标签";
                lines.Add(
                    $"分歧：{image}｜A {predictedA} / B {predictedB}｜真实 {trueLabel}");
                shown++;
            }

            if (total > shown)
            {
                lines.Add($"（其余 {total - shown} 条分歧未显示）");
            }
        }

        static string DescribeCompareFailure(JsonElement root)
        {
            var error = ReadString(root, "error");
            if (!string.IsNullOrWhiteSpace(error))
            {
                return error;
            }

            if (root.TryGetProperty("errors", out var errors) &&
                errors.ValueKind == JsonValueKind.Array &&
                errors.GetArrayLength() > 0)
            {
                var first = errors[0];
                var message = ReadString(first, "error");
                if (!string.IsNullOrWhiteSpace(message))
                {
                    var image = ReadString(first, "image");
                    return string.IsNullOrWhiteSpace(image)
                        ? message
                        : $"{image}：{message}";
                }
            }

            return "没有可对比的图片";
        }

        static string DescribeCommandFailure(string stdout, string stderr)
        {
            try
            {
                using var document = JsonDocument.Parse(stdout);
                var error = ReadString(document.RootElement, "error");
                if (!string.IsNullOrWhiteSpace(error))
                {
                    return error;
                }
            }
            catch (JsonException)
            {
                // stdout 不是 JSON，退回原始输出。
            }

            return stderr.Trim().Length > 0 ? stderr.Trim() : stdout.Trim();
        }
    }

    private async Task RunPredictAsync()
    {
        if (_repositoryRoot is null || _pythonPath is null)
        {
            Status = "环境不完整，无法启动后端";
            return;
        }

        if (string.IsNullOrWhiteSpace(PackagePath) || !Directory.Exists(PackagePath))
        {
            Status = "请填写存在的模型包目录";
            return;
        }

        if (string.IsNullOrWhiteSpace(ImagePath) || !File.Exists(ImagePath))
        {
            Status = "请填写存在的待测图片路径";
            return;
        }

        var requestId = "req-" + Guid.NewGuid().ToString("N")[..12];
        var taskId = "task-" + Guid.NewGuid().ToString("N")[..12];
        var supervisor = new TaskSupervisor(
            _pythonPath,
            new[]
            {
                "-m", "backend.runtime.worker", "predict",
                "--package", PackagePath,
                "--image", ImagePath,
                "--request-id", requestId,
                "--project-id", "proj-local",
                "--task-id", taskId,
            },
            _repositoryRoot,
            requestId,
            "proj-local",
            taskId);

        _supervisor = supervisor;
        Messages.Clear();
        Artifact = string.Empty;
        Status = "运行中…";
        SetRunning(true);
        supervisor.MessageReceived += OnMessage;

        try
        {
            supervisor.Start();
            var outcome = await Task.Run(() => supervisor.WaitForExit(TimeSpan.FromMinutes(2)));
            ApplyOutcome(outcome);
        }
        catch (TimeoutException)
        {
            supervisor.Cancel("timeout");
            Status = "超时，已取消";
        }
        catch (Exception error)
        {
            Status = "失败：" + error.Message;
        }
        finally
        {
            supervisor.MessageReceived -= OnMessage;
            supervisor.Dispose();
            _supervisor = null;
            SetRunning(false);
        }
    }

    private void OnMessage(Envelope envelope)
    {
        var dispatcher = Application.Current?.Dispatcher;
        void Apply()
        {
            Messages.Add(envelope.MessageType switch
            {
                "progress" => $"进度：{envelope.PayloadString("stage") ?? "?"} "
                              + $"{envelope.PayloadInt64("completed")}/{envelope.PayloadInt64("total")?.ToString() ?? "?"}",
                "result" => $"完成：{envelope.PayloadArtifactId() ?? envelope.ArtifactId}",
                "error" => $"错误：{envelope.PayloadString("code")} {envelope.PayloadString("message")}",
                "cancelled" => "已取消",
                _ => envelope.MessageType,
            });
        }

        if (dispatcher is null)
        {
            Apply();
        }
        else
        {
            dispatcher.Invoke(Apply);
        }
    }

    private void ApplyOutcome(TaskOutcome outcome)
    {
        if (outcome.ArtifactId is not null)
        {
            Artifact = outcome.ArtifactId;
        }

        Status = outcome.State switch
        {
            TaskState.Succeeded => "成功",
            TaskState.Cancelled => "已取消",
            TaskState.Failed => $"失败：{outcome.ErrorCode ?? "未知错误"}",
            _ => outcome.State.ToString(),
        };
    }

    private void Cancel()
    {
        _supervisor?.Cancel();
        Status = "取消中…";
    }

    private void SetRunning(bool running)
    {
        _running = running;
        CommandManager.InvalidateRequerySuggested();
    }

    private void SetField<T>(ref T field, T value, [System.Runtime.CompilerServices.CallerMemberName] string? name = null)
    {
        if (EqualityComparer<T>.Default.Equals(field, value))
        {
            return;
        }

        field = value;
        OnPropertyChanged(name);
    }

    private void OnPropertyChanged(string? name)
    {
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
    }
}
