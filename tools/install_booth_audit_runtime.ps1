[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$lockPath = Join-Path $repoRoot "config/booth-audit-model.json"
$lock = Get-Content -LiteralPath $lockPath -Raw -Encoding utf8 | ConvertFrom-Json
$runtimeRoot = Join-Path $repoRoot "Assets/_Local/booth-audit/runtime"
$runtimePath = Join-Path $runtimeRoot ("onnx-export-" + $lock.decisionModel.runtimeRevision.Substring(0, 8))
$modelRoot = Join-Path $repoRoot "Assets/_Local/booth-audit/models"
$modelPath = Join-Path $modelRoot ("d1-2B-ONNX-" + $lock.decisionModel.revision.Substring(0, 8))

function Invoke-Checked {
    param([Parameter(Mandatory = $true)][string]$File, [string[]]$Arguments = @())
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$File failed with exit code $LASTEXITCODE"
    }
}

function Get-RepositoryRelativePath {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Path
    )
    $fullRoot = [System.IO.Path]::GetFullPath($Root)
    if ($fullRoot.EndsWith([System.IO.Path]::DirectorySeparatorChar)) {
        $fullRoot = $fullRoot.Substring(0, $fullRoot.Length - 1)
    }
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $prefix = $fullRoot + [System.IO.Path]::DirectorySeparatorChar
    if (-not $fullPath.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Runtime-state paths must remain inside the repository."
    }
    return $fullPath.Substring($prefix.Length).Replace("\", "/")
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "git is required to install the pinned local D1 runtime."
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required to install the pinned local D1 runtime."
}
New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
New-Item -ItemType Directory -Path $modelRoot -Force | Out-Null

if (Test-Path -LiteralPath $runtimePath) {
    $runtimeCommit = (& git -C $runtimePath rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $runtimeCommit -ne $lock.decisionModel.runtimeRevision) {
        throw "Existing D1 runtime checkout differs from the pinned revision; it was left untouched."
    }
    $runtimeChanges = @(& git -C $runtimePath status --porcelain)
    if ($runtimeChanges.Count -gt 0) {
        throw "Existing D1 runtime checkout has local changes; it was left untouched."
    }
} else {
    Invoke-Checked -File git -Arguments @("clone", "--no-checkout", $lock.decisionModel.runtimeRepository, $runtimePath)
    Invoke-Checked -File git -Arguments @("-C", $runtimePath, "fetch", "--depth", "1", "origin", $lock.decisionModel.runtimeRevision)
    Invoke-Checked -File git -Arguments @("-C", $runtimePath, "checkout", "--detach", $lock.decisionModel.runtimeRevision)
}

$runtimeCommit = (& git -C $runtimePath rev-parse HEAD).Trim()
if ($runtimeCommit -ne $lock.decisionModel.runtimeRevision) {
    throw "D1 runtime revision verification failed."
}

$env:UV_CACHE_DIR = Join-Path $repoRoot "Assets/_Local/.uv-cache"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $repoRoot "Assets/_Local/.uv-python"
$env:UV_PROJECT_ENVIRONMENT = Join-Path $runtimePath ".venv"
$env:HF_HOME = Join-Path $repoRoot "Assets/_Local/booth-audit/hf-cache"
$env:HF_HUB_DISABLE_TELEMETRY = "1"
Invoke-Checked -File uv -Arguments @(
    "sync", "--project", $runtimePath, "--locked", "--no-dev", "--python", $lock.decisionModel.runtimePython
)

$includePatterns = @(
    "*.py",
    "*.json",
    "*.jinja",
    "LICENSE",
    "README.md",
    "onnx/decoder_q4.onnx",
    "onnx/decoder_q4.onnx_data",
    "onnx/vision_encoder_q8.onnx",
    "onnx/vision_encoder_q8.onnx_data"
)
$downloadArgs = @(
    "run", "--project", $runtimePath, "--locked", "--no-dev", "hf", "download",
    $lock.decisionModel.repository,
    "--revision", $lock.decisionModel.revision,
    "--local-dir", $modelPath
)
foreach ($pattern in $includePatterns) {
    $downloadArgs += @("--include", $pattern)
}
Invoke-Checked -File uv -Arguments $downloadArgs

$requiredFiles = @(
    "config.json",
    "processor_config.json",
    "tokenizer.json",
    "runner.py",
    "prompt.py",
    "onnx/decoder_q4.onnx",
    "onnx/decoder_q4.onnx_data",
    "onnx/vision_encoder_q8.onnx",
    "onnx/vision_encoder_q8.onnx_data"
)
foreach ($relativeFile in $requiredFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $modelPath $relativeFile) -PathType Leaf)) {
        throw "Pinned D1 model is incomplete: missing $relativeFile"
    }
}

$d1Cli = Join-Path $runtimePath ".venv/Scripts/d1-infer.exe"
if (-not (Test-Path -LiteralPath $d1Cli -PathType Leaf)) {
    $d1Cli = Join-Path $runtimePath ".venv/Scripts/d1-infer"
}
if (-not (Test-Path -LiteralPath $d1Cli -PathType Leaf)) {
    throw "uv installed the runtime but the d1-infer entry point is missing."
}
Invoke-Checked -File $d1Cli -Arguments @("--help")

$runtimeStatePath = Join-Path $repoRoot ".image2outfit/booth-audit/runtime-state.json"
New-Item -ItemType Directory -Path (Split-Path -Parent $runtimeStatePath) -Force | Out-Null
$weightState = @()
foreach ($relativeFile in @("onnx/decoder_q4.onnx_data", "onnx/vision_encoder_q8.onnx_data")) {
    $path = Join-Path $modelPath $relativeFile
    $weightState += [ordered]@{
        path = $relativeFile
        bytes = (Get-Item -LiteralPath $path).Length
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
    }
}
$runtimeState = [ordered]@{
    state = "installed_candidate_unbenchmarked"
    installedAtUtc = [DateTime]::UtcNow.ToString("o")
    runtimeRevision = $runtimeCommit
    modelRepository = $lock.decisionModel.repository
    modelRevision = $lock.decisionModel.revision
    precision = $lock.decisionModel.precision
    executionProvider = $lock.decisionModel.executionProvider
    runtimePath = Get-RepositoryRelativePath -Root $repoRoot -Path $runtimePath
    modelPath = Get-RepositoryRelativePath -Root $repoRoot -Path $modelPath
    weights = $weightState
}
[System.IO.File]::WriteAllText(
    $runtimeStatePath,
    (($runtimeState | ConvertTo-Json -Depth 8) + "`n"),
    [System.Text.UTF8Encoding]::new($false)
)
Write-Output "Installed pinned D1-2B ONNX candidate."
Write-Output "Runtime: $runtimeCommit"
Write-Output "Model: $($lock.decisionModel.revision) ($($lock.decisionModel.precision), CPU)"
Write-Output "State: $runtimeStatePath"
