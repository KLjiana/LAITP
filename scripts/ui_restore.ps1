# 界面自动化：项目保存与恢复（A9）
# 第一阶段：新建项目 → 导入 4 批 → 检查数据 → 训练并发布（1 轮）→ 记录模型产物
# 第二阶段：关闭程序后重新启动 → 重新打开项目 → 校验类别、当前模型、数据清单与检查结论
# 用法：powershell -File scripts\ui_restore.ps1 -SourceRoot <dir> -ProjectParent <dir>
param(
    [string]$Exe = "desktop\src\Laitp.Desktop\bin\Debug\net8.0-windows10.0.19041.0\Laitp.Desktop.exe",
    [Parameter(Mandatory = $true)][string]$SourceRoot,
    [Parameter(Mandatory = $true)][string]$ProjectParent,
    [string]$ProjectName = "保存恢复验证",
    [string]$Classes = "苹果 香蕉",
    [string]$Output = "artifacts\ui-restore.json",
    [string]$LaitpHome = "",
    [string]$LaitpPython = ""
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

if ($LaitpHome) { $env:LAITP_HOME = $LaitpHome }
if ($LaitpPython) { $env:LAITP_PYTHON = $LaitpPython }

function Find-ById {
    param($Root, [string]$AutomationId)
    $condition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::AutomationIdProperty, $AutomationId)
    return $Root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $condition)
}

function Get-Text {
    param($Root, [string]$AutomationId)
    $element = Find-ById -Root $Root -AutomationId $AutomationId
    if ($null -eq $element) { return $null }
    return $element.Current.Name
}

function Set-Value {
    param($Root, [string]$AutomationId, [string]$Value)
    $element = Find-ById -Root $Root -AutomationId $AutomationId
    if ($null -eq $element) { throw "未找到控件 $AutomationId" }
    $pattern = $element.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
    $pattern.SetValue($Value)
}

function Invoke-Button {
    param($Root, [string]$AutomationId)
    $element = Find-ById -Root $Root -AutomationId $AutomationId
    if ($null -eq $element) { throw "未找到按钮 $AutomationId" }
    $element.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
}

function Wait-Text {
    param($Window, [string]$AutomationId, [string]$Pattern, [int]$TimeoutSeconds = 120)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $last = $null
    while ((Get-Date) -lt $deadline -and (Get-Date) -lt $script:FlowDeadline) {
        Start-Sleep -Milliseconds 500
        $last = Get-Text -Root $Window -AutomationId $AutomationId
        if ($last -and $last -match $Pattern) { return $last }
        if ($last -and $last -match "失败|超时") { return $last }
    }
    if ((Get-Date) -ge $script:FlowDeadline) {
        throw "ui 流程总超时（$script:FlowTimeoutSeconds s）：等待状态 $Pattern（最后状态：$last）"
    }
    return $last
}

function Get-Value {
    param($Root, [string]$AutomationId)
    $element = Find-ById -Root $Root -AutomationId $AutomationId
    if ($null -eq $element) { return $null }
    return $element.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value
}

function Set-ValueChecked {
    param($Root, [string]$AutomationId, [string]$Value)
    $lastError = $null
    for ($attempt = 1; $attempt -le 4; $attempt++) {
        try {
            Set-Value -Root $Root -AutomationId $AutomationId -Value $Value
        }
        catch {
            $lastError = $_.Exception.Message
        }
        $pollDeadline = (Get-Date).AddMilliseconds(1000)
        while ((Get-Date) -lt $pollDeadline) {
            Start-Sleep -Milliseconds 100
            if ((Get-Value -Root $Root -AutomationId $AutomationId) -eq $Value) { return }
        }
        Start-Sleep -Milliseconds (150 * $attempt)
    }
    if ($lastError) {
        throw "控件 $AutomationId 的值未能设置为 $Value（最后一次错误：$lastError）"
    }
    throw "控件 $AutomationId 的值未能设置为 $Value"
}

function Wait-ButtonEnabled {
    param($Root, [string]$AutomationId, [int]$TimeoutSeconds = 60)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline -and (Get-Date) -lt $script:FlowDeadline) {
        $element = Find-ById -Root $Root -AutomationId $AutomationId
        if ($element -and $element.Current.IsEnabled) { return }
        Start-Sleep -Milliseconds 300
    }
    if ((Get-Date) -ge $script:FlowDeadline) {
        throw "ui 流程总超时（$script:FlowTimeoutSeconds s）：等待按钮 $AutomationId"
    }
    throw "按钮 $AutomationId 长时间不可用"
}

