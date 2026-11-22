[CmdletBinding()]
param(
    [string]$BatchManifest = "config/batch/tracked-requests.json",
    [string]$UvEnvironment = "",
    [ValidateRange(1, 10)]
    [int]$MaximumAttemptsPerRevision = 3
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-AutomationState {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [object]$State
    )

    $temporaryPath = "$Path.tmp"
    $json = ConvertTo-Json -InputObject $State -Depth 10
    [System.IO.File]::WriteAllText(
        $temporaryPath,
        "$json`n",
        [System.Text.UTF8Encoding]::new($false)
    )
    Move-Item -LiteralPath $temporaryPath -Destination $Path -Force
}

function Invoke-AutonomousFactory {
    $repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
    $automationRoot = Join-Path $repoRoot ".image2outfit\autonomous-factory"
    $statePath = Join-Path $automationRoot "state.json"
    $logPath = Join-Path $automationRoot "latest-run.log"
    $lockPath = Join-Path $automationRoot "run.lock"
    $lockStream = $null

    New-Item -ItemType Directory -Path $automationRoot -Force | Out-Null

    try {
        $lockStream = [System.IO.File]::Open(
            $lockPath,
            [System.IO.FileMode]::OpenOrCreate,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
    }
    catch [System.IO.IOException] {
        Write-Output "Skipped: another autonomous factory run owns the lock."
        return 0
    }

    try {
        $git = Get-Command git.exe -ErrorAction Stop
        $sourceCommit = (& $git.Source -C $repoRoot rev-parse HEAD).Trim()
        if ($LASTEXITCODE -ne 0 -or -not $sourceCommit) {
            throw "Could not read the repository commit."
        }
        $branch = (& $git.Source -C $repoRoot branch --show-current).Trim()
        if ($LASTEXITCODE -ne 0 -or -not $branch) {
            throw "Autonomous manufacturing requires a named Git branch."
        }

        $previousState = $null
        if (Test-Path -LiteralPath $statePath -PathType Leaf) {
            $previousState = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        }

        $attempts = 1
        if ($null -ne $previousState -and $previousState.sourceCommit -eq $sourceCommit) {
            if ($previousState.status -in @("SUCCEEDED", "REVIEW_REQUIRED")) {
                Write-Output "Skipped: $($previousState.status) is terminal for commit $sourceCommit."
                return 0
            }

            $previousAttempts = [int]$previousState.attemptsThisRevision
            if ($previousState.status -in @("FAILED", "RUNNING", "FAILED_HALTED_MAX_RETRIES") -and $previousAttempts -ge $MaximumAttemptsPerRevision) {
                $previousState.status = "FAILED_HALTED_MAX_RETRIES"
                $previousState.checkedAt = (Get-Date).ToString("o")
                Write-AutomationState -Path $statePath -State $previousState
                Write-Output "Skipped: failure limit reached for commit $sourceCommit."
                return 1
            }
            $attempts = $previousAttempts + 1
        }

        $dirtyEntries = @(& $git.Source -C $repoRoot status --porcelain --untracked-files=all)
        if ($LASTEXITCODE -ne 0) {
            throw "Could not inspect the repository worktree."
        }
        if ($dirtyEntries.Count -gt 0) {
            $state = [ordered]@{
                schemaVersion = 1
                sourceCommit = $sourceCommit
                branch = $branch
                batchManifest = $BatchManifest
                status = "SKIPPED_DIRTY_WORKTREE"
                attemptsThisRevision = if ($null -ne $previousState -and $previousState.sourceCommit -eq $sourceCommit) { [int]$previousState.attemptsThisRevision } else { 0 }
                checkedAt = (Get-Date).ToString("o")
                dirtyPaths = @($dirtyEntries | ForEach-Object { $_.Substring(3).Trim() })
                productCompletionClaimed = $false
                releaseEligibilityEvaluated = $false
            }
            Write-AutomationState -Path $statePath -State $state
            Set-Content -LiteralPath $logPath -Value "Skipped because tracked or untracked source files are present." -Encoding UTF8
            Write-Output "Skipped: the worktree has source changes; current product evidence is preserved."
            return 0
        }

        $startedAt = Get-Date
        $runningState = [ordered]@{
            schemaVersion = 1
            sourceCommit = $sourceCommit
            branch = $branch
            batchManifest = $BatchManifest
            status = "RUNNING"
            attemptsThisRevision = $attempts
            startedAt = $startedAt.ToString("o")
            productCompletionClaimed = $false
            releaseEligibilityEvaluated = $false
        }
        Write-AutomationState -Path $statePath -State $runningState
        Set-Content -LiteralPath $logPath -Value "Started $($startedAt.ToString('o')) on $branch at $sourceCommit" -Encoding UTF8

        $task = Get-Command task.exe -ErrorAction Stop
        $uv = Get-Command uv.exe -ErrorAction Stop
        $environmentPath = if ($UvEnvironment) {
            [System.IO.Path]::GetFullPath($UvEnvironment)
        }
        else {
            Join-Path $repoRoot "Assets\_Local\uv-env-task-v311"
        }
        $pythonPath = Join-Path $environmentPath "Scripts\python.exe"
        if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
            throw "Pinned local Python environment is missing: $environmentPath"
        }
        $env:PATH = "$(Split-Path -Parent $task.Source);$(Split-Path -Parent $uv.Source);$env:PATH"

        $taskOutput = @(& $task.Source "batch:run" "BATCH=$BatchManifest" "UV_ENV=$environmentPath" 2>&1)
        $taskExitCode = $LASTEXITCODE
        $taskOutput | Add-Content -LiteralPath $logPath -Encoding UTF8
        $afterRunDirtyEntries = @(& $git.Source -C $repoRoot status --porcelain --untracked-files=all)
        if ($LASTEXITCODE -ne 0) {
            $afterRunDirtyEntries = @("WORKTREE_STATUS_UNAVAILABLE")
        }

        $finalStatus = switch ($taskExitCode) {
            0 { "SUCCEEDED"; break }
            2 { "REVIEW_REQUIRED"; break }
            default { "FAILED" }
        }
        $finishedAt = Get-Date
        $state = [ordered]@{
            schemaVersion = 1
            sourceCommit = $sourceCommit
            branch = $branch
            batchManifest = $BatchManifest
            status = $finalStatus
            taskExitCode = $taskExitCode
            attemptsThisRevision = $attempts
            startedAt = $startedAt.ToString("o")
            finishedAt = $finishedAt.ToString("o")
            runtimeSeconds = [math]::Round(($finishedAt - $startedAt).TotalSeconds, 1)
            dirtyPathsAfterRun = @($afterRunDirtyEntries | ForEach-Object { $_.Substring([math]::Min(3, $_.Length)).Trim() })
            productCompletionClaimed = $false
            releaseEligibilityEvaluated = $false
        }
        Write-AutomationState -Path $statePath -State $state
        return [int]$taskExitCode
    }
    catch {
        $errorText = $_.Exception.Message
        Set-Content -LiteralPath $logPath -Value "Automation error: $errorText" -Encoding UTF8
        if (Test-Path -LiteralPath $statePath -PathType Leaf) {
            try {
                $existingState = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
                if ($existingState.status -eq "RUNNING") {
                    $existingState.status = "FAILED"
                    $existingState.taskExitCode = 1
                    $existingState.finishedAt = (Get-Date).ToString("o")
                    $existingState.error = $errorText
                    Write-AutomationState -Path $statePath -State $existingState
                }
            }
            catch {
                # Keep the original automation error visible in the log.
            }
        }
        Write-Output "Automation error: $errorText"
        return 1
    }
    finally {
        if ($null -ne $lockStream) {
            $lockStream.Dispose()
        }
    }
}

$resultCode = Invoke-AutonomousFactory
exit $resultCode
