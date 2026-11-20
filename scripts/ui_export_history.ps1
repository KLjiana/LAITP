# 界面自动化：训练历史导出（未选择时提示；选择后重新导出并切换当前模型）
# 用法：powershell -File scripts\ui_export_history.ps1 -ProjectPath <project.json>
param(
    [string]$Exe = "desktop\src\Laitp.Desktop\bin\Debug\net8.0-windows10.0.19041.0\Laitp.Desktop.exe",
    [Parameter(Mandatory = $true)][string]$ProjectPath,
    [string]$Output = "artifacts\ui-export-history.json",
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
    $element.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).SetValue($Value)
}

function Invoke-Button {
    param($Root, [string]$AutomationId)
    $element = Find-ById -Root $Root -AutomationId $AutomationId
    if ($null -eq $element) { throw "未找到按钮 $AutomationId" }
    $element.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
}

function Wait-Status {
    param($Window, [string]$Pattern, [int]$TimeoutSeconds = 180)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $last = $null
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
        $last = Get-Text -Root $Window -AutomationId "StatusText"
        if ($last -and $last -match $Pattern) { return $last }
        if ($last -and $last -match "失败|超时") { return $last }
    }
    return $last
}

$projectFile = (Resolve-Path $ProjectPath).Path
$projectDir = Split-Path -Parent $projectFile
$exePath = (Resolve-Path $Exe).Path
$process = Start-Process -FilePath $exePath -PassThru
$result = [ordered]@{
    exe = $exePath
    project = $projectFile
    window_found = $false
    no_selection_status = $null
    run_count = 0
    selected_run = $null
    export_status = $null
    artifact = $null
    exported_package_exists = $false
    ok = $false
    error = ""
}

try {
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
    if (-not $window) { throw "未找到桌面窗口" }
    $result.window_found = $true
    Start-Sleep -Seconds 4
    $deadline = (Get-Date).AddSeconds(30)
    while (-not (Find-ById -Root $window -AutomationId "ProjectPathBox") -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
    }

    Set-Value -Root $window -AutomationId "ProjectPathBox" -Value $projectFile
    Invoke-Button -Root $window -AutomationId "OpenProjectButton"
    Start-Sleep -Seconds 6

    $runsBox = Find-ById -Root $window -AutomationId "TrainingRunsListBox"
    if ($null -eq $runsBox) { throw "未找到训练历史列表" }
    $itemCondition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::ListItem)
    $items = $runsBox.FindAll([System.Windows.Automation.TreeScope]::Children, $itemCondition)
    $result.run_count = $items.Count

    if ($items.Count -eq 0) {
        # 无历史运行：导出按钮应提示先选择
        Invoke-Button -Root $window -AutomationId "ExportRunButton"
        $result.no_selection_status = Wait-Status -Window $window -Pattern "请先选择" -TimeoutSeconds 30
        $result.selected_run = ""
    }
    else {
        # 打开项目后界面会自动选中第一条历史运行，直接导出
        $result.selected_run = $items[0].Current.Name
        Invoke-Button -Root $window -AutomationId "ExportRunButton"
        $result.export_status = Wait-Status -Window $window -Pattern "已导出运行" -TimeoutSeconds 300
        $result.artifact = Get-Text -Root $window -AutomationId "ArtifactText"
        if ($result.artifact) {
            $artifactId = ($result.artifact -replace "产物 ID：", "").Trim()
            $package = Join-Path (Join-Path $projectDir "exports") (Join-Path $artifactId "model-package")
            $result.exported_package_exists = Test-Path (Join-Path $package "manifest.json")
        }
    }

    if ($items.Count -eq 0) {
        $result.ok = $result.window_found -and ($result.no_selection_status -match "请先选择")
    }
    else {
        $result.ok = $result.window_found -and ($result.run_count -gt 0) -and
            ($result.export_status -match "已导出运行") -and $result.exported_package_exists
    }
    if (-not $result.ok) {
        $result.error = "训练历史导出的界面状态不符合预期"
    }
}
catch {
    $result.error = $_.Exception.Message
}
finally {
    if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
}

$json = $result | ConvertTo-Json -Depth 5
$outputPath = if ([System.IO.Path]::IsPathRooted($Output)) { [System.IO.Path]::GetFullPath($Output) } else { [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $Output)) }
$directory = [System.IO.Path]::GetDirectoryName($outputPath)
if (-not (Test-Path $directory)) { New-Item -ItemType Directory -Path $directory | Out-Null }
[System.IO.File]::WriteAllText($outputPath, $json, (New-Object System.Text.UTF8Encoding($false)))
Write-Output $json
if ($result.ok) { exit 0 } else { exit 1 }
