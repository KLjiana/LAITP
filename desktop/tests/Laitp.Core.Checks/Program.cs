using System.Diagnostics;
using System.IO.Compression;
using System.Text;
using System.Text.Json;
using Laitp.Core;

Console.OutputEncoding = Encoding.UTF8;

var failures = new List<string>();
void Check(string name, bool ok)
{
    Console.WriteLine((ok ? "PASS " : "FAIL ") + name);
    if (!ok) failures.Add(name);
}

string EnvelopeJson(
    string type,
    long sequence,
    string requestId = "req",
    string projectId = "proj",
    string taskId = "task",
    string artifactId = "null",
    string payload = "{}")
    => $"{{\"protocol_version\":\"1.0\",\"request_id\":\"{requestId}\",\"project_id\":\"{projectId}\","
       + $"\"task_id\":\"{taskId}\",\"message_type\":\"{type}\",\"sequence\":{sequence},"
       + $"\"artifact_id\":{artifactId},\"payload\":{payload}}}";

const string progressPayload = "{\"stage\":\"load\",\"completed\":0,\"total\":1}";
const string resultPayload =
    "{\"operation\":\"validate\",\"artifact\":{\"artifact_id\":\"art-1\","
    + "\"manifest_path\":\"manifest.json\","
    + "\"manifest_sha256\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\"}}";

// ---- 信封解析 ----
var progress = Envelope.Parse(EnvelopeJson("progress", 0, payload: progressPayload));
Check("解析 progress 信封", progress.MessageType == "progress" && progress.Sequence == 0);

var missingPayload = "{\"protocol_version\":\"1.0\",\"request_id\":\"req\",\"project_id\":\"proj\","
    + "\"task_id\":\"task\",\"message_type\":\"progress\",\"sequence\":0,\"artifact_id\":null}";
Check("缺少 payload 被拒绝", Throws(() => Envelope.Parse(missingPayload)));

Check("结果产物 ID 不一致被拒绝",
    Throws(() => Envelope.Parse(EnvelopeJson("result", 1, artifactId: "\"art-2\"", payload: resultPayload))));

// ---- 任务状态机 ----
var session = new TaskSession("req", "proj", "task");
Check("接受进度消息", session.Accept(Envelope.Parse(EnvelopeJson("progress", 0, payload: progressPayload))));
Check("接受结果消息", session.Accept(Envelope.Parse(EnvelopeJson("result", 1, artifactId: "\"art-1\"", payload: resultPayload))));
Check("结果后状态为成功", session.State == TaskState.Succeeded);
Check("迟到进度被拒绝",
    !session.Accept(Envelope.Parse(EnvelopeJson("progress", 2, payload: progressPayload)))
    && session.RejectionsSnapshot().Any(r => r.Code == "TASK_LATE_MESSAGE"));

var identity = new TaskSession("req", "proj", "task");
Check("归属不一致被拒绝",
    !identity.Accept(Envelope.Parse(EnvelopeJson("progress", 0, projectId: "other", payload: progressPayload)))
    && identity.RejectionsSnapshot().Any(r => r.Code == "TASK_IDENTITY_MISMATCH"));

var sequence = new TaskSession("req", "proj", "task");
sequence.Accept(Envelope.Parse(EnvelopeJson("progress", 1, payload: progressPayload)));
Check("序号倒退被拒绝",
    !sequence.Accept(Envelope.Parse(EnvelopeJson("progress", 0, payload: progressPayload)))
    && sequence.RejectionsSnapshot().Any(r => r.Code == "TASK_SEQUENCE_INVALID"));

var cancelled = new TaskSession("req", "proj", "task");
cancelled.MarkCancelled();
Check("取消后成功消息不改写状态",
    !cancelled.Accept(Envelope.Parse(EnvelopeJson("result", 0, artifactId: "\"art-1\"", payload: resultPayload)))
    && cancelled.State == TaskState.Cancelled && cancelled.ResultEnvelope is null);

// ---- 父进程与假工作进程 ----
var fixtures = Path.GetFullPath(Path.Combine(
    AppContext.BaseDirectory, "..", "..", "..", "..", "fixtures"));
