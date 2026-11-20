# 界面自动化：新建项目 → 导入图片 → 检查数据
# 需要预先准备 SourceRoot\类别\批次\*.png 图片目录。
# 用法：powershell -File scripts\ui_create_import.ps1 -SourceRoot <dir> -ProjectParent <dir>
param(
    [string]$Exe = "desktop\src\Laitp.Desktop\bin\Debug\net8.0-windows10.0.19041.0\Laitp.Desktop.exe",
    [Parameter(Mandatory = $true)][string]$SourceRoot,
    [Parameter(Mandatory = $true)][string]$ProjectParent,
    [string]$ProjectName = "界面自动化项目",
    [string]$Classes = "苹果 香蕉",
    [string]$TreeSource = "",
    [string]$TestSource = "",
    [string]$Output = "artifacts\ui-create-import.json",
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
    while ((Get-Date) -lt $deadline) {
        $element = Find-ById -Root $Root -AutomationId $AutomationId
        if ($element -and $element.Current.IsEnabled) { return }
        Start-Sleep -Milliseconds 300
    }
    throw "按钮 $AutomationId 长时间不可用"
}

function Wait-TextChanged {
    param($Window, [string]$AutomationId, [string]$Pattern, [string]$Previous,
          [int]$TimeoutSeconds = 120)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $last = $null
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
        $last = Get-Text -Root $Window -AutomationId $AutomationId
        if ($last -and $last -ne $Previous -and $last -match $Pattern) { return $last }
        if ($last -and $last -ne $Previous -and $last -match "失败|超时") { return $last }
    }
    return $last
}

function Wait-Text {
    param($Window, [string]$AutomationId, [string]$Pattern, [int]$TimeoutSeconds = 120)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $last = $null
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
        $last = Get-Text -Root $Window -AutomationId $AutomationId
        if ($last -and $last -match $Pattern) { return $last }
        if ($last -and $last -match "失败|超时") { return $last }
    }
    return $last
}

$source = (Resolve-Path $SourceRoot).Path
$parent = [System.IO.Path]::GetFullPath($ProjectParent)
if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent | Out-Null }
$projectRoot = Join-Path $parent "界面 项目"
if (Test-Path $projectRoot) { Remove-Item -Recurse -Force $projectRoot }

