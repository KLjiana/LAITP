# 最小界面冒烟：使用 Windows UI Automation 定位窗口、点击“环境自检”，
# 读取状态栏与消息区变化。结果写入 JSON。
# 用法：powershell -ExecutionPolicy Bypass -File scripts\ui_smoke.ps1
param(
    [string]$Exe = "desktop\src\Laitp.Desktop\bin\Debug\net8.0-windows10.0.19041.0\Laitp.Desktop.exe",
    [string]$Output = "artifacts\ui-smoke.json",
    [string]$LaitpHome = "",
    [string]$LaitpPython = "",
    [switch]$BrokenPython,
    [switch]$Screenshot
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
if ($Screenshot) {
    Add-Type -AssemblyName System.Drawing
    Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class LaitpWin32 {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdcBlt, uint nFlags);
}
"@
}

function Save-WindowScreenshot {
    param($Window, [string]$Path)
    $handle = [IntPtr]$Window.Current.NativeWindowHandle
    [LaitpWin32]::ShowWindow($handle, 9) | Out-Null
    [LaitpWin32]::SetForegroundWindow($handle) | Out-Null
    Start-Sleep -Milliseconds 800
    $rect = $Window.Current.BoundingRectangle
    $width = [int]$rect.Width
    $height = [int]$rect.Height
    if ($width -le 0 -or $height -le 0) { throw "窗口尺寸无效：$width x $height" }
    $bitmap = New-Object System.Drawing.Bitmap($width, $height)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $method = "PrintWindow"
    try {
        $hdc = $graphics.GetHdc()
        try {
            $printed = [LaitpWin32]::PrintWindow($handle, $hdc, 2)
        }
        finally {
            $graphics.ReleaseHdc($hdc)
        }
        if (-not $printed) {
            $method = "CopyFromScreen"
            $graphics.CopyFromScreen(
                [int]$rect.X, [int]$rect.Y, 0, 0,
                (New-Object System.Drawing.Size($width, $height)))
        }
        $directory = [System.IO.Path]::GetDirectoryName($Path)
        if (-not (Test-Path $directory)) { New-Item -ItemType Directory -Path $directory | Out-Null }
        $bitmap.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
    }
    finally {
        $graphics.Dispose()
        $bitmap.Dispose()
    }
    return $method
}

if ($LaitpHome) {
    $env:LAITP_HOME = $LaitpHome
}
if ($LaitpPython) {
    $env:LAITP_PYTHON = $LaitpPython
}
if ($BrokenPython) {
    $env:LAITP_PYTHON = Join-Path $env:TEMP "laitp-missing-python.exe"
}

function Find-ByControlType {
    param($Root, $ControlType)
    $condition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty, $ControlType)
    return $Root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)
}

function Find-ById {
    param($Root, [string]$AutomationId)
    $condition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::AutomationIdProperty, $AutomationId)
    return $Root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $condition)
}

function Get-Names {
    param($Elements)
    $names = @()
    foreach ($element in $Elements) {
        $name = $element.Current.Name
        if ($name) { $names += $name }
    }
    return $names
}

$exePath = (Resolve-Path $Exe).Path
$process = Start-Process -FilePath $exePath -PassThru
$result = [ordered]@{
    exe = $exePath
    expect_failure = $BrokenPython.IsPresent
    window_found = $false
    title = ""
    button_found = $false
    status_before = @()
    status_after = @()
    message_lines = @()
    screenshot = ""
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

    if (-not $window) {
        throw "未找到桌面窗口（进程 $($process.Id)）"
    }
    $result.window_found = $true
    $result.title = $window.Current.Name

    # 等待自动自检完成（启动后后台运行）。
    Start-Sleep -Seconds 4
    $deadline = (Get-Date).AddSeconds(30)
    while (-not (Find-ById -Root $window -AutomationId "StatusText") -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
    }

    $textsBefore = Find-ByControlType -Root $window -ControlType ([System.Windows.Automation.ControlType]::Text)
    $result.status_before = @(Get-Names $textsBefore | Where-Object { $_ -match "自检|就绪|未通过|失败" })

    $buttons = Find-ByControlType -Root $window -ControlType ([System.Windows.Automation.ControlType]::Button)
    $selfTestButton = $null
    foreach ($button in $buttons) {
        if ($button.Current.Name -eq "环境自检") { $selfTestButton = $button; break }
    }

    if (-not $selfTestButton) {
        throw "未找到环境自检按钮"
    }
    $result.button_found = $true

    $pattern = $selfTestButton.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
    $pattern.Invoke()
    Start-Sleep -Seconds 4

    $textsAfter = Find-ByControlType -Root $window -ControlType ([System.Windows.Automation.ControlType]::Text)
    $result.status_after = @(Get-Names $textsAfter | Where-Object { $_ -match "自检|就绪|未通过|失败" })

    $lists = Find-ByControlType -Root $window -ControlType ([System.Windows.Automation.ControlType]::List)
    foreach ($list in $lists) {
        $items = Find-ByControlType -Root $list -ControlType ([System.Windows.Automation.ControlType]::ListItem)
        foreach ($item in $items) {
            $name = $item.Current.Name
            if ($name -match "自检|通过|失败") { $result.message_lines += $name }
        }
    }

    if ($Screenshot) {
        $shotPath = Join-Path (Get-Location) ("artifacts\ui-screenshots\ui-smoke-" +
            (Get-Date -Format "yyyyMMdd-HHmmss") + ".png")
        $shotPath = [System.IO.Path]::GetFullPath($shotPath)
        Save-WindowScreenshot -Window $window -Path $shotPath
        $result.screenshot = $shotPath
    }

    if ($BrokenPython) {
        $failureStatus = @($result.status_before | Where-Object { $_ -match "未通过|失败" })
        $failureLines = @($result.message_lines | Where-Object { $_ -match "^失败|未通过" })
        $result.ok = ($failureStatus.Count -gt 0) -and ($failureLines.Count -gt 0)
        if (-not $result.ok) {
            $result.error = "错误 Python 环境下未观察到自动自检失败提示"
        }
    }
    else {
        $result.ok = ($result.status_after.Count -gt 0) -and ($result.message_lines.Count -gt 0)
        if (-not $result.ok) {
            $result.error = "点击后未观察到自检状态或消息变化"
        }
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