var commandShell = Environment.GetEnvironmentVariable("ComSpec") ?? "cmd.exe";

TaskOutcome RunFixture(string script, string suffix, TimeSpan timeout)
{
    var supervisor = new TaskSupervisor(
        commandShell,
        new[] { "/c", Path.Combine(fixtures, script) },
        fixtures,
        "req-sup" + suffix,
        "proj-sup",
        "task-sup" + suffix);
    supervisor.Start();
    return supervisor.WaitForExit(timeout);
}

var okOutcome = RunFixture("ok_worker.cmd", "-ok", TimeSpan.FromSeconds(30));
Check("父进程成功终态", okOutcome.State == TaskState.Succeeded && okOutcome.ArtifactId == "art-sup");
Check("父进程退出码为 0", okOutcome.ExitCode == 0);
Check("父进程未记录拒绝", okOutcome.Rejections.Count == 0);
Check("父进程保存进度", okOutcome.Progress.Count == 1);

var exitOutcome = RunFixture("exit_worker.cmd", "-exit", TimeSpan.FromSeconds(30));
Check("未发终态退出判为失败",
    exitOutcome.State == TaskState.Failed && exitOutcome.ErrorCode == "TASK_CHILD_EXITED");
Check("保留子进程退出码", exitOutcome.ExitCode == 3);

var slow = new TaskSupervisor(
    commandShell,
    new[] { "/c", Path.Combine(fixtures, "slow_worker.cmd") },
    fixtures,
    "req-sup-slow",
    "proj-sup",
    "task-sup-slow");
using var firstMessage = new ManualResetEventSlim(false);
slow.MessageReceived += _ => firstMessage.Set();
slow.Start();
var received = firstMessage.Wait(TimeSpan.FromSeconds(15));
var cancelledOutcome = new TaskOutcome(TaskState.Running, null, null, Array.Empty<string>(),
    Array.Empty<Rejection>(), null, string.Empty);
if (received && slow.Cancel())
{
    cancelledOutcome = slow.WaitForExit(TimeSpan.FromSeconds(15));
}

Check("取消慢速任务", received && cancelledOutcome.State == TaskState.Cancelled);
Check("取消后无结果", cancelledOutcome.Result is null);

// ---- 工作区定位 ----
var repositoryRoot = WorkspaceLocator.FindRepositoryRoot(AppContext.BaseDirectory);
Check("定位仓库根目录", repositoryRoot is not null &&
    Directory.Exists(Path.Combine(repositoryRoot, "backend", "runtime")));
Console.WriteLine("仓库：" + (repositoryRoot ?? "（未找到）"));
Console.WriteLine("Python：" + (repositoryRoot is null
    ? "（未知）"
    : WorkspaceLocator.FindPython(repositoryRoot) ?? "（未找到 .venv）"));

// ---- 项目文件 ----
string ProjectJson(
    string classesJson = "[\"a\",\"b\"]",
    string modelsJson = "[]",
    string currentId = "null")
    => $"{{\"project_format\":\"1.0\",\"project_id\":\"proj-x\",\"name\":\"x\","
       + "\"task\":\"image_classification\",\"created_at\":\"2026-11-17T10:00:00+08:00\","
       + "\"updated_at\":\"2026-11-17T10:00:00+08:00\","
       + $"\"classes\":{classesJson},\"dataset_manifest\":null,"
       + $"\"models\":{modelsJson},\"current_model_artifact_id\":{currentId}}}";

var projectFixture = Path.Combine(fixtures, "project.json");
var projectDocument = ProjectDocument.Load(projectFixture);
Check("解析项目文件",
    projectDocument.Name == "测试项目" && projectDocument.Classes.Count == 3);
Check("读取当前模型", projectDocument.CurrentModel()?.ArtifactId == "art-fixture-0001");
Check("定位当前模型目录",
    projectDocument.CurrentModelDirectory() == "exports/art-fixture-0001/model-package");
Check("项目重复类别被拒绝",
    ThrowsProject(() => ProjectDocument.Parse(ProjectJson(classesJson: "[\"a\",\"a\"]"))));