$exePath = (Resolve-Path $Exe).Path
$process = Start-Process -FilePath $exePath -PassThru
$result = [ordered]@{
    exe = $exePath
    project_root = $projectRoot
    window_found = $false
    create_status = $null
    classes_after_create = $null
    import_statuses = @()
    dataset_summary = $null
    check_status = $null
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
    while (-not (Find-ById -Root $window -AutomationId "NewProjectRootBox") -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
    }

    Set-Value -Root $window -AutomationId "NewProjectRootBox" -Value $projectRoot
    Set-Value -Root $window -AutomationId "NewProjectNameBox" -Value $ProjectName
    Set-Value -Root $window -AutomationId "NewProjectClassesBox" -Value $Classes
    Invoke-Button -Root $window -AutomationId "CreateProjectButton"
    $result.create_status = Wait-Text -Window $window -AutomationId "StatusText" -Pattern "已创建并打开项目" -TimeoutSeconds 120
    $result.classes_after_create = Get-Text -Root $window -AutomationId "ClassesTextBlock"

    $imported = 0
    if ($TreeSource) {
        Set-Value -Root $window -AutomationId "ImportTreeSourceBox" -Value (Resolve-Path $TreeSource).Path
        $previous = Get-Text -Root $window -AutomationId "StatusText"
        Invoke-Button -Root $window -AutomationId "ImportTreeButton"
        $status = Wait-TextChanged -Window $window -AutomationId "StatusText" -Pattern "批量导入完成" -Previous $previous -TimeoutSeconds 300
        $result.import_statuses += [ordered]@{
            class = "(批量)"
            batch = "(全部)"
            status = $status
        }
        if ($status -and $status -match "批量导入完成") { $imported++ }
    }
    else {
        foreach ($className in $Classes.Split(" ")) {
            if (-not $className) { continue }
            $classDir = Join-Path $source $className
            if (-not (Test-Path $classDir)) { continue }
            $batches = Get-ChildItem -Path $classDir -Directory | Sort-Object Name
            foreach ($batch in $batches) {
                Wait-ButtonEnabled -Root $window -AutomationId "ImportButton"
                Set-ValueChecked -Root $window -AutomationId "ImportClassBox" -Value $className
                Set-ValueChecked -Root $window -AutomationId "ImportSourceBox" -Value $batch.FullName
                Set-ValueChecked -Root $window -AutomationId "ImportBatchBox" -Value $batch.Name
                $previous = Get-Text -Root $window -AutomationId "StatusText"
                Invoke-Button -Root $window -AutomationId "ImportButton"
                $status = Wait-TextChanged -Window $window -AutomationId "StatusText" -Pattern "导入完成" -Previous $previous -TimeoutSeconds 120
                Wait-ButtonEnabled -Root $window -AutomationId "ImportButton"
                $result.import_statuses += [ordered]@{
                    class = $className
                    batch = $batch.Name
                    status = $status
                }
                if ($status -and $status -match "导入完成") { $imported++ }
            }
        }
    }

    $testImported = 0
    if ($TestSource) {
        $testRoot = (Resolve-Path $TestSource).Path
        $testBox = Find-ById -Root $window -AutomationId "ImportAsTestCheckBox"
        if ($null -eq $testBox) { throw "未找到测试集导入复选框" }
        $toggle = $testBox.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
        if ($toggle.Current.ToggleState -ne [System.Windows.Automation.ToggleState]::On) {
            $toggle.Toggle()
        }
        Start-Sleep -Milliseconds 300
        foreach ($classDir in (Get-ChildItem -Path $testRoot -Directory | Sort-Object Name)) {
            foreach ($batch in (Get-ChildItem -Path $classDir.FullName -Directory | Sort-Object Name)) {
                Wait-ButtonEnabled -Root $window -AutomationId "ImportButton"
                Set-ValueChecked -Root $window -AutomationId "ImportClassBox" -Value $classDir.Name
                Set-ValueChecked -Root $window -AutomationId "ImportSourceBox" -Value $batch.FullName
                Set-ValueChecked -Root $window -AutomationId "ImportBatchBox" -Value $batch.Name
                $previous = Get-Text -Root $window -AutomationId "StatusText"
                Invoke-Button -Root $window -AutomationId "ImportButton"
                $status = Wait-TextChanged -Window $window -AutomationId "StatusText" -Pattern "导入完成" -Previous $previous -TimeoutSeconds 120
                Wait-ButtonEnabled -Root $window -AutomationId "ImportButton"
                $result.import_statuses += [ordered]@{
                    class = $classDir.Name
                    batch = $batch.Name
                    split = "test"
                    status = $status
                }
                if ($status -and $status -match "导入完成") { $testImported++ }
            }
        }
        if ($toggle.Current.ToggleState -ne [System.Windows.Automation.ToggleState]::Off) {
            $toggle.Toggle()
        }
    }

    Start-Sleep -Seconds 1
    $result.dataset_summary = Get-Text -Root $window -AutomationId "DatasetSummaryTextBlock"

    Invoke-Button -Root $window -AutomationId "CheckDatasetButton"
    Start-Sleep -Seconds 6
    $result.check_status = Get-Text -Root $window -AutomationId "DataCheckStatusText"

    $projectFile = Join-Path $projectRoot "project.json"
    $created = (Test-Path $projectFile)
    $classesOk = -not [string]::IsNullOrWhiteSpace($result.classes_after_create) -and $result.classes_after_create.Contains("/")
    $importOk = if ($TreeSource) { $imported -ge 1 } else { $imported -ge 4 }
    $testOk = (-not $TestSource) -or (
        $testImported -ge 1 -and $result.dataset_summary -match "测试 [1-9]"
    )
    $summaryOk = -not [string]::IsNullOrWhiteSpace($result.dataset_summary) -and $result.dataset_summary.Contains("合计")
    $checkOk = -not [string]::IsNullOrWhiteSpace($result.check_status) -and $result.check_status -match "数据检查通过"
    $result.ok = $created -and $classesOk -and $importOk -and $testOk -and $summaryOk -and $checkOk
    if (-not $result.ok) {
        $result.error = "新建项目、导入或数据检查的界面状态不符合预期"
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