function Wait-TextChanged {
    param($Window, [string]$AutomationId, [string]$Pattern, [string]$Previous,
          [int]$TimeoutSeconds = 120)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $last = $null
    while ((Get-Date) -lt $deadline -and (Get-Date) -lt $script:FlowDeadline) {
        Start-Sleep -Milliseconds 500
        $last = Get-Text -Root $Window -AutomationId $AutomationId
        if ($last -and $last -ne $Previous -and $last -match $Pattern) { return $last }
        if ($last -and $last -ne $Previous -and $last -match "失败|超时") { return $last }
    }
    if ((Get-Date) -ge $script:FlowDeadline) {
        throw "ui 流程总超时（$script:FlowTimeoutSeconds s）：等待状态 $Pattern（最后状态：$last）"
    }
    return $last
}

function Open-Window {
    param([string]$ExePath)
    $process = Start-Process -FilePath $ExePath -PassThru
    $window = $null
    $windowDeadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $windowDeadline -and -not $window) {
        Start-Sleep -Milliseconds 500
        $candidates = [System.Windows.Automation.AutomationElement]::RootElement.FindAll(
            [System.Windows.Automation.TreeScope]::Children,
            (New-Object System.Windows.Automation.PropertyCondition(
                [System.Windows.Automation.AutomationElement]::ProcessIdProperty, $process.Id)))
        foreach ($candidate in $candidates) {
            if (Find-ById -Root $candidate -AutomationId "StatusText") { $window = $candidate; break }
        }
    }
    if (-not $window) {
        if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
        throw "未找到桌面窗口"
    }
    Start-Sleep -Seconds 4
    $deadline = (Get-Date).AddSeconds(30)
    while (-not (Find-ById -Root $window -AutomationId "StatusText") -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
    }
    return @{ Process = $process; Window = $window }
}

$source = (Resolve-Path $SourceRoot).Path
$parent = [System.IO.Path]::GetFullPath($ProjectParent)
if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent | Out-Null }
$projectRoot = Join-Path $parent "保存 恢复 项目"
if (Test-Path $projectRoot) { Remove-Item -Recurse -Force $projectRoot }

$exePath = (Resolve-Path $Exe).Path
$result = [ordered]@{
    exe = $exePath
    project_root = $projectRoot
    created = $false
    imported = 0
    trained = $false
    artifact_phase1 = $null
    reopened = $false
    status_after_reopen = $null
    classes_after_reopen = $null
    dataset_after_reopen = $null
    check_after_reopen = $null
    ok = $false
    error = ""
}