Check("项目绝对模型路径被拒绝",
    ThrowsProject(() => ProjectDocument.Parse(ProjectJson(
        modelsJson: "[{\"artifact_id\":\"art-1\",\"kind\":\"export\","
                    + "\"path\":\"/abs/manifest.json\",\"sha256\":\""
                    + new string('a', 64)
                    + "\",\"created_at\":\"2026-11-17T10:00:00+08:00\"}]"))));
Check("项目当前模型不存在被拒绝",
    ThrowsProject(() => ProjectDocument.Parse(ProjectJson(currentId: "\"art-missing\""))));
Check("项目未知模型类型被拒绝",
    ThrowsProject(() => ProjectDocument.Parse(ProjectJson(
        modelsJson: "[{\"artifact_id\":\"art-1\",\"kind\":\"zip\","
                    + "\"path\":\"m.json\",\"sha256\":\""
                    + new string('a', 64)
                    + "\",\"created_at\":\"2026-11-17T10:00:00+08:00\"}]"))));

// ---- 训练报告 ----
var reportFixture = Path.Combine(fixtures, "metrics.json");
var trainingReport = TrainingReport.Load(reportFixture);
Check("解析训练报告",
    trainingReport.Classes.Count == 3 && Math.Abs(trainingReport.Accuracy - 0.5) < 1e-9);
Check("统计误判样本", trainingReport.Misclassified().Count() == 1);

var reportJson = File.ReadAllText(reportFixture);
Check("训练报告矩阵维度被拒绝",
    ThrowsTrainingReport(() => TrainingReport.Parse(reportJson.Replace(
        "\"confusion_matrix\": [[1, 0, 0], [0, 0, 1], [0, 0, 0]]",
        "\"confusion_matrix\": [[1, 2], [3, 4]]"))));
Check("训练报告样本越界被拒绝",
    ThrowsTrainingReport(() => TrainingReport.Parse(reportJson.Replace(
        "\"predicted_class_id\": 2", "\"predicted_class_id\": 9"))));

// ---- 数据清单摘要 ----
var datasetFixture = Path.Combine(fixtures, "dataset-manifest.json");
var datasetSummary = DatasetSummary.Load(datasetFixture);
Check("解析数据清单",
    datasetSummary.Classes.Count == 2 && datasetSummary.Samples.Count == 3);
Check("按类别统计样本",
    datasetSummary.Count("水杯", "train") == 1
    && datasetSummary.Count("水杯", "test") == 1
    && datasetSummary.TotalFor("train") == 2);
var datasetJson = File.ReadAllText(datasetFixture);
Check("数据清单类别越界被拒绝",
    ThrowsDataset(() => DatasetSummary.Parse(datasetJson.Replace(
        "\"class_id\": 1", "\"class_id\": 9"))));
Check("数据清单未知划分被拒绝",
    ThrowsDataset(() => DatasetSummary.Parse(datasetJson.Replace(
        "\"split\": \"test\"", "\"split\": \"holdout\""))));

// ---- 样本列表 ----
var samplesFixture = Path.Combine(fixtures, "samples.json");
var sampleList = SampleList.Parse(File.ReadAllText(samplesFixture));
Check("解析样本列表", sampleList.Total == 2 && sampleList.Samples.Count == 2);
Check("样本显示名", sampleList.Samples[0].DisplayName.Contains("水杯"));
var samplesJson = File.ReadAllText(samplesFixture);
Check("样本类别名不一致被拒绝",
    ThrowsSamples(() => SampleList.Parse(samplesJson.Replace(
        "\"class_name\": \"书本\"", "\"class_name\": \"水杯\""))));
Check("样本未知划分被拒绝",
    ThrowsSamples(() => SampleList.Parse(samplesJson.Replace(
        "\"split\": \"test\"", "\"split\": \"val\""))));
Check("样本路径越界被拒绝",
    ThrowsSamples(() => SampleList.Parse(samplesJson.Replace(
        "images/水杯/batch-1/001.png", "../escape.png"))));

// ---- 数据检查报告 ----
var checkFixture = Path.Combine(fixtures, "dataset-check.json");
var checkJson = File.ReadAllText(checkFixture);
var checkReport = DatasetCheckReport.Parse(checkJson);
Check("解析数据检查报告", checkReport.Ok && checkReport.Issues.Count == 0);
Check("解析检查策略",
    checkReport.Policy is not null
    && !checkReport.Policy.RequireTestSplit
    && checkReport.Policy.MinTrainPerClass == 1);
