# 摄像头长时间预览稳定性：启动桌面 → 开始预览 → 定时采样内存 → 停止，输出 JSON。
# 用法：powershell -File scripts\ui_preview_stability.ps1 [-Seconds 60] [-Exe <exe>]
param(
    [string]$Exe = "desktop\src\Laitp.Desktop\bin\Debug\net8.0-windows10.0.19041.0\Laitp.Desktop.exe",
    [int]$Seconds = 60,
    [int]$SampleSeconds = 5,
    [string]$Output = "artifacts\ui-preview-stability.json",
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

function Invoke-Button {
    param($Root, [string]$AutomationId)
    $element = Find-ById -Root $Root -AutomationId $AutomationId
    if ($null -eq $element) { throw "未找到按钮 $AutomationId" }
    $element.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
}

function Wait-Status {
    param($Window, [string]$Pattern, [int]$TimeoutSeconds = 60)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
        $status = Get-Text -Root $Window -AutomationId "StatusText"
        if ($status -and $status -match $Pattern) { return $status }
    }
    return (Get-Text -Root $Window -AutomationId "StatusText")
}

$exePath = (Resolve-Path $Exe).Path
$process = Start-Process -FilePath $exePath -PassThru
$result = [ordered]@{
    exe = $exePath
    seconds = $Seconds
    window_found = $false
    preview_status = $null
    preview_stop_status = $null
    samples = @()
    memory_start_mb = $null
    memory_end_mb = $null
    memory_peak_mb = $null
    memory_growth_mb = $null
    ok = $false
    error = ""
}

try {
    $window = $null
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline -and -not $window) {
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

    Invoke-Button -Root $window -AutomationId "CameraPreviewButton"
    Start-Sleep -Seconds 2
    $elapsed = 0
    while ($elapsed -lt $Seconds) {
        Start-Sleep -Seconds $SampleSeconds
        $elapsed += $SampleSeconds
        $process.Refresh()
        $memoryMb = [Math]::Round($process.WorkingSet64 / 1MB, 1)
        $handles = $process.HandleCount
        $status = Get-Text -Root $window -AutomationId "StatusText"
        $result.samples += [ordered]@{
            at_seconds = $elapsed
            memory_mb = $memoryMb
            handles = $handles
            status = $status
        }
    }

    $status = Get-Text -Root $window -AutomationId "StatusText"
    $result.preview_status = $status
    $memories = @($result.samples | ForEach-Object { $_.memory_mb })
    if ($memories.Count -gt 0) {
        $result.memory_start_mb = $memories[0]
        $result.memory_end_mb = $memories[-1]
        $result.memory_peak_mb = ($memories | Measure-Object -Maximum).Maximum
        $result.memory_growth_mb = [Math]::Round($result.memory_end_mb - $result.memory_start_mb, 1)
    }

    Invoke-Button -Root $window -AutomationId "CameraPreviewStopButton"
    $result.preview_stop_status = Wait-Status -Window $window -Pattern "预览已停止" -TimeoutSeconds 60

    $previewOk = $result.preview_status -match "预览中（\d" -and $result.preview_status -match "fps"
    $memoryOk = $null -eq $result.memory_growth_mb -or $result.memory_growth_mb -lt 150
    $result.ok = $previewOk -and $result.preview_stop_status -match "预览已停止" -and $memoryOk
    if (-not $result.ok) {
        $result.error = "长时间预览状态或内存增长不符合预期"
    }
}
catch {
    $result.error = $_.Exception.Message
}
finally {
    if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
}

$json = $result | ConvertTo-Json -Depth 6
$outputPath = if ([System.IO.Path]::IsPathRooted($Output)) { [System.IO.Path]::GetFullPath($Output) } else { [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $Output)) }
$directory = [System.IO.Path]::GetDirectoryName($outputPath)
if (-not (Test-Path $directory)) { New-Item -ItemType Directory -Path $directory | Out-Null }
[System.IO.File]::WriteAllText($outputPath, $json, (New-Object System.Text.UTF8Encoding($false)))
Write-Output $json
if ($result.ok) { exit 0 } else { exit 1 }
