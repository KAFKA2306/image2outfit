param()

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ConfigPath = Join-Path $RepoRoot "config\oss-runtimes\garmentcode-pygarment.json"
$Config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$RuntimePath = Join-Path $RepoRoot $Config.runtimePath
$Revision = [string]$Config.upstreamRevision
$PythonVersion = [string]$Config.pythonVersion
$LockPath = Join-Path $RepoRoot $Config.requirementsLockPath

$RuntimeParent = Split-Path -Parent $RuntimePath
New-Item -ItemType Directory -Force -Path $RuntimeParent | Out-Null
$env:UV_CACHE_DIR = Join-Path $RepoRoot ".image2outfit\oss-runtimes\.uv-cache"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $RepoRoot ".image2outfit\oss-runtimes\.uv-python"
New-Item -ItemType Directory -Force -Path $env:UV_CACHE_DIR, $env:UV_PYTHON_INSTALL_DIR | Out-Null

if (-not (Test-Path -LiteralPath (Join-Path $RuntimePath ".git"))) {
    if (Test-Path -LiteralPath $RuntimePath) {
        throw "GarmentCode runtime path exists without Git metadata; refusing to replace it: $RuntimePath"
    }
    git clone --no-checkout $Config.upstreamRepository $RuntimePath
    if ($LASTEXITCODE -ne 0) { throw "GarmentCode clone failed with exit code $LASTEXITCODE" }
    git -C $RuntimePath checkout --detach $Revision
    if ($LASTEXITCODE -ne 0) { throw "GarmentCode checkout failed with exit code $LASTEXITCODE" }
}

$ActualRevision = (git -C $RuntimePath rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw "Could not inspect GarmentCode checkout: $RuntimePath" }
if ($ActualRevision -ne $Revision) {
    throw "GarmentCode checkout revision mismatch; expected $Revision, found $ActualRevision"
}

uv python find $PythonVersion --no-project *> $null
if ($LASTEXITCODE -ne 0) {
    uv python install $PythonVersion
    if ($LASTEXITCODE -ne 0) { throw "Could not install Python $PythonVersion" }
}
$VenvPath = Join-Path $RuntimePath ".venv"
$PreviousLocation = Get-Location
try {
    Set-Location -LiteralPath $RuntimePath
    uv venv --allow-existing --no-project --python $PythonVersion .venv
} finally {
    Set-Location -LiteralPath $PreviousLocation
}
if ($LASTEXITCODE -ne 0) { throw "Could not prepare the isolated GarmentCode environment" }
$Python = Join-Path $VenvPath "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Expected Windows Python executable was not created: $Python"
}
uv pip sync --python $Python $LockPath
if ($LASTEXITCODE -ne 0) { throw "Could not install the locked GarmentCode dependencies" }

$env:PYTHONPATH = $RuntimePath
& $Python -c "import sys; from pygarment.pattern.wrappers import VisPattern; import cairosvg; assert sys.version.split()[0] == '$PythonVersion'; print(sys.version.split()[0], VisPattern.__name__, cairosvg.__version__)"
if ($LASTEXITCODE -ne 0) { throw "GarmentCode runtime health check failed" }

Write-Output "GarmentCode is ready at pinned revision $Revision with Python $PythonVersion."