var failedCheckJson = checkJson
    .Replace("\"ok\": true", "\"ok\": false")
    .Replace(
        "\"issues\": []",
        "\"issues\": [{\"code\":\"DATASET_CLASS_MISSING_IN_SPLIT\","
        + "\"stage\":\"semantics\",\"message\":\"类别缺少验证样本\","
        + "\"location\":\"samples\"}]");
var failedReport = DatasetCheckReport.Parse(failedCheckJson);
Check("数据检查问题项", !failedReport.Ok && failedReport.Issues.Count == 1
    && failedReport.Issues[0].Code == "DATASET_CLASS_MISSING_IN_SPLIT");
Check("检查未通过但无问题被拒绝",
    ThrowsCheck(() => DatasetCheckReport.Parse(
        checkJson.Replace("\"ok\": true", "\"ok\": false"))));
Check("检查策略负数下限被拒绝",
    ThrowsCheck(() => DatasetCheckReport.Parse(
        checkJson.Replace("\"min_train_per_class\": 1", "\"min_train_per_class\": -1"))));

// ---- 训练历史 ----
var runsFixture = Path.Combine(fixtures, "runs.json");
var runsJson = File.ReadAllText(runsFixture);
var trainingRuns = TrainingRunList.Parse(runsJson);
Check("解析训练历史", trainingRuns.Total == 2 && trainingRuns.Runs.Count == 2);
Check("训练历史显示名", trainingRuns.Runs[0].DisplayName.Contains("已登记"));
Check("训练历史数量不一致被拒绝",
    ThrowsRuns(() => TrainingRunList.Parse(runsJson.Replace("\"total\": 2", "\"total\": 3"))));
Check("训练历史准确率越界被拒绝",
    ThrowsRuns(() => TrainingRunList.Parse(runsJson.Replace(
        "\"accuracy\": 0.75", "\"accuracy\": 1.75"))));

// ---- 首次运行自检 ----
var selfTestOutput = Path.Combine(
    Path.GetTempPath(), $"laitp-self-test-{Guid.NewGuid():N}.json");
SelfTest.Run(selfTestOutput);
var selfTestReport = File.Exists(selfTestOutput)
    ? JsonSerializer.Deserialize<SelfTestReport>(File.ReadAllText(selfTestOutput))
    : null;
Check("首次运行自检生成报告",
    selfTestReport is not null && selfTestReport.Checks.Count >= 2);
Check("自检包含仓库与 Python 检查",
    selfTestReport is not null
    && selfTestReport.Checks.Any(item => item.Name == "repository_root" && item.Ok)
    && selfTestReport.Checks.Any(item => item.Name == "python"));
var selfTestChecks = SelfTest.RunChecks();
Check("自检可直接返回报告",
    selfTestChecks.Checks.Count >= 2
    && selfTestChecks.Checks.Any(item => item.Name == "repository_root"));
var recentAdded = RecentProjects.Add(new[] { "b.json", "a.json" }, "a.json", max: 2);
Check("最近项目去重并置于首位",
    recentAdded.Count == 2
    && recentAdded[0] == "a.json"
    && recentAdded[1] == "b.json");
var recentFile = System.IO.Path.Combine(
    System.IO.Path.GetTempPath(), $"laitp-recent-{Guid.NewGuid():N}.json");
RecentProjects.Save(recentFile, new[] { "a.json", "b.json", "a.json" });
var recentLoaded = RecentProjects.Load(recentFile);
Check("最近项目保存与读取", recentLoaded.SequenceEqual(new[] { "a.json", "b.json" }));
File.Delete(recentFile);
Check("最近项目缺失文件返回空列表",
    RecentProjects.Load(System.IO.Path.Combine(
        System.IO.Path.GetTempPath(), $"missing-{Guid.NewGuid():N}.json")).Count == 0);
var copySource = System.IO.Path.Combine(
    System.IO.Path.GetTempPath(), $"laitp-copy-src-{Guid.NewGuid():N}");
