# 解压后一键验收：包内自检 + 窗口自检 + 启动耗时。
# 用法（在解压目录内）：powershell -ExecutionPolicy Bypass -File scripts\run_acceptance.ps1
param(
    [string]$Exe = "desktop/app/Laitp.Desktop.exe",
    [switch]$SkipSmoke,
    [switch]$SkipMeasure,
    [switch]$IncludeFlow,
    [switch]$IncludeExtended,
    [string]$Output = "acceptance-run.json"
)

$ErrorActionPreference = "Stop"
# 统一控制台/管道编码：避免中文 Windows 的 CP936 控制台把 Python 的 UTF-8 JSON
# 输出按 GBK 解码，导致 ConvertFrom-Json 解析失败（数据体检/历史汇总/严格验收）。
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {
    # 无控制台（服务/计划任务）时忽略；后续步骤会按实际情况报告失败。
}
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root "python/python.exe"
$artifacts = Join-Path $root "artifacts"
if (-not (Test-Path $artifacts)) { New-Item -ItemType Directory -Path $artifacts | Out-Null }

# 包身份：读取包根的 manifest.json，记录 format、created_at、组件数、文件数、总字节
# 与清单自身 SHA-256，便于把验收记录与具体分发包对应。manifest 缺失或损坏时只记
# warning 并把 bundle 置为 $null，不改变验收步骤与判定逻辑。
$manifestPath = Join-Path $root "manifest.json"
$bundle = $null
$bundleComponentCount = 0
$bundleWarnings = @()
if (Test-Path $manifestPath) {
    try {
        $manifestData = Get-Content $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $hasFormat = $null -ne $manifestData.PSObject.Properties["format"]
        $hasComponents = $null -ne $manifestData.PSObject.Properties["components"]
        if (-not $hasFormat -or -not $hasComponents) {
            throw "缺少 format 或 components 字段"
        }
        if ([string]::IsNullOrWhiteSpace([string]$manifestData.format)) {
            throw "format 字段为空"
        }
        $components = @($manifestData.components)
        if ($components.Count -eq 0) {
            throw "components 为空"
        }
        $fileCount = 0
        $totalBytes = [int64]0
        foreach ($component in $components) {
            if ($null -eq $component) { continue }
            $files = @($component.files)
            $fileCount += $files.Count
            foreach ($file in $files) {
                if ($null -ne $file) { $totalBytes += [int64]$file.size }
            }
        }
        $manifestSha256 = (Get-FileHash -Path $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
        $bundle = [ordered]@{
            format = [string]$manifestData.format
            created_at = [string]$manifestData.created_at
            file_count = [int]$fileCount
            total_bytes = [int64]$totalBytes
            manifest_sha256 = $manifestSha256
        }
        $bundleComponentCount = $components.Count
    }
    catch {
        $bundle = $null
        $bundleComponentCount = 0
        $bundleWarnings += "读取 manifest.json 失败，包身份不可用：$($_.Exception.Message)"
    }
}
else {
    $bundleWarnings += "未找到 manifest.json（$manifestPath），包身份不可用"
}
foreach ($bundleWarning in $bundleWarnings) { Write-Warning $bundleWarning }

$result = [ordered]@{
    root = $root
    python = $python
    exe = $Exe
    bundle = $bundle
    warnings = @($bundleWarnings)
    steps = @()
    report = $null
    ok = $false
    error = ""
}

# 预检：只清理本包目录下的残留桌面/后端进程，避免上一次失败运行的
# 窗口或文件占用干扰本次界面自动化（不影响其它程序）。
$staleProcesses = @()
try {
    $rootPrefix = $root.TrimEnd('\') + '\'
    foreach ($process in @(Get-Process -Name "Laitp.Desktop" -ErrorAction SilentlyContinue)) {
        try {
            $processPath = $process.Path
            if ($processPath -and $processPath.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
                Stop-Process -Id $process.Id -Force -ErrorAction Stop
                $staleProcesses += "Laitp.Desktop($($process.Id))"
            }
        }
        catch { }
    }
    foreach ($process in @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue)) {
        try {
            $commandLine = [string]$process.CommandLine
            if ($commandLine -and $commandLine.IndexOf($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
                Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
                $staleProcesses += "python($($process.ProcessId))"
            }
        }
        catch { }
    }
    if ($staleProcesses.Count -gt 0) {
        Start-Sleep -Milliseconds 800
        $staleMessage = "预检清理残留进程：" + ($staleProcesses -join "、")
        Write-Warning $staleMessage
        $result.warnings += $staleMessage
    }
}
catch {
    $result.warnings += "预检清理残留进程时出现异常：$($_.Exception.Message)"
}

function Add-Step {
    param([string]$Name, [string]$Status, [double]$Seconds, [string]$Detail)
    $script:result.steps += [ordered]@{
        name = $Name
        status = $Status
        seconds = [Math]::Round($Seconds, 2)
        detail = $Detail
    }
}

# Start-Process 的 -ArgumentList 数组按空格拼接、不会自动给含空格的元素加引号；
# 验收包常被解压到含中文/空格的目录（如“教学 平台 验收 …”），这里按 Windows
# 命令行规则逐项加双引号，保持与原 `& powershell -File …` 调用相同的参数语义。
function ConvertTo-PowerShellProcessArgument {
    param([string]$Value)
    if ([string]::IsNullOrEmpty($Value)) { return '""' }
    if ($Value.IndexOfAny([char[]]@(' ', "`t", '"')) -lt 0) { return $Value }
    $escaped = $Value -replace '(\\*)"', '$1$1\"'
    $escaped = $escaped -replace '(\\+)$', '$1$1'
    return '"' + $escaped + '"'
}

# 有界超时调用界面自动化脚本：用 Start-Process 启动子 powershell 并每 500 ms
# 轮询等待；超时用 taskkill /T /F 终止整棵进程树（含 WPF 窗口与后端 python），
# 返回统一结果对象。超时判失败（ExitCode=124）、记录 warning 并追加到
# $result.warnings，但后续步骤仍按原有依赖逻辑 skip/fail，不中断整个验收。
function Invoke-PowerShellScriptWithTimeout {
    param(
        [string]$ScriptPath,
        [string[]]$Arguments = @(),
        [int]$TimeoutSeconds = 420,
        [string]$Label = ""
    )
    $displayName = if ([string]::IsNullOrWhiteSpace($Label)) {
        Split-Path -Leaf $ScriptPath
    }
    else {
        $Label
    }
    $process = $null
    try {
        $startArguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $ScriptPath) +
            @($Arguments)
        $quotedArguments = @()
        foreach ($startArgument in $startArguments) {
            $quotedArguments += (ConvertTo-PowerShellProcessArgument ([string]$startArgument))
        }
        $process = Start-Process -FilePath "powershell" -ArgumentList $quotedArguments `
            -PassThru -NoNewWindow
        # Windows PowerShell 5.1 的 Start-Process -PassThru（未加 -Wait）在进程退出后
        # 读取 .ExitCode 可能得到 $null；启动后立即读取一次 .Handle 让 Process 对象
        # 持有进程句柄，正常结束才能取到真实退出码。
        try { $null = $process.Handle } catch { }

        $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
        while ((-not $process.HasExited) -and ([DateTime]::UtcNow -lt $deadline)) {
            Start-Sleep -Milliseconds 500
        }
        if (-not $process.HasExited) {
            $timeoutMessage = "$displayName 超时（${TimeoutSeconds}s），已终止进程树（PID $($process.Id)）"
            try {
                & taskkill /T /F /PID $process.Id 2>$null | Out-Null
            }
            catch {
                $timeoutMessage += "；taskkill 异常：$($_.Exception.Message)"
            }
            try { [void]$process.WaitForExit(5000) } catch { }
            Write-Warning $timeoutMessage
            if ($null -ne $script:result) { $script:result.warnings += $timeoutMessage }
            return [pscustomobject]@{ ExitCode = 124; TimedOut = $true }
        }

        $exitCode = $process.ExitCode
        if ($null -eq $exitCode) {
            # 兜底：句柄未缓存导致退出码不可读时再等待重试；仍取不到按失败（1）
            # 处理并记录 warning，避免把未知退出码误判为通过。
            try { $process.WaitForExit() } catch { }
            try { $exitCode = $process.ExitCode } catch { $exitCode = $null }
            if ($null -eq $exitCode) {
                $unknownMessage = "$displayName 已结束但无法获取退出码，按失败（1）处理"
                Write-Warning $unknownMessage
                if ($null -ne $script:result) { $script:result.warnings += $unknownMessage }
                $exitCode = 1
            }
        }
        return [pscustomobject]@{ ExitCode = [int]$exitCode; TimedOut = $false }
    }
    catch {
        if ($null -ne $process) {
            try {
                if (-not $process.HasExited) {
                    & taskkill /T /F /PID $process.Id 2>$null | Out-Null
                }
            }
            catch { }
        }
        $failureMessage = "$displayName 启动或等待失败：$($_.Exception.Message)"
        Write-Warning $failureMessage
        if ($null -ne $script:result) { $script:result.warnings += $failureMessage }
        return [pscustomobject]@{ ExitCode = 1; TimedOut = $false }
    }
    finally {
        if ($null -ne $process) {
            try { $process.Dispose() } catch { }
        }
    }
}

# 界面步骤失败自动重试：只重试一次。偶发 UI 自动化超时/失败（窗口未就绪、
# UIA 焦点抖动等）通常重跑即可通过；因此保持 11 个步骤与判定口径不变，仅在
# 首次失败（非 0 退出码或超时）后等待 DelaySeconds 再执行一次。首次失败信息
# 留在返回值里，由调用方写入 detail 与 warnings，便于目标机记录“偶发但通过”。
function Invoke-UiStepWithRetry {
    param(
        [string]$ScriptPath,
        [string[]]$Arguments = @(),
        [int]$TimeoutSeconds = 420,
        [string]$Label = "",
        [int]$DelaySeconds = 2
    )
    $first = Invoke-PowerShellScriptWithTimeout `
        -ScriptPath $ScriptPath -Arguments $Arguments `
        -TimeoutSeconds $TimeoutSeconds -Label $Label
    $firstFailed = ($first.ExitCode -ne 0) -or [bool]$first.TimedOut
    $retryResult = [pscustomobject]@{
        ExitCode      = $first.ExitCode
        TimedOut      = [bool]$first.TimedOut
        Attempts      = 1
        FirstExitCode = $first.ExitCode
        FirstTimedOut = [bool]$first.TimedOut
        Retried       = $false
    }
    if (-not $firstFailed) { return $retryResult }

    if ($DelaySeconds -gt 0) { Start-Sleep -Seconds $DelaySeconds }
    $second = Invoke-PowerShellScriptWithTimeout `
        -ScriptPath $ScriptPath -Arguments $Arguments `
        -TimeoutSeconds $TimeoutSeconds -Label $Label
    $retryResult.ExitCode = $second.ExitCode
    $retryResult.TimedOut = [bool]$second.TimedOut
    $retryResult.Attempts = 2
    $retryResult.Retried = $true
    return $retryResult
}

# 把重试结果转成 detail 后缀与 warning：重试后通过时保留首次失败原因；两次
# 均失败时同时记录最终与首次原因。未发生重试（首次即通过）时返回 $null，
# 调用方保持原有 detail/warning 不变。
function Get-UiRetryNote {
    param(
        $Run,
        [int]$TimeoutSeconds,
        [bool]$Passed,
        [string]$FailureReason = ""
    )
    if (-not $Run.Retried) { return $null }
    $firstReason = if ($Run.FirstTimedOut) {
        "超时 ${TimeoutSeconds} s"
    }
    else {
        "退出码 $($Run.FirstExitCode)"
    }
    if ($Passed) {
        return [pscustomobject]@{
            DetailSuffix = "（首次失败：$firstReason；第 2 次通过）"
            Warning      = "首次失败，重试后通过（首次失败：$firstReason）"
        }
    }
    $finalReason = if (-not [string]::IsNullOrWhiteSpace($FailureReason)) {
        $FailureReason
    }
    elseif ($Run.TimedOut) {
        "超时 ${TimeoutSeconds} s"
    }
    else {
        "退出码 $($Run.ExitCode)"
    }
    return [pscustomobject]@{
        DetailSuffix = "（已重试 2 次均失败：最终$finalReason；首次失败：$firstReason）"
        Warning      = "重试后仍失败（最终$finalReason；首次失败：$firstReason）"
    }
}

try {
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    & $python (Join-Path $root "scripts/verify_offline_bundle.py") --extracted $root
    $watch.Stop()
    $checkOk = $LASTEXITCODE -eq 0
    Add-Step -Name "包内自检" -Status ($(if ($checkOk) { "pass" } else { "fail" })) -Seconds $watch.Elapsed.TotalSeconds -Detail "verify_offline_bundle --extracted"

    if (-not $SkipSmoke) {
        $smokeOut = Join-Path $artifacts "ui-smoke-acceptance.json"
        $watch = [System.Diagnostics.Stopwatch]::StartNew()
        $smokeRun = Invoke-UiStepWithRetry `
            -ScriptPath (Join-Path $root "scripts/ui_smoke.ps1") `
            -Arguments @("-Exe", $Exe, "-LaitpHome", $root, "-LaitpPython", $python, "-Output", $smokeOut) `
            -TimeoutSeconds 240 -Label "ui_smoke.ps1"
        $watch.Stop()
        $smokeOk = $smokeRun.ExitCode -eq 0
        $smokeDetail = if ($smokeRun.TimedOut) { "$smokeOut（超时 240 s，已终止进程树）" } else { $smokeOut }
        $smokeRetry = Get-UiRetryNote -Run $smokeRun -TimeoutSeconds 240 -Passed $smokeOk
        if ($null -ne $smokeRetry) {
            $smokeDetail = "$smokeDetail$($smokeRetry.DetailSuffix)"
            $result.warnings += "步骤 窗口自检 $($smokeRetry.Warning)"
        }
        Add-Step -Name "窗口自检" -Status ($(if ($smokeOk) { "pass" } else { "fail" })) -Seconds $watch.Elapsed.TotalSeconds -Detail $smokeDetail
    }
    else {
        Add-Step -Name "窗口自检" -Status "skip" -Seconds 0 -Detail "已指定 -SkipSmoke"
    }

    if (-not $SkipMeasure) {
        $measureOut = Join-Path $artifacts "startup-acceptance.json"
        $watch = [System.Diagnostics.Stopwatch]::StartNew()
        $measureRun = Invoke-UiStepWithRetry `
            -ScriptPath (Join-Path $root "scripts/measure_startup.ps1") `
            -Arguments @("-Exe", $Exe, "-LaitpHome", $root, "-LaitpPython", $python, "-Output", $measureOut) `
            -TimeoutSeconds 180 -Label "measure_startup.ps1"
        $watch.Stop()
        $measureOk = $measureRun.ExitCode -eq 0
        $measureDetail = if ($measureRun.TimedOut) { "$measureOut（超时 180 s，已终止进程树）" } else { $measureOut }
        $measureRetry = Get-UiRetryNote -Run $measureRun -TimeoutSeconds 180 -Passed $measureOk
        if ($null -ne $measureRetry) {
            $measureDetail = "$measureDetail$($measureRetry.DetailSuffix)"
            $result.warnings += "步骤 启动耗时 $($measureRetry.Warning)"
        }
        Add-Step -Name "启动耗时" -Status ($(if ($measureOk) { "pass" } else { "fail" })) -Seconds $watch.Elapsed.TotalSeconds -Detail $measureDetail
    }
    else {
        Add-Step -Name "启动耗时" -Status "skip" -Seconds 0 -Detail "已指定 -SkipMeasure"
    }

    if ($IncludeFlow) {
        $demo = Join-Path $root "acceptance-demo"
        if (Test-Path $demo) { Remove-Item -Recurse -Force $demo }
        New-Item -ItemType Directory -Path $demo | Out-Null
        $source = Join-Path $demo "source"
        $watch = [System.Diagnostics.Stopwatch]::StartNew()
        & $python (Join-Path $root "scripts/make_demo_dataset.py") --root $source --test
        $watch.Stop()
        $datasetOk = $LASTEXITCODE -eq 0
        Add-Step -Name "演示数据生成" -Status ($(if ($datasetOk) { "pass" } else { "fail" })) -Seconds $watch.Elapsed.TotalSeconds -Detail $source

        $createOut = Join-Path $artifacts "ui-create-import-acceptance.json"
        $watch = [System.Diagnostics.Stopwatch]::StartNew()
        $createRun = Invoke-UiStepWithRetry `
            -ScriptPath (Join-Path $root "scripts/ui_create_import.ps1") `
            -Arguments @(
                "-Exe", $Exe, "-LaitpHome", $root, "-LaitpPython", $python,
                "-SourceRoot", $source, "-ProjectParent", (Join-Path $demo "项目父目录"),
                "-TestSource", (Join-Path $demo "source-test"), "-Output", $createOut
            ) `
            -TimeoutSeconds 420 -Label "ui_create_import.ps1"
        $watch.Stop()
        $createOk = $false
        if ((Test-Path $createOut) -and ($createRun.ExitCode -eq 0)) {
            $createData = Get-Content $createOut -Raw -Encoding UTF8 | ConvertFrom-Json
            $createOk = [bool]$createData.ok
        }
        $createDetail = if ($createRun.TimedOut) { "$createOut（超时 420 s，已终止进程树）" } else { $createOut }
        $createFailReason = if (($createRun.ExitCode -eq 0) -and (-not $createOk)) {
            "退出码 0 但界面结果 ok=false 或输出缺失"
        }
        else { "" }
        $createRetry = Get-UiRetryNote -Run $createRun -TimeoutSeconds 420 -Passed $createOk `
            -FailureReason $createFailReason
        if ($null -ne $createRetry) {
            $createDetail = "$createDetail$($createRetry.DetailSuffix)"
            $result.warnings += "步骤 新项目与导入 $($createRetry.Warning)"
        }
        Add-Step -Name "新项目与导入" -Status ($(if ($createOk) { "pass" } else { "fail" })) -Seconds $watch.Elapsed.TotalSeconds -Detail $createDetail

        if ($createOk) {
            $flowProject = Join-Path $createData.project_root "project.json"
            $testImages = @(Get-ChildItem -Path (Join-Path $demo "source-test") -Recurse -Filter *.png | Sort-Object FullName)
            $flowOut = Join-Path $artifacts "ui-flow-acceptance.json"
            # 模型对比的示例包随离线包分发（bundle 内 demo/model-package）；只有
            # 目录与 manifest.json 都存在时才传入 -ComparePackage，否则不加该参数
            # 并在步骤详情里说明，避免旧包或裁剪包因缺示例包而失败。
            $comparePackage = Join-Path $root "demo/model-package"
            $compareAvailable =
                (Test-Path $comparePackage) -and
                (Test-Path (Join-Path $comparePackage "manifest.json"))
            $compareNote = if ($compareAvailable) {
                ""
            }
            else {
                "未提供 -ComparePackage：$comparePackage\manifest.json 不存在，跳过模型对比"
            }
            $flowArgs = @(
                "-Exe", $Exe,
                "-LaitpHome", $root,
                "-LaitpPython", $python,
                "-ProjectPath", $flowProject,
                "-ImagePath", $testImages[0].FullName,
                "-TrainPredict",
                "-Epochs", "3",
                "-BatchImagesDir", (Join-Path $demo "source-test"),
                "-Output", $flowOut
            )
            if ($compareAvailable) { $flowArgs += @("-ComparePackage", $comparePackage) }
            $watch = [System.Diagnostics.Stopwatch]::StartNew()
            $flowRun = Invoke-UiStepWithRetry `
                -ScriptPath (Join-Path $root "scripts/ui_flow.ps1") `
                -Arguments $flowArgs -TimeoutSeconds 600 -Label "ui_flow.ps1"
            $watch.Stop()
            $flowExit = $flowRun.ExitCode
            $flowData = $null
            if (Test-Path $flowOut) {
                try {
                    $flowData = Get-Content $flowOut -Raw -Encoding UTF8 | ConvertFrom-Json
                }
                catch {
                    $flowData = $null
                }
            }
            $flowOk = ($flowExit -eq 0) -and ($null -ne $flowData) -and [bool]$flowData.ok
            # 批量预测与模型对比是界面流程内的必选扩展动作，只把状态摘要附在
            # “训练与预测”步骤详情里（如 batch=…；compare=…），不新增步骤。
            $flowSummary = @()
            if ($null -ne $flowData) {
                if (-not [string]::IsNullOrWhiteSpace([string]$flowData.batch_status)) {
                    $flowSummary += "batch=$($flowData.batch_status)"
                }
                if (-not [string]::IsNullOrWhiteSpace([string]$flowData.compare_status)) {
                    $flowSummary += "compare=$($flowData.compare_status)"
                }
            }
            if ($compareNote) { $flowSummary += $compareNote }
            $flowDetail = $flowOut
            if ($flowSummary.Count -gt 0) {
                $flowDetail = "$flowOut（$($flowSummary -join '；')）"
            }
            if ($flowRun.TimedOut) {
                $flowDetail = "$flowOut（超时 600 s，已终止进程树）"
            }
            $flowFailReason = if (($flowExit -eq 0) -and (-not $flowOk)) {
                "退出码 0 但流程结果 ok=false 或输出缺失"
            }
            else { "" }
            $flowRetry = Get-UiRetryNote -Run $flowRun -TimeoutSeconds 600 -Passed $flowOk `
                -FailureReason $flowFailReason
            if ($null -ne $flowRetry) {
                $flowDetail = "$flowDetail$($flowRetry.DetailSuffix)"
                $result.warnings += "步骤 训练与预测 $($flowRetry.Warning)"
            }
            Add-Step -Name "训练与预测" -Status ($(if ($flowOk) { "pass" } else { "fail" })) -Seconds $watch.Elapsed.TotalSeconds -Detail $flowDetail
        }
        else {
            Add-Step -Name "训练与预测" -Status "skip" -Seconds 0 -Detail "前置步骤失败"
        }
    }

    if ($IncludeExtended) {
        $restoreOut = Join-Path $artifacts "ui-restore-acceptance.json"
        $restoreProjectFile = $null
        if (-not $IncludeFlow) {
            Add-Step -Name "保存与恢复" -Status "skip" -Seconds 0 -Detail "需同时指定 -IncludeFlow"
        }
        else {
            $watch = [System.Diagnostics.Stopwatch]::StartNew()
            $restoreRun = Invoke-UiStepWithRetry `
                -ScriptPath (Join-Path $root "scripts/ui_restore.ps1") `
                -Arguments @(
                    "-Exe", $Exe, "-LaitpHome", $root, "-LaitpPython", $python,
                    "-SourceRoot", (Join-Path $demo "source"),
                    "-ProjectParent", (Join-Path $demo "恢复项目父目录"), "-Output", $restoreOut
                ) `
                -TimeoutSeconds 480 -Label "ui_restore.ps1"
            $watch.Stop()
            $restoreOk = $false
            if ((Test-Path $restoreOut) -and ($restoreRun.ExitCode -eq 0)) {
                $restoreData = Get-Content $restoreOut -Raw -Encoding UTF8 | ConvertFrom-Json
                $restoreOk = [bool]$restoreData.ok
            }
            $restoreDetail = if ($restoreRun.TimedOut) { "$restoreOut（超时 480 s，已终止进程树）" } else { $restoreOut }
            $restoreFailReason = if (($restoreRun.ExitCode -eq 0) -and (-not $restoreOk)) {
                "退出码 0 但界面结果 ok=false 或输出缺失"
            }
            else { "" }
            $restoreRetry = Get-UiRetryNote -Run $restoreRun -TimeoutSeconds 480 -Passed $restoreOk `
                -FailureReason $restoreFailReason
            if ($null -ne $restoreRetry) {
                $restoreDetail = "$restoreDetail$($restoreRetry.DetailSuffix)"
                $result.warnings += "步骤 保存与恢复 $($restoreRetry.Warning)"
            }
            Add-Step -Name "保存与恢复" -Status ($(if ($restoreOk) { "pass" } else { "fail" })) -Seconds $watch.Elapsed.TotalSeconds -Detail $restoreDetail

            # 数据体检针对保存恢复流程生成的项目；项目目录名由 ui_restore.ps1
            # 默认（含空格），从 ui-restore-acceptance.json 的 project_root 读取，
            # 避免在验收脚本里重复硬编码项目名。
            $restoreProjectRoot = $null
            if (Test-Path $restoreOut) {
                try {
                    $restoreData = Get-Content $restoreOut -Raw -Encoding UTF8 | ConvertFrom-Json
                    if (-not [string]::IsNullOrWhiteSpace([string]$restoreData.project_root)) {
                        $restoreProjectRoot = [string]$restoreData.project_root
                    }
                }
                catch {
                    $restoreProjectRoot = $null
                }
            }
            if ($restoreProjectRoot) {
                $candidate = Join-Path $restoreProjectRoot "project.json"
                if (Test-Path $candidate) { $restoreProjectFile = $candidate }
            }
        }

        # 批量历史汇总优先使用 flow 项目：ui_flow.ps1 的批量预测会把结果写入
        # 项目 runs/batch-predict-*.json，可覆盖“非空历史”；flow 项目不可用时
        # 回退保存恢复项目（其 runs/ 通常为空，只验证空历史的契约行为）。
        $historyProjectFile = $null
        $historyProjectLabel = ""
        $flowCreateOut = Join-Path $artifacts "ui-create-import-acceptance.json"
        if ($IncludeFlow -and (Test-Path $flowCreateOut)) {
            try {
                $flowCreateData = Get-Content $flowCreateOut -Raw -Encoding UTF8 | ConvertFrom-Json
                $flowProjectRoot = [string]$flowCreateData.project_root
                if (-not [string]::IsNullOrWhiteSpace($flowProjectRoot)) {
                    $candidate = Join-Path $flowProjectRoot "project.json"
                    if (Test-Path $candidate) { $historyProjectFile = $candidate }
                }
            }
            catch {
                $historyProjectFile = $null
            }
        }
        if ($historyProjectFile) {
            $historyProjectLabel = "flow 项目"
        }
        elseif ($restoreProjectFile) {
            $historyProjectFile = $restoreProjectFile
            $historyProjectLabel = "保存恢复项目"
        }

        if (-not $restoreProjectFile) {
            $skipDetail = if (-not $IncludeFlow) {
                "需同时指定 -IncludeFlow"
            }
            else {
                "未取得保存恢复项目（ui-restore-acceptance.json 缺少可用的 project_root 或 project.json 不存在）"
            }
            Add-Step -Name "数据体检" -Status "skip" -Seconds 0 -Detail $skipDetail
        }
        else {
            # 数据体检：读取项目数据清单与 data/ 目录，输出 Markdown 报告与逐样本 CSV。
            $reportPath = Join-Path $demo "dataset-report.md"
            $reportCsv = Join-Path $demo "dataset-samples.csv"
            $reportErr = Join-Path $artifacts "dataset-report-acceptance.stderr.txt"
            $watch = [System.Diagnostics.Stopwatch]::StartNew()
            $reportRaw = (& $python (Join-Path $root "scripts/dataset_report.py") `
                --project $restoreProjectFile --output $reportPath --csv $reportCsv 2>$reportErr | Out-String)
            $watch.Stop()
            $reportExit = $LASTEXITCODE
            $reportOk = $false
            $reportDetail = $reportPath
            try {
                $reportData = $reportRaw | ConvertFrom-Json
                $reportOk = [bool]$reportData.ok -and (Test-Path $reportPath)
                if (-not $reportOk) {
                    $reportDetail = "$reportPath（退出码 $reportExit，ok=$([bool]$reportData.ok)，报告文件存在=$(Test-Path $reportPath)，详见 $reportErr）"
                }
            }
            catch {
                $reportDetail = "$reportPath（退出码 $reportExit，无法解析脚本 JSON 输出，详见 $reportErr）"
            }
            Add-Step -Name "数据体检" -Status ($(if ($reportOk) { "pass" } else { "fail" })) -Seconds $watch.Elapsed.TotalSeconds -Detail $reportDetail
        }

        if (-not $historyProjectFile) {
            $historySkipDetail = if (-not $IncludeFlow) {
                "需同时指定 -IncludeFlow"
            }
            else {
                "未取得可用项目（flow 项目与保存恢复项目均不可用）"
            }
            Add-Step -Name "批量历史汇总" -Status "skip" -Seconds 0 -Detail $historySkipDetail
        }
        else {
            # 批量历史汇总：扫描项目 runs/batch-predict-*.json；没有历史时脚本
            # 仍返回 ok:true（汇总为空），验收只按脚本契约检查 ok。
            $historyPath = Join-Path $demo "batch-history.md"
            $historyCsv = Join-Path $demo "batch-history.csv"
            $historyErr = Join-Path $artifacts "batch-history-acceptance.stderr.txt"
            $watch = [System.Diagnostics.Stopwatch]::StartNew()
            $historyRaw = (& $python (Join-Path $root "scripts/batch_history_export.py") `
                --project $historyProjectFile --markdown $historyPath --csv $historyCsv 2>$historyErr | Out-String)
            $watch.Stop()
            $historyExit = $LASTEXITCODE
            $historyOk = $false
            $historyDetail = $historyPath
            try {
                $historyData = $historyRaw | ConvertFrom-Json
                $historyOk = [bool]$historyData.ok
                if ($historyOk) {
                    $historyDetail = "$historyPath（$(@($historyData.runs).Count) 次运行；$historyProjectLabel：$historyProjectFile）"
                }
                else {
                    $historyDetail = "$historyPath（退出码 $historyExit，ok=false，详见 $historyErr）"
                }
            }
            catch {
                $historyDetail = "$historyPath（退出码 $historyExit，无法解析脚本 JSON 输出，详见 $historyErr）"
            }
            Add-Step -Name "批量历史汇总" -Status ($(if ($historyOk) { "pass" } else { "fail" })) -Seconds $watch.Elapsed.TotalSeconds -Detail $historyDetail
        }

        # 严格验收（正向）：对 flow 项目用包内 Python 执行 backend.project
        # check-dataset 严格策略（--require-test）。阈值不凭空写死：先用全 0 限位
        # 试跑一次读取 counts.by_class，把每类各划分的最小样本数作为可达下限
        # （训练/验证/测试至少 1 张），再以该 policy 做一次正式的正向验收。这样
        # 演示数据的批次划分或规模变化时阈值仍可达；本步骤证明的是“严格验收
        # 链路可在目标机正向通过”，不是正式验收门槛（正式门槛需真实课堂数据
        # 满足每类 ≥30 训练 / ≥8 验证 / ≥10 测试）。
        $strictProjectRoot = $null
        if ($IncludeFlow -and (Test-Path $flowCreateOut)) {
            try {
                $flowCreateData = Get-Content $flowCreateOut -Raw -Encoding UTF8 | ConvertFrom-Json
                $candidateRoot = [string]$flowCreateData.project_root
                if (-not [string]::IsNullOrWhiteSpace($candidateRoot)) {
                    $strictProjectRoot = $candidateRoot
                }
            }
            catch {
                $strictProjectRoot = $null
            }
        }
        $strictProjectFile = $null
        if ($strictProjectRoot) {
            $candidate = Join-Path $strictProjectRoot "project.json"
            if (Test-Path $candidate) { $strictProjectFile = $candidate }
        }

        if (-not $IncludeFlow) {
            Add-Step -Name "严格验收（正向）" -Status "skip" -Seconds 0 -Detail "需同时指定 -IncludeFlow"
        }
        elseif (-not $strictProjectFile) {
            Add-Step -Name "严格验收（正向）" -Status "skip" -Seconds 0 `
                -Detail "未取得 flow 项目（ui-create-import-acceptance.json 缺少可用 project_root 或 project.json 不存在）"
        }
        else {
            $strictProbeErr = Join-Path $artifacts "strict-acceptance-probe.stderr.txt"
            $strictErr = Join-Path $artifacts "strict-acceptance.stderr.txt"
            $watch = [System.Diagnostics.Stopwatch]::StartNew()
            # 在包根执行 -m backend.project：-m 会把当前目录加入 sys.path，包内
            # Python 无需额外 PYTHONPATH；结束后恢复原工作目录。
            Push-Location $root
            try {
                # 试跑：下限全 0 且不要求测试集，只用于读取实际划分计数。
                $probeRaw = (& $python -m backend.project check-dataset --root $strictProjectRoot `
                    --min-train 0 --min-val 0 --min-test 0 2>$strictProbeErr | Out-String)
                $probeData = $null
                $probeParsed = $false
                try {
                    $probeData = $probeRaw | ConvertFrom-Json
                    $probeParsed = $true
                }
                catch {
                    $probeData = $null
                }
                $policyTrain = 1
                $policyVal = 1
                $policyTest = 1
                $policyNote = ""
                if (($null -ne $probeData) -and ($null -ne $probeData.counts)) {
                    $probeClasses = @($probeData.counts.by_class)
                    if ($probeClasses.Count -gt 0) {
                        # 每类最小样本数即可达阈值；训练/验证/测试下限至少 1 张。
                        $policyTrain = [Math]::Max(
                            1, [int](($probeClasses | Measure-Object -Property train -Minimum).Minimum))
                        $policyVal = [Math]::Max(
                            1, [int](($probeClasses | Measure-Object -Property val -Minimum).Minimum))
                        $policyTest = [Math]::Max(
                            1, [int](($probeClasses | Measure-Object -Property test -Minimum).Minimum))
                    }
                    else {
                        $policyNote = "；试跑未返回 by_class，改用保底下限 1/1/1"
                    }
                }
                elseif ($probeParsed) {
                    $policyNote = "；试跑未返回 counts，改用保底下限 1/1/1"
                }
                else {
                    $policyNote = "；试跑 JSON 无法解析，改用保底下限 1/1/1"
                }

                $strictRaw = (& $python -m backend.project check-dataset --root $strictProjectRoot `
                    --require-test --min-train $policyTrain --min-val $policyVal `
                    --min-test $policyTest 2>$strictErr | Out-String)
                $strictExit = $LASTEXITCODE
            }
            finally {
                Pop-Location
            }
            $watch.Stop()
            $strictData = $null
            try {
                $strictData = $strictRaw | ConvertFrom-Json
            }
            catch {
                $strictData = $null
            }
            $strictOk = $false
            $strictDetail = $strictProjectRoot
            if ($null -eq $strictData) {
                $strictDetail = "$strictProjectRoot（退出码 $strictExit，无法解析 check-dataset JSON 输出，详见 $strictErr）"
            }
            else {
                $strictIssues = @($strictData.issues)
                $strictOk = ($strictExit -eq 0) -and [bool]$strictData.ok -and ($strictIssues.Count -eq 0)
                $strictPolicy = "require_test=true, min_train=$policyTrain, " +
                    "min_val=$policyVal, min_test=$policyTest"
                $strictCounts = "未返回 counts"
                if ($null -ne $strictData.counts) {
                    $strictCounts = "total=$($strictData.counts.total), " +
                        "train/val/test=$($strictData.counts.splits.train)/" +
                        "$($strictData.counts.splits.val)/$($strictData.counts.splits.test)"
                    $strictClasses = @($strictData.counts.by_class)
                    if ($strictClasses.Count -gt 0) {
                        $classMinTrain = [int](($strictClasses | Measure-Object -Property train -Minimum).Minimum)
                        $classMinVal = [int](($strictClasses | Measure-Object -Property val -Minimum).Minimum)
                        $classMinTest = [int](($strictClasses | Measure-Object -Property test -Minimum).Minimum)
                        $strictCounts += "，每类最小 train/val/test=" +
                            "$classMinTrain/$classMinVal/$classMinTest"
                    }
                }
                if ($strictOk) {
                    $strictDetail = "$strictProjectRoot（policy: $strictPolicy；counts: " +
                        "$strictCounts；阈值取自 counts.by_class 最小值$policyNote，" +
                        "仅验证严格验收链路正向通过，不是正式验收门槛）"
                }
                else {
                    $strictDetail = "$strictProjectRoot（退出码 $strictExit，" +
                        "ok=$([bool]$strictData.ok)，issues=$($strictIssues.Count)；" +
                        "policy: $strictPolicy；counts: $strictCounts$policyNote；详见 $strictErr）"
                }
            }
            Add-Step -Name "严格验收（正向）" -Status ($(if ($strictOk) { "pass" } else { "fail" })) -Seconds $watch.Elapsed.TotalSeconds -Detail $strictDetail
        }

        # 自检幂等性复核（第 11 步）：第 1 步是首次自检；本步骤在全部扩展步骤
        # 之后用包内 Python 在包根再执行一次清单校验，确认验收过程（启动窗口、
        # 训练、写项目等）没有改写清单涉及的包内文件。历史缺陷：旧打包把
        # backend/__pycache__ 的 pyc 纳入清单，首次自检重写 pyc 后复核摘要不符；
        # 打包脚本已排除 __pycache__/pyc，本步骤用于防止该缺陷回归。
        $idemErr = Join-Path $artifacts "verify-bundle-idempotent.stderr.txt"
        $watch = [System.Diagnostics.Stopwatch]::StartNew()
        $idemExit = 1
        Push-Location $root
        try {
            & $python (Join-Path $root "scripts/verify_offline_bundle.py") --extracted . 2>$idemErr | Out-Null
            $idemExit = $LASTEXITCODE
        }
        finally {
            Pop-Location
        }
        $watch.Stop()
        if ($idemExit -eq 0) {
            Add-Step -Name "自检幂等性复核" -Status "pass" -Seconds $watch.Elapsed.TotalSeconds -Detail "验收后自检通过（清单摘要可重复校验）"
        }
        else {
            Add-Step -Name "自检幂等性复核" -Status "fail" -Seconds $watch.Elapsed.TotalSeconds -Detail "验收后自检失败（第 2 次 verify_offline_bundle --extracted . 退出码 $idemExit，清单摘要与首次不一致或校验失败，详见 $idemErr）"
        }
    }

    $failed = @($result.steps | Where-Object { $_.status -eq "fail" })
    $result.ok = $failed.Count -eq 0
    if (-not $result.ok) {
        $result.error = "存在失败步骤：" + (($failed | ForEach-Object { $_.name }) -join "、")
    }
}
catch {
    $result.error = $_.Exception.Message
}
finally {
    $outputPath = if ([System.IO.Path]::IsPathRooted($Output)) {
        [System.IO.Path]::GetFullPath($Output)
    }
    else {
        [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $Output))
    }
    $isAdmin = $false
    try {
        $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
        $isAdmin = $principal.IsInRole(
            [System.Security.Principal.WindowsBuiltInRole]::Administrator)
    }
    catch {
        $isAdmin = $false
    }
    $cpuName = ""
    $memoryGb = ""
    try {
        $cpuName = (Get-CimInstance Win32_Processor | Select-Object -First 1).Name
        $memoryGb = [Math]::Round(
            (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
    }
    catch {
        $cpuName = ""
    }
    $freeGb = ""
    try {
        $qualifier = Split-Path -Qualifier $root
        $freeGb = [Math]::Round((Get-PSDrive -Name $qualifier.TrimEnd(':')).Free / 1GB, 1)
    }
    catch {
        $freeGb = ""
    }
    $longPaths = "未知"
    try {
        $longPathsValue = (Get-ItemProperty `
            -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" `
            -Name "LongPathsEnabled" -ErrorAction Stop).LongPathsEnabled
        $longPaths = if ($longPathsValue -eq 1) { "已启用" } else { "未启用" }
    }
    catch {
        $longPaths = "未知"
    }
    $rootLength = ([string]$root).Length

    $report = New-Object System.Text.StringBuilder
    [void]$report.AppendLine("# LAITP 离线包验收记录")
    [void]$report.AppendLine()
    [void]$report.AppendLine("- 时间：$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
    [void]$report.AppendLine("- 系统：$([System.Environment]::OSVersion.VersionString)")
    [void]$report.AppendLine("- 用户：$env:USERNAME（管理员：$(if ($isAdmin) { '是' } else { '否' })）")
    [void]$report.AppendLine("- CPU：$cpuName")
    [void]$report.AppendLine("- 内存：$memoryGb GB")
    [void]$report.AppendLine("- 磁盘：$freeGb GB（包所在盘剩余）")
    [void]$report.AppendLine("- 长路径支持：$longPaths（Windows LongPathsEnabled）")
    [void]$report.AppendLine("- 包目录长度：$rootLength 字符（建议使用较短解压路径）")
    [void]$report.AppendLine("- 包目录：$root")
    [void]$report.AppendLine()
    [void]$report.AppendLine("## 包身份")
    [void]$report.AppendLine()
    if ($null -ne $result.bundle) {
        [void]$report.AppendLine("- format：$($result.bundle.format)")
        [void]$report.AppendLine("- created_at：$($result.bundle.created_at)")
        [void]$report.AppendLine("- 组件数：$bundleComponentCount")
        [void]$report.AppendLine("- 文件数：$($result.bundle.file_count)")
        [void]$report.AppendLine("- 总字节：$($result.bundle.total_bytes)")
        $manifestShaShort = [string]$result.bundle.manifest_sha256
        if ($manifestShaShort.Length -gt 16) {
            $manifestShaShort = $manifestShaShort.Substring(0, 16)
        }
        [void]$report.AppendLine("- manifest SHA-256：$manifestShaShort（前 16 位）")
    }
    elseif (Test-Path $manifestPath) {
        [void]$report.AppendLine("manifest.json 存在但无法解析（包身份不可用）。")
    }
    else {
        [void]$report.AppendLine("未找到 manifest.json。")
    }
    foreach ($bundleWarning in @($result.warnings)) {
        [void]$report.AppendLine("- 警告：$bundleWarning")
    }
    [void]$report.AppendLine()
    [void]$report.AppendLine("| 步骤 | 状态 | 耗时(s) |")
    [void]$report.AppendLine("| --- | --- | --- |")
    foreach ($step in $result.steps) {
        [void]$report.AppendLine("| $($step.name) | $($step.status) | $($step.seconds) |")
    }
    [void]$report.AppendLine()
    [void]$report.AppendLine("## 结论")
    [void]$report.AppendLine()
    if ($result.ok) {
        [void]$report.AppendLine("通过（步骤全部通过或跳过）。")
    }
    else {
        [void]$report.AppendLine("未通过：$($result.error)")
    }
    $reportPath = Join-Path (Split-Path -Parent $outputPath) "acceptance-report.md"
    [System.IO.File]::WriteAllText(
        $reportPath, $report.ToString(), (New-Object System.Text.UTF8Encoding($false)))
    $result.report = $reportPath
    $json = $result | ConvertTo-Json -Depth 5
    [System.IO.File]::WriteAllText($outputPath, $json, (New-Object System.Text.UTF8Encoding($false)))
    Write-Output $json
}

if ($result.ok) { exit 0 } else { exit 1 }
