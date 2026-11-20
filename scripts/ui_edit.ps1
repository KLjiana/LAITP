# 界面自动化：项目编辑与严格验收
# 打开真实项目副本 → 项目改名 → 添加/删除类别 → 类别改名 → 样本重命名/删除 → 严格验收检查
# 默认路径（不传 -ExpectStrictPass）：严格验收应因样本不足显示“未通过”，用于拒绝路径证据。
# 正向路径（-ExpectStrictPass）：写入每类样本下限并断言“严格验收检查通过”。删除样本会使
# 某类的验证样本从 20 降到 19，无法满足 20/20/10，因此正向模式跳过删除样本步骤
# （删除路径由默认拒绝模式覆盖）。
# 用法：
#   powershell -File scripts\ui_edit.ps1 -ProjectPath <project.json>
#   powershell -File scripts\ui_edit.ps1 -ProjectPath <project.json> `
#       -MinTrain 20 -MinVal 20 -MinTest 10 -ExpectStrictPass
param(
    [string]$Exe = "desktop\src\Laitp.Desktop\bin\Debug\net8.0-windows10.0.19041.0\Laitp.Desktop.exe",
    [Parameter(Mandatory = $true)][string]$ProjectPath,
    [string]$Output = "artifacts\ui-edit.json",
    [string]$LaitpHome = "",
    [string]$LaitpPython = "",
    [string]$MinTrain = "",
    [string]$MinVal = "",
    [string]$MinTest = "",
    [switch]$ExpectStrictPass
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
    param($Window, [string]$Pattern, [int]$TimeoutSeconds = 120)
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

function Get-ListItems {
    param($Root, [string]$AutomationId)
    $list = Find-ById -Root $Root -AutomationId $AutomationId
    if ($null -eq $list) { return @() }
    $condition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::ListItem)
    $items = $list.FindAll([System.Windows.Automation.TreeScope]::Children, $condition)
    $names = @()
    foreach ($item in $items) { $names += $item.Current.Name }
    return ,$names
}

function Get-ElementValue {
    param($Element)
    if ($null -eq $Element) { return $null }
    return $Element.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value
}

# 严格验收阈值输入框优先按 AutomationId（MinTrainBox/MinValBox/MinTestBox）定位；
# 旧版界面没有 AutomationId 时，回退为“与 StrictAcceptanceCheckBox 同一水平行、位于其右侧”的几何定位，
# 再按水平位置排序，依次即 MinTrain/MinVal/MinTest 三个输入框。
function Find-StrictThresholdBoxes {
    param($Window)
    $byId = @()
    foreach ($id in @("MinTrainBox", "MinValBox", "MinTestBox")) {
        $element = Find-ById -Root $Window -AutomationId $id
        if ($null -eq $element) { $byId = @(); break }
        $byId += $element
    }
    if ($byId.Count -eq 3) { return ,$byId }
    $strictBox = Find-ById -Root $Window -AutomationId "StrictAcceptanceCheckBox"
    if ($null -eq $strictBox) { return $null }
    $anchor = $strictBox.Current.BoundingRectangle
    if ($anchor.IsEmpty) { return $null }
    $condition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Edit)
    $edits = $Window.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)
    $selected = @()
    foreach ($edit in $edits) {
        $rect = $edit.Current.BoundingRectangle
        if ($rect.IsEmpty) { continue }
        $sameRow = ($rect.Top -lt $anchor.Bottom) -and ($rect.Bottom -gt $anchor.Top)
        if ($sameRow -and ($rect.Left -gt $anchor.Left)) { $selected += $edit }
    }
    if ($selected.Count -ne 3) { return $null }
    return @($selected | Sort-Object { $_.Current.BoundingRectangle.Left })
}

