# 界面主流程冒烟：打开项目 → 检查数据（可选训练 → 预测），使用 Windows UI Automation。
# 用法：
#   powershell -File scripts\ui_flow.ps1 -ProjectPath <project.json>
#   powershell -File scripts\ui_flow.ps1 -ProjectPath <project.json> -DataReport
#   powershell -File scripts\ui_flow.ps1 -ProjectPath <project.json> -ImagePath <png> -TrainPredict
#   powershell -File scripts\ui_flow.ps1 -ProjectPath <project.json> -ImagePath <png> -TrainPredict -BatchImagesDir <dir> -PostChecks
param(
    [string]$Exe = "desktop\src\Laitp.Desktop\bin\Debug\net8.0-windows10.0.19041.0\Laitp.Desktop.exe",
    [Parameter(Mandatory = $true)][string]$ProjectPath,
    [string]$ImagePath = "",
    [string]$Output = "artifacts\ui-flow.json",
    [string]$LaitpHome = "",
    [string]$LaitpPython = "",
    [switch]$TrainPredict,
    [switch]$DataReport,
    [switch]$PostChecks,
    [switch]$CleanEnv,
    [switch]$UseRecent,
    [string]$SaveAsDir = "",
    [string]$ArchiveDir = "",
    [string]$BatchImagesDir = "",
    [string]$ComparePackage = "",
    [int]$Epochs = 1
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

if ($CleanEnv) {
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    $env:HTTP_PROXY = "http://127.0.0.1:9"
    $env:HTTPS_PROXY = "http://127.0.0.1:9"
    $env:NO_PROXY = ""
}

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

function Get-Value {
    param($Root, [string]$AutomationId)
    $element = Find-ById -Root $Root -AutomationId $AutomationId
    if ($null -eq $element) { return $null }
    $pattern = $element.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
    return $pattern.Current.Value
}

function Set-Value {
    param($Root, [string]$AutomationId, [string]$Value)
    $element = Find-ById -Root $Root -AutomationId $AutomationId
    if ($null -eq $element) { throw "未找到控件 $AutomationId" }
    $pattern = $element.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
    $pattern.SetValue($Value)
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

function Invoke-Button {
    param($Root, [string]$AutomationId)
    $element = Find-ById -Root $Root -AutomationId $AutomationId
    if ($null -eq $element) { throw "未找到按钮 $AutomationId" }
    $element.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
}

function Get-ListNames {
    param($Root)
    $names = @()
    $lists = $Root.FindAll(
        [System.Windows.Automation.TreeScope]::Descendants,
        (New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
            [System.Windows.Automation.ControlType]::List)))
    foreach ($list in $lists) {
        $items = $list.FindAll(
            [System.Windows.Automation.TreeScope]::Children,
            (New-Object System.Windows.Automation.PropertyCondition(
                [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
                [System.Windows.Automation.ControlType]::ListItem)))
        foreach ($item in $items) {
            if ($item.Current.Name) { $names += $item.Current.Name }
        }
    }
    return $names
}

function Wait-Status {    param($Window, [string]$Pattern, [int]$TimeoutSeconds = 240)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $last = $null
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 700
        $last = Get-Text -Root $Window -AutomationId "StatusText"
        if ($last -and $last -match $Pattern) { return $last }
        if ($last -and $last -match "失败|未通过|超时") { return $last }
    }
    return $last
}

$projectFile = (Resolve-Path $ProjectPath).Path
$exePath = (Resolve-Path $Exe).Path
$process = Start-Process -FilePath $exePath -PassThru
$result = [ordered]@{
    exe = $exePath
    project = $projectFile
    train_predict = $TrainPredict.IsPresent
    window_found = $false
    status_after_open = $null
    classes = $null
    status_after_check = $null
    data_check_status = $null
    data_report_status = $null
    data_report_path = $null
    train_status = $null
    package = $null
    image = $null
    predict_status = $null
    artifact = $null
    open_seconds = $null
    check_seconds = $null
    train_seconds = $null
    predict_seconds = $null
    save_as_status = $null
    archive_export_status = $null
    archive_import_status = $null
    archive_path = $null
    batch_status = $null
    compare_status = $null
    verify_project_status = $null
    export_history_status = $null
    compare_history_status = $null
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

    $pathBox = Find-ById -Root $window -AutomationId "ProjectPathBox"
    if ($null -eq $pathBox) { throw "未找到项目路径输入框" }
    Set-Value -Root $window -AutomationId "ProjectPathBox" -Value $projectFile
    Start-Sleep -Milliseconds 300

    $openWatch = [System.Diagnostics.Stopwatch]::StartNew()
    if ($UseRecent) {
        $recentButton = Find-ById -Root $window -AutomationId "OpenRecentButton"
        if ($null -eq $recentButton) { throw "未找到打开最近按钮" }
        $recentButton.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
    }
    else {
        $openButton = Find-ById -Root $window -AutomationId "OpenProjectButton"
        if ($null -eq $openButton) { throw "未找到打开项目按钮" }
        $openButton.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
    }
    Start-Sleep -Seconds 5
    $openWatch.Stop()
    $result.open_seconds = [Math]::Round($openWatch.Elapsed.TotalSeconds, 2)

    $result.status_after_open = Get-Text -Root $window -AutomationId "StatusText"
    $result.classes = Get-Text -Root $window -AutomationId "ClassesTextBlock"

    if ($SaveAsDir) {
        Set-Value -Root $window -AutomationId "SaveAsPathBox" -Value $SaveAsDir
        Invoke-Button -Root $window -AutomationId "SaveAsButton"
        $result.save_as_status = Wait-Status -Window $window -Pattern "已另存为|另存为失败" -TimeoutSeconds 300
        $result.status_after_open = Get-Text -Root $window -AutomationId "StatusText"
    }

    if ($ArchiveDir) {
        $archiveRoot = if ([System.IO.Path]::IsPathRooted($ArchiveDir)) {
            [System.IO.Path]::GetFullPath($ArchiveDir)
        }
        else {
            [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $ArchiveDir))
        }
        if (-not (Test-Path $archiveRoot)) {
            New-Item -ItemType Directory -Force -Path $archiveRoot | Out-Null
        }
        $archiveZip = Join-Path $archiveRoot "flow-archive.zip"
        if (Test-Path $archiveZip) { Remove-Item -Path $archiveZip -Force }
        $result.archive_path = $archiveZip

        Set-ValueChecked -Root $window -AutomationId "ArchivePathBox" -Value $archiveZip
        Wait-ButtonEnabled -Root $window -AutomationId "ExportArchiveButton"
        Invoke-Button -Root $window -AutomationId "ExportArchiveButton"
        $result.archive_export_status = Wait-Status -Window $window -Pattern "已导出存档" -TimeoutSeconds 300

        Set-ValueChecked -Root $window -AutomationId "ArchivePathBox" -Value $archiveZip
        Wait-ButtonEnabled -Root $window -AutomationId "ImportArchiveButton"
        Invoke-Button -Root $window -AutomationId "ImportArchiveButton"
        $result.archive_import_status = Wait-Status -Window $window -Pattern "已从存档导入" -TimeoutSeconds 300
    }

    $checkWatch = [System.Diagnostics.Stopwatch]::StartNew()
    $checkButton = Find-ById -Root $window -AutomationId "CheckDatasetButton"
    if ($null -eq $checkButton) { throw "未找到检查数据按钮" }
    $checkButton.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
    Start-Sleep -Seconds 6
    $checkWatch.Stop()
    $result.check_seconds = [Math]::Round($checkWatch.Elapsed.TotalSeconds, 2)

    $result.status_after_check = Get-Text -Root $window -AutomationId "StatusText"
    $result.data_check_status = Get-Text -Root $window -AutomationId "DataCheckStatusText"

    if ($DataReport) {
        Wait-ButtonEnabled -Root $window -AutomationId "DatasetReportButton"
        Invoke-Button -Root $window -AutomationId "DatasetReportButton"
        $result.data_report_status = Wait-Status -Window $window -Pattern "数据体检完成|数据体检失败" -TimeoutSeconds 300
        # 状态文本只含统计数字；路径优先取消息区“数据体检报告：<路径>”，
        # 消息不可见时退回项目 runs/ 下的报告文件是否存在。
        $reportMessages = @(Get-ListNames -Root $window | Where-Object { $_ -match "数据体检报告" })
        if ($reportMessages.Count -gt 0 -and $reportMessages[-1] -match "数据体检报告[：:]\s*(.+)$") {
            $result.data_report_path = $Matches[1].Trim()
        }
        if (-not $result.data_report_path) {
            $reportFile = Join-Path (Split-Path -Parent $projectFile) "runs\dataset-report.md"
            if (Test-Path $reportFile) {
                $result.data_report_path = (Resolve-Path $reportFile).Path
            }
        }
    }

    $classesOk = -not [string]::IsNullOrWhiteSpace($result.classes) -and $result.classes.Contains("/")
    $statusOk = $null -ne $result.status_after_open -and
    ($result.status_after_open -match "已打开项目" -or $result.status_after_open -match "已另存为")
    $checkOk = $null -ne $result.data_check_status -and $result.data_check_status -match "数据检查通过"
    $trainOk = $true
    $predictOk = $true

    if ($TrainPredict) {
        Set-Value -Root $window -AutomationId "EpochsBox" -Value "$Epochs"
        $trainButton = Find-ById -Root $window -AutomationId "TrainButton"
        if ($null -eq $trainButton) { throw "未找到训练按钮" }
        $trainWatch = [System.Diagnostics.Stopwatch]::StartNew()
        $trainButton.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
        $result.train_status = Wait-Status -Window $window -Pattern "训练与导出完成" -TimeoutSeconds 360
        $trainWatch.Stop()
        $result.train_seconds = [Math]::Round($trainWatch.Elapsed.TotalSeconds, 2)
        $trainOk = $null -ne $result.train_status -and $result.train_status -match "训练与导出完成"
        $result.package = Get-Value -Root $window -AutomationId "PackagePathBox"
        if ($trainOk -and $ImagePath) {
            $result.image = (Resolve-Path $ImagePath).Path
            Set-ValueChecked -Root $window -AutomationId "ImagePathBox" -Value $result.image
            Wait-ButtonEnabled -Root $window -AutomationId "PredictButton"
            $predictWatch = [System.Diagnostics.Stopwatch]::StartNew()
            Invoke-Button -Root $window -AutomationId "PredictButton"
            $result.predict_status = Wait-Status -Window $window -Pattern "^成功$" -TimeoutSeconds 180
            if ($result.predict_status -notmatch "^成功$") {
                Start-Sleep -Seconds 1
                Wait-ButtonEnabled -Root $window -AutomationId "PredictButton"
                Invoke-Button -Root $window -AutomationId "PredictButton"
                $result.predict_status = Wait-Status -Window $window -Pattern "^成功$" -TimeoutSeconds 180
            }
            $predictWatch.Stop()
            $result.predict_seconds = [Math]::Round($predictWatch.Elapsed.TotalSeconds, 2)
            $result.artifact = Get-Text -Root $window -AutomationId "ArtifactText"
            $predictOk = $result.predict_status -eq "成功"
        }

        if ($trainOk -and $BatchImagesDir) {
            Set-ValueChecked -Root $window -AutomationId "BatchImagesBox" -Value (Resolve-Path $BatchImagesDir).Path
            Wait-ButtonEnabled -Root $window -AutomationId "BatchPredictButton"
            Invoke-Button -Root $window -AutomationId "BatchPredictButton"
            $result.batch_status = Wait-Status -Window $window -Pattern "批量预测完成|批量预测失败" -TimeoutSeconds 900
            $result.batch_messages = @(Get-ListNames -Root $window |
                Where-Object { $_ -match "批量预测|各类准确率|各批次准确率|误判|CSV|JSON" })
        }

        if ($trainOk -and $ComparePackage) {
            if (-not $BatchImagesDir) {
                $result.compare_status = "跳过：未指定批量测试目录"
            }
            else {
                Set-ValueChecked -Root $window -AutomationId "ComparePackageBox" -Value (Resolve-Path $ComparePackage).Path
                Wait-ButtonEnabled -Root $window -AutomationId "CompareButton"
                Invoke-Button -Root $window -AutomationId "CompareButton"
                $result.compare_status = Wait-Status -Window $window -Pattern "模型对比完成|模型对比失败" -TimeoutSeconds 300
            }
        }
    }

    if ($PostChecks) {
        Wait-ButtonEnabled -Root $window -AutomationId "VerifyProjectButton"
        Invoke-Button -Root $window -AutomationId "VerifyProjectButton"
        $result.verify_project_status = Wait-Status -Window $window -Pattern "项目校验通过|项目校验失败" -TimeoutSeconds 300

        if ($BatchImagesDir) {
            Wait-ButtonEnabled -Root $window -AutomationId "ExportBatchHistoryButton"
            Invoke-Button -Root $window -AutomationId "ExportBatchHistoryButton"
            $result.export_history_status = Wait-Status -Window $window -Pattern "已导出批量历史|导出批量历史失败" -TimeoutSeconds 300
        }

        if ($ComparePackage) {
            # 模型对比成功后界面会把 runs/compare-*.json 刷新到对比历史列表；
            # 这里验证“选中历史 → 查看对比历史”这条回看链路。
            $historyList = Find-ById -Root $window -AutomationId "CompareHistoryListBox"
            $historyItem = $null
            if ($null -ne $historyList) {
                $itemCondition = New-Object System.Windows.Automation.PropertyCondition(
                    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
                    [System.Windows.Automation.ControlType]::ListItem)
                $historyItems = $historyList.FindAll(
                    [System.Windows.Automation.TreeScope]::Children, $itemCondition)
                foreach ($candidate in $historyItems) {
                    $historyItem = $candidate
                    break
                }
            }

            if ($null -eq $historyItem) {
                $result.compare_history_status = "跳过：无对比历史"
            }
            else {
                # 查看按钮的 CanExecute 依赖选中项，必须先选中第一项按钮才可用。
                try {
                    $selection = $historyItem.GetCurrentPattern(
                        [System.Windows.Automation.SelectionItemPattern]::Pattern)
                    $selection.Select()
                    Start-Sleep -Milliseconds 300
                }
                catch {
                    # 个别提供程序不支持 SelectionItemPattern：继续走按钮点击，
                    # 界面会在未选中时提示“请先选择对比历史”。
                }
                Wait-ButtonEnabled -Root $window -AutomationId "ViewCompareHistoryButton"
                Invoke-Button -Root $window -AutomationId "ViewCompareHistoryButton"
                $result.compare_history_status = Wait-Status -Window $window `
                    -Pattern "已载入历史模型对比结果|读取.*失败|请先选择" -TimeoutSeconds 120

                if ($result.compare_history_status -match "请先选择") {
                    # 选择未生效（例如通知迟到）：重新选中第一项后再点一次。
                    try {
                        $selection = $historyItem.GetCurrentPattern(
                            [System.Windows.Automation.SelectionItemPattern]::Pattern)
                        $selection.Select()
                        Start-Sleep -Milliseconds 300
                        Wait-ButtonEnabled -Root $window -AutomationId "ViewCompareHistoryButton"
                        Invoke-Button -Root $window -AutomationId "ViewCompareHistoryButton"
                        $result.compare_history_status = Wait-Status -Window $window `
                            -Pattern "已载入历史模型对比结果|读取.*失败|请先选择" -TimeoutSeconds 120
                    }
                    catch {
                        $result.compare_history_status = "读取历史对比结果失败：" + $_.Exception.Message
                    }
                }
            }
        }
    }

    $saveAsOk = (-not $SaveAsDir) -or ($result.save_as_status -match "已另存为")
    $archiveOk = (-not $ArchiveDir) -or
        ($result.archive_export_status -match "已导出存档" -and
         $result.archive_import_status -match "已从存档导入")
    $batchOk = (-not $BatchImagesDir) -or
        ($result.batch_status -match "批量预测完成" -and
         @($result.batch_messages | Where-Object { $_ -match "各类准确率" }).Count -gt 0 -and
         @($result.batch_messages | Where-Object { $_ -match "各批次准确率" }).Count -gt 0)
    $compareOk = (-not $ComparePackage) -or ($result.compare_status -match "模型对比完成")
    $dataReportOk = (-not $DataReport) -or ($result.data_report_status -match "数据体检完成")
    $postOk = (-not $PostChecks) -or
        (($result.verify_project_status -match "项目校验通过") -and
         ($BatchImagesDir -eq "" -or $result.export_history_status -match "已导出批量历史"))
    $compareHistoryOk = (-not $PostChecks) -or (-not $ComparePackage) -or
        ($result.compare_history_status -match "已载入历史模型对比结果") -or
        ($result.compare_history_status -eq "跳过：无对比历史")
    $result.ok = $classesOk -and $statusOk -and $checkOk -and $trainOk -and $predictOk -and $saveAsOk -and $archiveOk -and $batchOk -and $compareOk -and $dataReportOk -and $postOk -and $compareHistoryOk
    if (-not $result.ok) {
        $result.error = "界面状态不符合预期"
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