var copyTarget = System.IO.Path.Combine(
    System.IO.Path.GetTempPath(), $"laitp-copy-dst-{Guid.NewGuid():N}");
System.IO.Directory.CreateDirectory(System.IO.Path.Combine(copySource, "data"));
System.IO.File.WriteAllText(
    System.IO.Path.Combine(copySource, "data", "x.txt"), "content");
ProjectCopy.CopyDirectory(copySource, copyTarget);
Check("项目目录复制",
    System.IO.File.ReadAllText(
        System.IO.Path.Combine(copyTarget, "data", "x.txt")) == "content");
var copyRejected = false;
try
{
    ProjectCopy.CopyDirectory(copySource, copyTarget);
}
catch (InvalidOperationException)
{
    copyRejected = true;
}
Check("项目复制拒绝非空目标", copyRejected);
System.IO.Directory.Delete(copySource, recursive: true);
System.IO.Directory.Delete(copyTarget, recursive: true);

// ---- 项目归档 ----
var archiveRoot = System.IO.Path.Combine(
    System.IO.Path.GetTempPath(), $"laitp-archive-{Guid.NewGuid():N}");
var archiveSource = System.IO.Path.Combine(archiveRoot, "source");
System.IO.Directory.CreateDirectory(System.IO.Path.Combine(archiveSource, "data"));
var archiveProjectJson = "{\"project_format\":\"1.0\",\"project_id\":\"proj-archive\","
    + "\"name\":\"存档测试\",\"task\":\"image_classification\","
    + "\"classes\":[\"a\",\"b\"],\"models\":[],\"current_model_artifact_id\":null}";
System.IO.File.WriteAllText(
    System.IO.Path.Combine(archiveSource, "project.json"), archiveProjectJson);
System.IO.File.WriteAllText(
    System.IO.Path.Combine(archiveSource, "data", "x.txt"), "archive-content");
var archiveZip = System.IO.Path.Combine(archiveRoot, "backup.zip");
ProjectArchive.Export(archiveSource, archiveZip);
ProjectArchive.Export(archiveSource, archiveZip); // 已存在的归档应可安全覆盖
bool archiveHasProject;
using (var exportedBundle = ZipFile.OpenRead(archiveZip))
{
    archiveHasProject = exportedBundle.GetEntry("project.json") is not null
        && exportedBundle.GetEntry("data/x.txt") is not null;
}

Check("项目归档导出包含 project.json", archiveHasProject);

var archiveImported = System.IO.Path.Combine(archiveRoot, "restored");
ProjectArchive.Import(archiveZip, archiveImported);
Check("项目归档导出导入往返",
    System.IO.File.Exists(System.IO.Path.Combine(archiveImported, "project.json"))
    && System.IO.File.ReadAllText(
        System.IO.Path.Combine(archiveImported, "project.json")) == archiveProjectJson
    && System.IO.File.ReadAllText(
        System.IO.Path.Combine(archiveImported, "data", "x.txt")) == "archive-content");

Check("项目归档导入拒绝非空目标",
    ThrowsArchive(() => ProjectArchive.Import(archiveZip, archiveImported)));

var incompleteArchive = System.IO.Path.Combine(archiveRoot, "incomplete.zip");
using (var incompleteBundle = ZipFile.Open(incompleteArchive, ZipArchiveMode.Create))
{
    using var incompleteWriter = new System.IO.StreamWriter(
        incompleteBundle.CreateEntry("readme.txt").Open());
    incompleteWriter.Write("缺少 project.json");
}

var incompleteTarget = System.IO.Path.Combine(archiveRoot, "incomplete-target");
var slipArchive = System.IO.Path.Combine(archiveRoot, "slip.zip");
using (var slipBundle = ZipFile.Open(slipArchive, ZipArchiveMode.Create))
{
    slipBundle.CreateEntry("../escape.txt");
    using var slipWriter = new System.IO.StreamWriter(
        slipBundle.CreateEntry("project.json").Open());
    slipWriter.Write("{}");
}

