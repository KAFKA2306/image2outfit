[CmdletBinding()]
param(
    [string]$TaskName = "Image2Outfit Factory Daily",
    [string]$DailyAt = "03:00"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runnerPath = Join-Path $PSScriptRoot "run_autonomous_factory.ps1"
$taskDescription = "Managed by image2outfit; serial checkpointed production with human visual-review stop."
if (-not (Test-Path -LiteralPath $runnerPath -PathType Leaf)) {
    throw "Autonomous factory runner is missing: $runnerPath"
}

$git = Get-Command git.exe -ErrorAction Stop
$branch = (& $git.Source -C $repoRoot branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or -not $branch) {
    throw "Register the task from a named Git branch."
}
$dirtyEntries = @(& $git.Source -C $repoRoot status --porcelain --untracked-files=all)
if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect the repository worktree."
}
if ($dirtyEntries.Count -gt 0) {
    throw "Register the task only from a clean worktree; current files must remain reviewable."
}

$timeParts = $DailyAt.Split(":")
if ($timeParts.Count -ne 2) {
    throw "DailyAt must use HH:mm local time."
}
$hour = [int]$timeParts[0]
$minute = [int]$timeParts[1]
if ($hour -lt 0 -or $hour -gt 23 -or $minute -lt 0 -or $minute -gt 59) {
    throw "DailyAt must use a valid 24-hour time."
}
$firstRun = (Get-Date).Date.AddHours($hour).AddMinutes($minute)
if ($firstRun -le (Get-Date)) {
    $firstRun = $firstRun.AddDays(1)
}

$powershellPath = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$actionArguments = "-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runnerPath`""
$action = New-ScheduledTaskAction -Execute $powershellPath -Argument $actionArguments -WorkingDirectory $repoRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $firstRun
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfIdle `
    -IdleDuration (New-TimeSpan -Minutes 15) `
    -IdleWaitTimeout (New-TimeSpan -Hours 2) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4) `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited

$existingTask = Get-ScheduledTask -TaskName $TaskName -TaskPath "\" -ErrorAction SilentlyContinue
if ($null -ne $existingTask) {
    if ($existingTask.Description -ne $taskDescription) {
        throw "A different task already uses '$TaskName'; it was not changed."
    }
    if ($existingTask.State -eq "Running") {
        throw "The owned task is running; wait before updating its schedule."
    }
    Set-ScheduledTask `
        -TaskName $TaskName `
        -TaskPath "\" `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal | Out-Null
}
else {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -TaskPath "\" `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description $taskDescription | Out-Null
}

$registered = Get-ScheduledTask -TaskName $TaskName -TaskPath "\"
$taskInfo = Get-ScheduledTaskInfo -TaskName $TaskName -TaskPath "\"
[pscustomobject]@{
    taskPath = $registered.TaskPath
    taskName = $registered.TaskName
    state = $registered.State.ToString()
    runAs = $registered.Principal.UserId
    logonType = $registered.Principal.LogonType.ToString()
    nextRunTime = $taskInfo.NextRunTime.ToString("o")
    worktree = $repoRoot
    sourceBranch = $branch
    idleMinutesRequired = 15
    maximumRuntimeHours = 4
    maximumFailedAttemptsPerRevision = 3
    releaseEligibilityEvaluated = $false
} | ConvertTo-Json -Depth 4