# 写入严格验收阈值并逐个读回校验，返回实际生效的 train/val/test 字符串。
function Set-StrictThresholds {
    param($Window, [string]$Train, [string]$Val, [string]$Test)
    $boxes = Find-StrictThresholdBoxes -Window $Window
    if ($null -eq $boxes) { throw "未找到严格验收阈值输入框（MinTrain/MinVal/MinTest）" }
    $labels = @("train", "val", "test")
    $expected = @($Train, $Val, $Test)
    $applied = [ordered]@{ train = ""; val = ""; test = "" }
    for ($index = 0; $index -lt $expected.Count; $index++) {
        $pattern = $boxes[$index].GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
        if ($expected[$index] -ne "") {
            $pattern.SetValue($expected[$index])
            Start-Sleep -Milliseconds 150
            $readBack = $pattern.Current.Value
            if ($readBack -ne $expected[$index]) {
                throw "严格验收阈值 $($labels[$index]) 回读不一致：写入 $($expected[$index])，实际 $readBack"
            }
        }
        $applied[$labels[$index]] = $pattern.Current.Value
    }
    return ,$applied
}

$projectFile = (Resolve-Path $ProjectPath).Path
$exePath = (Resolve-Path $Exe).Path
$process = Start-Process -FilePath $exePath -PassThru
$result = [ordered]@{
    exe = $exePath
    project = $projectFile
    window_found = $false
    rename_project_status = $null
    classes_after_add = $null
    classes_after_remove = $null
    classes_after_rename = $null
    samples_before = 0
    rename_sample_status = $null
    delete_sample_status = $null
    samples_after = 0
    strict_check_status = $null
    strict_data_check = $null
    strict_thresholds = [ordered]@{ train = ""; val = ""; test = "" }
    strict_positive = $false
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

    # 项目改名
    Set-Value -Root $window -AutomationId "EditProjectNameBox" -Value "教室项目"
    Invoke-Button -Root $window -AutomationId "RenameProjectButton"
    $result.rename_project_status = Wait-Status -Window $window -Pattern "项目已改名" -TimeoutSeconds 120

    # 添加类别
    Set-Value -Root $window -AutomationId "NewClassNameBox" -Value "测试类别"
    Invoke-Button -Root $window -AutomationId "AddClassButton"
    $addStatus = Wait-Status -Window $window -Pattern "已添加类别" -TimeoutSeconds 120
    $result.classes_after_add = Get-Text -Root $window -AutomationId "ClassesTextBlock"

    # 删除类别
    Set-Value -Root $window -AutomationId "RemoveClassNameBox" -Value "测试类别"
    Invoke-Button -Root $window -AutomationId "RemoveClassButton"
    $removeStatus = Wait-Status -Window $window -Pattern "已删除类别" -TimeoutSeconds 120
    $result.classes_after_remove = Get-Text -Root $window -AutomationId "ClassesTextBlock"

    # 类别改名：T恤 → 短袖
    Set-Value -Root $window -AutomationId "RenameClassOldBox" -Value "T恤"
    Set-Value -Root $window -AutomationId "RenameClassNewBox" -Value "短袖"
    Invoke-Button -Root $window -AutomationId "RenameClassButton"
    $renameClassStatus = Wait-Status -Window $window -Pattern "已重命名类别" -TimeoutSeconds 120
    $result.classes_after_rename = Get-Text -Root $window -AutomationId "ClassesTextBlock"

    # 样本列表与重命名
    $before = Get-ListItems -Root $window -AutomationId "SampleListBox"
    $result.samples_before = $before.Count
    $sampleList = Find-ById -Root $window -AutomationId "SampleListBox"
    $itemCondition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::ListItem)
    $items = $sampleList.FindAll([System.Windows.Automation.TreeScope]::Children, $itemCondition)
    if ($items.Count -eq 0) { throw "样本列表为空" }
    $items[0].GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select()
    Start-Sleep -Milliseconds 500
    Set-Value -Root $window -AutomationId "SampleNewNameBox" -Value "样本A"
    Invoke-Button -Root $window -AutomationId "RenameSampleButton"
    $result.rename_sample_status = Wait-Status -Window $window -Pattern "已重命名样本" -TimeoutSeconds 120

    # 删除样本（正向严格验收模式跳过：每类验证样本只有 20 张，删除后降为 19，
    # 20/20/10 阈值将无法通过；删除样本的路径由默认拒绝模式覆盖。）
    if ($ExpectStrictPass) {
        $result.delete_sample_status = "已跳过：-ExpectStrictPass 保留每类完整样本量"
        $after = Get-ListItems -Root $window -AutomationId "SampleListBox"
        $result.samples_after = $after.Count
    }
    else {
        Start-Sleep -Milliseconds 500
        $items2 = $sampleList.FindAll([System.Windows.Automation.TreeScope]::Children, $itemCondition)
        if ($items2.Count -eq 0) { throw "重命名后样本列表为空" }
        $items2[0].GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select()
        Start-Sleep -Milliseconds 500
        Invoke-Button -Root $window -AutomationId "DeleteSampleButton"
        $result.delete_sample_status = Wait-Status -Window $window -Pattern "已删除样本" -TimeoutSeconds 120
        $after = Get-ListItems -Root $window -AutomationId "SampleListBox"
        $result.samples_after = $after.Count
    }

    # 严格验收：先写入每类样本下限（任一 Min 参数非空时）并读回校验，再勾选并检查
    $strictThresholds = $null
    if (($MinTrain -ne "") -or ($MinVal -ne "") -or ($MinTest -ne "")) {
        $strictThresholds = Set-StrictThresholds -Window $window -Train $MinTrain -Val $MinVal -Test $MinTest
    }
    if ($null -eq $strictThresholds) {
        # 未指定阈值时尽量读取界面当前值，便于在结果中记录默认拒绝所用的阈值。
        try {
            $boxes = Find-StrictThresholdBoxes -Window $window
            if ($null -ne $boxes) {
                $strictThresholds = [ordered]@{
                    train = (Get-ElementValue -Element $boxes[0])
                    val = (Get-ElementValue -Element $boxes[1])
                    test = (Get-ElementValue -Element $boxes[2])
                }
            }
        }
        catch {
            $strictThresholds = $null
        }
    }
    if ($null -ne $strictThresholds) { $result.strict_thresholds = $strictThresholds }

    # 严格验收：勾选后检查。默认路径应因样本不足“未通过”；-ExpectStrictPass 应“严格验收检查通过”。
    $strictBox = Find-ById -Root $window -AutomationId "StrictAcceptanceCheckBox"
    if ($null -eq $strictBox) { throw "未找到严格验收复选框" }
    $toggle = $strictBox.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
    if ($toggle.Current.ToggleState -ne [System.Windows.Automation.ToggleState]::On) { $toggle.Toggle() }
    Start-Sleep -Milliseconds 500
    Invoke-Button -Root $window -AutomationId "CheckDatasetButton"
    if ($ExpectStrictPass) {
        $result.strict_check_status = Wait-Status -Window $window -Pattern "严格验收检查通过|数据检查未通过" -TimeoutSeconds 120
    }
    else {
        $result.strict_check_status = Wait-Status -Window $window -Pattern "严格验收检查通过|数据检查未通过|严格验收检查未通过" -TimeoutSeconds 120
    }
    $result.strict_data_check = Get-Text -Root $window -AutomationId "DataCheckStatusText"

    $renameOk = $result.rename_project_status -match "项目已改名"
    $addOk = $addStatus -match "已添加类别" -and $result.classes_after_add -match "测试类别"
    $removeOk = $removeStatus -match "已删除类别" -and $result.classes_after_remove -notmatch "测试类别"
    $renameClassOk = $renameClassStatus -match "已重命名类别" -and $result.classes_after_rename -match "短袖"
    $sampleRenameOk = $result.rename_sample_status -match "已重命名样本"
    $sampleDeleteOk = if ($ExpectStrictPass) {
        $result.delete_sample_status -match "已跳过"
    }
    else {
        $result.delete_sample_status -match "已删除样本"
    }
    # 样本列表为虚拟化列表，可见项数量不等于总数，故只校验删除状态与序号变化提示。
    $strictPositive = [bool]($ExpectStrictPass -and
        ($result.strict_data_check -match "通过") -and
        ($result.strict_check_status -match "严格验收检查通过"))
    $result.strict_positive = $strictPositive
    if ($ExpectStrictPass) {
        $strictOk = $strictPositive
    }
    else {
        $strictOk = $result.strict_data_check -match "未通过"
    }
    $result.ok = $result.window_found -and $renameOk -and $addOk -and $removeOk -and $renameClassOk -and $sampleRenameOk -and $sampleDeleteOk -and $strictOk
    if (-not $result.ok) {
        $result.error = "项目编辑或严格验收的界面状态不符合预期"
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