try {
    $script:FlowTimeoutSeconds = 420
    $script:FlowDeadline = (Get-Date).AddSeconds($script:FlowTimeoutSeconds)
    # ---- 第一阶段：新建、导入、训练 ----
    $first = Open-Window -ExePath $exePath
    $window = $first.Window
    Wait-ButtonEnabled -Root $window -AutomationId "CreateProjectButton"
    Set-ValueChecked -Root $window -AutomationId "NewProjectRootBox" -Value $projectRoot
    Set-ValueChecked -Root $window -AutomationId "NewProjectNameBox" -Value $ProjectName
    Set-ValueChecked -Root $window -AutomationId "NewProjectClassesBox" -Value $Classes
    $previous = Get-Text -Root $window -AutomationId "StatusText"
    Invoke-Button -Root $window -AutomationId "CreateProjectButton"
    $createStatus = Wait-TextChanged -Window $window -AutomationId "StatusText" -Pattern "已创建并打开项目" -Previous $previous -TimeoutSeconds 120
    $result.created = $null -ne $createStatus -and $createStatus -match "已创建并打开项目"

    $imported = 0
    foreach ($className in $Classes.Split(" ")) {
        if (-not $className) { continue }
        $classDir = Join-Path $source $className
        if (-not (Test-Path $classDir)) { continue }
        foreach ($batch in (Get-ChildItem -Path $classDir -Directory | Sort-Object Name)) {
            Wait-ButtonEnabled -Root $window -AutomationId "ImportButton"
            Set-ValueChecked -Root $window -AutomationId "ImportClassBox" -Value $className
            Set-ValueChecked -Root $window -AutomationId "ImportSourceBox" -Value $batch.FullName
            Set-ValueChecked -Root $window -AutomationId "ImportBatchBox" -Value $batch.Name
            $previous = Get-Text -Root $window -AutomationId "StatusText"
            Invoke-Button -Root $window -AutomationId "ImportButton"
            $status = Wait-TextChanged -Window $window -AutomationId "StatusText" -Pattern "导入完成" -Previous $previous -TimeoutSeconds 120
            Wait-ButtonEnabled -Root $window -AutomationId "ImportButton"
            if ($status -and $status -match "导入完成") { $imported++ }
        }
    }
    $result.imported = $imported

    Wait-ButtonEnabled -Root $window -AutomationId "TrainButton"
    Set-ValueChecked -Root $window -AutomationId "EpochsBox" -Value "1"
    $previous = Get-Text -Root $window -AutomationId "StatusText"
    Invoke-Button -Root $window -AutomationId "TrainButton"
    $trainStatus = Wait-TextChanged -Window $window -AutomationId "StatusText" -Pattern "训练与导出完成" -Previous $previous -TimeoutSeconds 360
    $result.trained = $null -ne $trainStatus -and $trainStatus -match "训练与导出完成"
    $result.artifact_phase1 = Get-Text -Root $window -AutomationId "ArtifactText"

    if (-not $first.Process.HasExited) { Stop-Process -Id $first.Process.Id -Force }
    Start-Sleep -Seconds 2

    # ---- 第二阶段：重新启动并重新打开项目 ----
    $second = Open-Window -ExePath $exePath
    $window2 = $second.Window
    Wait-ButtonEnabled -Root $window2 -AutomationId "OpenProjectButton"
    Set-ValueChecked -Root $window2 -AutomationId "ProjectPathBox" -Value (Join-Path $projectRoot "project.json")
    Invoke-Button -Root $window2 -AutomationId "OpenProjectButton"
    Start-Sleep -Seconds 6
    $result.status_after_reopen = Get-Text -Root $window2 -AutomationId "StatusText"
    $result.classes_after_reopen = Get-Text -Root $window2 -AutomationId "ClassesTextBlock"
    $result.dataset_after_reopen = Get-Text -Root $window2 -AutomationId "DatasetSummaryTextBlock"
    Invoke-Button -Root $window2 -AutomationId "CheckDatasetButton"
    Start-Sleep -Seconds 6
    $result.check_after_reopen = Get-Text -Root $window2 -AutomationId "DataCheckStatusText"
    $result.reopened = $result.status_after_reopen -match "当前模型"

    if (-not $second.Process.HasExited) { Stop-Process -Id $second.Process.Id -Force }

    $classesOk = -not [string]::IsNullOrWhiteSpace($result.classes_after_reopen) -and $result.classes_after_reopen.Contains("/")
    $datasetOk = -not [string]::IsNullOrWhiteSpace($result.dataset_after_reopen) -and $result.dataset_after_reopen.Contains("合计")
    $checkOk = -not [string]::IsNullOrWhiteSpace($result.check_after_reopen) -and $result.check_after_reopen -match "数据检查通过"
    $result.ok = $result.created -and ($imported -ge 4) -and $result.trained -and $result.reopened -and $classesOk -and $datasetOk -and $checkOk
    if (-not $result.ok) {
        $result.error = "保存恢复的界面状态不符合预期"
    }
}
catch {
    $result.error = $_.Exception.Message
}

$json = $result | ConvertTo-Json -Depth 6
$outputPath = if ([System.IO.Path]::IsPathRooted($Output)) { [System.IO.Path]::GetFullPath($Output) } else { [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $Output)) }
$directory = [System.IO.Path]::GetDirectoryName($outputPath)
if (-not (Test-Path $directory)) { New-Item -ItemType Directory -Path $directory | Out-Null }
[System.IO.File]::WriteAllText($outputPath, $json, (New-Object System.Text.UTF8Encoding($false)))
Write-Output $json
if ($result.ok) { exit 0 } else { exit 1 }
