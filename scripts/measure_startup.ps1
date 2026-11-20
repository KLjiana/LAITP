# 启动耗时测量：启动桌面包内 exe，记录窗口出现与自动自检完成的时间。
# 用法：powershell -File scripts\measure_startup.ps1 [-Exe <exe>] [-Output <json>]
param(
    [string]$Exe = "dist\desktop-selfcontained\Laitp.Desktop.exe",
    [string]$Output = "artifacts\startup-measure.json",
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

$exePath = (Resolve-Path $Exe).Path
$watch = [System.Diagnostics.Stopwatch]::StartNew()
$process = Start-Process -FilePath $exePath -PassThru
$result = [ordered]@{
    exe = $exePath
    window_seconds = $null
    selftest_seconds = $null
    status = $null
    ok = $false
    error = ""
}

try {
    $window = $null
    $deadline = (Get-Date).AddSeconds(120)
    while ((Get-Date) -lt $deadline -and -not $window) {
        Start-Sleep -Milliseconds 100
        $candidates = [System.Windows.Automation.AutomationElement]::RootElement.FindAll(
            [System.Windows.Automation.TreeScope]::Children,
            (New-Object System.Windows.Automation.PropertyCondition(
                [System.Windows.Automation.AutomationElement]::ProcessIdProperty, $process.Id)))
        foreach ($candidate in $candidates) {
            if (Find-ById -Root $candidate -AutomationId "StatusText") {
                $window = $candidate
                break
            }
        }
    }
    if (-not $window) { throw "窗口未在 120 秒内出现" }
    $result.window_seconds = [Math]::Round($watch.Elapsed.TotalSeconds, 2)

    $status = $null
    $deadline = (Get-Date).AddSeconds(120)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 200
        $status = (Find-ById -Root $window -AutomationId "StatusText").Current.Name
        if ($status -and $status -match "环境自检通过|环境自检未通过") { break }
    }
    $result.selftest_seconds = [Math]::Round($watch.Elapsed.TotalSeconds, 2)
    $result.status = $status
    $result.ok = ($result.window_seconds -ne $null -and $status -match "环境自检通过")
    if (-not $result.ok) { $result.error = "自动自检未通过或未完成：$status" }
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