var slipTarget = System.IO.Path.Combine(archiveRoot, "slip-target");
Check("项目归档导入拒绝缺少 project.json 或 .. 路径的归档",
    ThrowsArchive(() => ProjectArchive.Import(incompleteArchive, incompleteTarget))
    && !System.IO.Directory.Exists(incompleteTarget)
    && ThrowsArchive(() => ProjectArchive.Import(slipArchive, slipTarget))
    && !System.IO.Directory.Exists(slipTarget)
    && !System.IO.File.Exists(System.IO.Path.Combine(archiveRoot, "escape.txt")));
System.IO.Directory.Delete(archiveRoot, recursive: true);

Check("摄像头权限错误提示",
    CameraErrors.Describe(unchecked((int)0x80070005), "denied").Contains("隐私"));
Check("摄像头占用错误提示",
    CameraErrors.Describe(unchecked((int)0x800700AA), "busy").Contains("占用"));
Check("摄像头缺失错误提示",
    CameraErrors.Describe(unchecked((int)0x80070490), "missing").Contains("未找到"));
Check("摄像头未知错误包含 HRESULT",
    CameraErrors.Describe(unchecked((int)0x80004005), "unknown").Contains("0x80004005"));
File.Delete(selfTestOutput);

// ---- 可选：用真实 Python 工作进程做集成检查 ----
string? packagePath = null;
string? imagePath = null;
for (var index = 0; index < args.Length; index++)
{
    if (args[index] == "--package" && index + 1 < args.Length) packagePath = args[++index];
    if (args[index] == "--image" && index + 1 < args.Length) imagePath = args[++index];
}

if (packagePath is not null && imagePath is not null)
{
    var python = repositoryRoot is null ? null : WorkspaceLocator.FindPython(repositoryRoot);
    if (python is null || repositoryRoot is null)
    {
        Check("真实工作进程集成（需要 .venv Python）", false);
    }
    else
    {
        var supervisor = new TaskSupervisor(
            python,
            new[]
            {
                "-m", "backend.runtime.worker", "predict",
                "--package", packagePath,
                "--image", imagePath,
                "--request-id", "req-checks-predict",
                "--project-id", "proj-checks",
                "--task-id", "task-checks-predict",
            },
            repositoryRoot,
            "req-checks-predict",
            "proj-checks",
            "task-checks-predict");
        supervisor.Start();
        var outcome = supervisor.WaitForExit(TimeSpan.FromMinutes(2));
        Check("真实工作进程集成成功",
            outcome.State == TaskState.Succeeded && outcome.ArtifactId is not null);
        if (outcome.State != TaskState.Succeeded)
        {
            Console.WriteLine("错误码：" + (outcome.ErrorCode ?? "（无）"));
            Console.WriteLine("标准错误：" + outcome.StderrTail);
        }
    }
}

Console.WriteLine();
Console.WriteLine(failures.Count == 0
    ? "全部检查通过"
    : $"失败 {failures.Count} 项：{string.Join("，", failures)}");
return failures.Count == 0 ? 0 : 1;

static bool Throws(Action action)
{
    try
    {
        action();
        return false;
    }
    catch (ProtocolException)
    {
        return true;
    }
}

static bool ThrowsProject(Action action)
{
    try
    {
        action();
        return false;
    }
    catch (ProjectDocumentException)
    {
        return true;
    }
}

static bool ThrowsTrainingReport(Action action)
{
    try
    {
        action();
        return false;
    }
    catch (TrainingReportException)
    {
        return true;
    }
}

static bool ThrowsDataset(Action action)
{
    try
    {
        action();
        return false;
    }
    catch (DatasetSummaryException)
    {
        return true;
    }
}

static bool ThrowsSamples(Action action)
{
    try
    {
        action();
        return false;
    }
    catch (SampleListException)
    {
        return true;
    }
}

static bool ThrowsCheck(Action action)
{
    try
    {
        action();
        return false;
    }
    catch (DatasetCheckException)
    {
        return true;
    }
}

static bool ThrowsRuns(Action action)
{
    try
    {
        action();
        return false;
    }
    catch (TrainingRunListException)
    {
        return true;
    }
}

static bool ThrowsArchive(Action action)
{
    try
    {
        action();
        return false;
    }
    catch (InvalidOperationException)
    {
        return true;
    }
}
