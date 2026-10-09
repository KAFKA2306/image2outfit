param()

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ConfigPath = Join-Path $RepoRoot "config\oss-runtimes\opensew-2-blender.json"
$Config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
if ($Config.schemaVersion -ne 1 -or $Config.outputMode -ne "2d-panel-mesh-only" -or $Config.threeDEnabled -ne $false) {
    throw "OpenSew runtime config must pin its 2D-only boundary."
}

$RuntimePath = Join-Path $RepoRoot $Config.runtimePath
$RuntimeParent = Split-Path -Parent $RuntimePath
New-Item -ItemType Directory -Force -Path $RuntimeParent | Out-Null
if (-not (Test-Path -LiteralPath (Join-Path $RuntimePath ".git"))) {
    if (Test-Path -LiteralPath $RuntimePath) {
        throw "OpenSew runtime path exists without Git metadata; refusing to replace it: $RuntimePath"
    }
    git clone --no-checkout $Config.upstreamRepository $RuntimePath
    if ($LASTEXITCODE -ne 0) { throw "OpenSew clone failed with exit code $LASTEXITCODE" }
    git -C $RuntimePath checkout --detach $Config.upstreamRevision
    if ($LASTEXITCODE -ne 0) { throw "OpenSew checkout failed with exit code $LASTEXITCODE" }
}

$ActualRepository = (git -C $RuntimePath remote get-url origin).Trim()
if ($LASTEXITCODE -ne 0 -or $ActualRepository -ne [string]$Config.upstreamRepository) {
    throw "OpenSew remote does not match the pinned source repository: $ActualRepository"
}
$ActualRevision = (git -C $RuntimePath rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $ActualRevision -ne [string]$Config.upstreamRevision) {
    throw "OpenSew revision mismatch; expected $($Config.upstreamRevision), found $ActualRevision"
}
$GitStatus = git -C $RuntimePath status --porcelain
if ($LASTEXITCODE -ne 0 -or $GitStatus) {
    throw "OpenSew checkout has local changes; refusing to alter or use it as pinned source."
}
$LicensePath = Join-Path $RuntimePath "LICENSE"
if (-not (Test-Path -LiteralPath $LicensePath)) {
    throw "OpenSew license file is missing: $LicensePath"
}

$ArchivePath = Join-Path $RepoRoot $Config.blenderArchivePath
$ArchiveParent = Split-Path -Parent $ArchivePath
New-Item -ItemType Directory -Force -Path $ArchiveParent | Out-Null
if (-not (Test-Path -LiteralPath $ArchivePath)) {
    $TempArchive = "$ArchivePath.$([guid]::NewGuid().ToString('N')).download"
    try {
        Invoke-WebRequest -Uri $Config.blenderArchiveUrl -OutFile $TempArchive
        $TempHash = (Get-FileHash -LiteralPath $TempArchive -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($TempHash -ne [string]$Config.blenderArchiveSha256) {
            throw "Blender archive checksum mismatch: $TempHash"
        }
        Move-Item -LiteralPath $TempArchive -Destination $ArchivePath
    } finally {
        if (Test-Path -LiteralPath $TempArchive) {
            Remove-Item -LiteralPath $TempArchive
        }
    }
}
$ArchiveHash = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($ArchiveHash -ne [string]$Config.blenderArchiveSha256) {
    throw "Blender archive checksum mismatch: expected $($Config.blenderArchiveSha256), found $ArchiveHash"
}

$ExtractRoot = Join-Path $RepoRoot $Config.blenderExtractRoot
$BlenderPath = Join-Path $RepoRoot $Config.blenderExecutable
if (-not (Test-Path -LiteralPath $BlenderPath)) {
    if (Test-Path -LiteralPath $ExtractRoot) {
        throw "Blender extraction path exists without the pinned executable; refusing to overwrite it: $ExtractRoot"
    }
    Expand-Archive -LiteralPath $ArchivePath -DestinationPath $ExtractRoot
}
if (-not (Test-Path -LiteralPath $BlenderPath)) {
    throw "Pinned Blender executable was not created: $BlenderPath"
}
$VersionOutput = (& $BlenderPath --background --version 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0 -or $VersionOutput -notmatch "(?m)^Blender $([regex]::Escape([string]$Config.blenderVersion))(?:\s|$)") {
    throw "Blender version does not match the pinned runtime $($Config.blenderVersion): $VersionOutput"
}

Write-Output "OpenSew is ready at $ActualRevision; Blender $($Config.blenderVersion) archive SHA-256 verified."
