[CmdletBinding()]
param(
    [switch]$DoctorOnly,
    [switch]$Force,
    [switch]$SkipUnityRegistration
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ContractPath = Join-Path $RepoRoot "config\mcp-authoring.json"
$Contract = Get-Content -Raw -LiteralPath $ContractPath | ConvertFrom-Json
$StateRoot = Join-Path $RepoRoot ($Contract.stateRoot -replace '/', '\')
$BlenderStateRoot = Join-Path $StateRoot "blender-mcp"
$BlenderAddonPath = Join-Path $BlenderStateRoot "addon.py"
$BlenderManifestPath = Join-Path $BlenderStateRoot "provenance.json"

$BlenderMcpVersion = [string]$Contract.blender.version
$BlenderMcpPython = [string]$Contract.blender.python
$BlenderMcpCommit = [string]$Contract.blender.commit
$BlenderAddonUrl = [string]$Contract.blender.addonUrl
$BlenderAddonGitBlobSha1 = [string]$Contract.blender.addonGitBlobSha1
$BlenderHost = [string]$Contract.blender.host
$BlenderPort = [int]$Contract.blender.port
$UnityMcpVersion = [string]$Contract.unity.version
$UnityMcpPackageUrl = [string]$Contract.unity.packageUrl
$UnityMcpUrl = [string]$Contract.unity.url
$UnityHost = [string]$Contract.unity.host
$UnityPort = [int]$Contract.unity.port
$BlenderCodexServerName = [string]$Contract.blender.serverName
$UnityCodexServerName = [string]$Contract.unity.serverName

function Test-Executable {
    param([Parameter(Mandatory = $true)][string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-LoopbackHost {
    param([Parameter(Mandatory = $true)][string]$HostName)
    return $HostName -in @("localhost", "127.0.0.1", "::1")
}

function Test-LoopbackPort {
    param(
        [string]$HostName = "127.0.0.1",
        [int]$Port,
        [int]$TimeoutMs = 500
    )
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $task = $client.ConnectAsync($HostName, $Port)
        if (-not $task.Wait($TimeoutMs)) { return $false }
        return $client.Connected
    }
    catch { return $false }
    finally { $client.Dispose() }
}

function Get-GitBlobSha1 {
    param([Parameter(Mandatory = $true)][string]$Path)
    [byte[]]$content = [System.IO.File]::ReadAllBytes($Path)
    [byte[]]$header = [System.Text.Encoding]::UTF8.GetBytes("blob $($content.Length)`0")
    [byte[]]$payload = New-Object byte[] ($header.Length + $content.Length)
    [Array]::Copy($header, 0, $payload, 0, $header.Length)
    [Array]::Copy($content, 0, $payload, $header.Length, $content.Length)
    $sha1 = [System.Security.Cryptography.SHA1]::Create()
    try {
        return ([BitConverter]::ToString($sha1.ComputeHash($payload))).Replace("-", "").ToLowerInvariant()
    }
    finally { $sha1.Dispose() }
}

function Get-CodexMcpRegistration {
    param([Parameter(Mandatory = $true)][string]$Name)
    if (-not (Test-Executable "codex")) { return $null }
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & codex mcp get $Name --json 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $output) { return $null }
        return ($output | Out-String | ConvertFrom-Json)
    }
    catch { return $null }
    finally { $ErrorActionPreference = $previousPreference }
}

function Remove-CodexMcpRegistration {
    param([Parameter(Mandatory = $true)][string]$Name)
    & codex mcp remove $Name
    if ($LASTEXITCODE -ne 0) { throw "Failed to remove existing Codex MCP server '$Name'." }
}

function Test-RegistrationContains {
    param(
        [object]$Registration,
        [Parameter(Mandatory = $true)][string[]]$RequiredTokens
    )
    if ($null -eq $Registration) { return $false }
    $text = $Registration | ConvertTo-Json -Depth 20 -Compress
    foreach ($token in $RequiredTokens) {
        if ($text.IndexOf($token, [StringComparison]::OrdinalIgnoreCase) -lt 0) { return $false }
    }
    return $true
}

function Get-UnityMcpDetected {
    $manifestPath = Join-Path $RepoRoot "Packages\manifest.json"
    if (Test-Path $manifestPath) {
        $manifestText = Get-Content -Raw -LiteralPath $manifestPath
        if ($manifestText -match [regex]::Escape([string]$Contract.unity.packageId)) { return $true }
    }
    $packageCache = Join-Path $RepoRoot "Library\PackageCache"
    if (Test-Path $packageCache) {
        $resolved = Get-ChildItem -LiteralPath $packageCache -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like "$($Contract.unity.packageId)*" } |
            Select-Object -First 1
        if ($null -ne $resolved) { return $true }
    }
    return $false
}

function Get-UnityProjectVersion {
    $versionPath = Join-Path $RepoRoot ([string]$Contract.unity.projectVersionSource -replace '/', '\')
    if (-not (Test-Path $versionPath)) { return $null }
    $line = Get-Content -LiteralPath $versionPath |
        Where-Object { $_ -match '^m_EditorVersion:\s*(.+)$' } |
        Select-Object -First 1
    if ($line -and $line -match '^m_EditorVersion:\s*(.+)$') { return $Matches[1].Trim() }
    return $null
}

function Test-BlenderAddonVerified {
    if (-not (Test-Path $BlenderAddonPath) -or -not (Test-Path $BlenderManifestPath)) { return $false }
    try {
        $provenance = Get-Content -Raw -LiteralPath $BlenderManifestPath | ConvertFrom-Json
        $actualBlob = Get-GitBlobSha1 -Path $BlenderAddonPath
        return (
            [string]$provenance.commit -eq $BlenderMcpCommit -and
            [string]$provenance.addonGitBlobSha1 -eq $BlenderAddonGitBlobSha1 -and
            $actualBlob -eq $BlenderAddonGitBlobSha1
        )
    }
    catch { return $false }
}

function Resolve-DoctorState {
    param(
        [bool]$PrerequisitesAvailable,
        [bool]$Configured,
        [bool]$Verified,
        [bool]$Reachable
    )
    if (-not $PrerequisitesAvailable -or -not $Configured) { return "UNAVAILABLE" }
    if (-not $Verified) { return "UNVERIFIED" }
    if ($Reachable) { return "REACHABLE" }
    return "CONFIGURED"
}

function Invoke-McpDoctor {
    $codexAvailable = Test-Executable "codex"
    $uvxAvailable = Test-Executable "uvx"
    $blenderRegistration = Get-CodexMcpRegistration -Name $BlenderCodexServerName
    $unityRegistration = Get-CodexMcpRegistration -Name $UnityCodexServerName
    $unityProjectVersion = Get-UnityProjectVersion

    $blenderRegistrationVerified = Test-RegistrationContains -Registration $blenderRegistration -RequiredTokens @(
        "blender-mcp==$BlenderMcpVersion", "BLENDER_HOST", $BlenderHost, "$BlenderPort", "DISABLE_TELEMETRY", "true"
    )
    $blenderArtifactVerified = Test-BlenderAddonVerified
    $blenderReachable = Test-LoopbackPort -HostName $BlenderHost -Port $BlenderPort
    $blenderState = Resolve-DoctorState `
        -PrerequisitesAvailable ($codexAvailable -and $uvxAvailable) `
        -Configured ($null -ne $blenderRegistration) `
        -Verified ($blenderRegistrationVerified -and $blenderArtifactVerified) `
        -Reachable $blenderReachable

    $unityRegistrationVerified = Test-RegistrationContains -Registration $unityRegistration -RequiredTokens @($UnityMcpUrl)
    $unityProjectCompatible = $unityProjectVersion -eq [string]$Contract.unity.expectedUnityVersion
    $unityPackageDetected = Get-UnityMcpDetected
    $unityReachable = Test-LoopbackPort -HostName $UnityHost -Port $UnityPort
    $unityState = Resolve-DoctorState `
        -PrerequisitesAvailable $codexAvailable `
        -Configured ($null -ne $unityRegistration) `
        -Verified ($unityRegistrationVerified -and $unityProjectCompatible) `
        -Reachable $unityReachable

    return [pscustomobject][ordered]@{
        schemaVersion = 1
        repoRoot = $RepoRoot
        contractPath = $ContractPath
        mutatesProductState = $false
        stateSemantics = [ordered]@{
            CONFIGURED = "Pinned configuration is verified; editor endpoint is not currently reachable."
            REACHABLE = "Pinned configuration is verified and the loopback editor endpoint is reachable."
            UNAVAILABLE = "A required local prerequisite or Codex registration is absent."
            UNVERIFIED = "Configuration exists but pin, identity, security, or compatibility could not be proven."
        }
        blender = [ordered]@{
            state = $blenderState
            codexAvailable = $codexAvailable
            uvxAvailable = $uvxAvailable
            registered = ($null -ne $blenderRegistration)
            registrationVerified = $blenderRegistrationVerified
            addonDownloaded = (Test-Path $BlenderAddonPath)
            addonIdentityVerified = $blenderArtifactVerified
            expectedAddonGitBlobSha1 = $BlenderAddonGitBlobSha1
            reachable = $blenderReachable
            host = $BlenderHost
            port = $BlenderPort
        }
        unity = [ordered]@{
            state = $unityState
            codexAvailable = $codexAvailable
            registered = ($null -ne $unityRegistration)
            registrationVerified = $unityRegistrationVerified
            packageDetected = $unityPackageDetected
            expectedPackageVersion = $UnityMcpVersion
            projectVersion = $unityProjectVersion
            projectVersionCompatible = $unityProjectCompatible
            reachable = $unityReachable
            url = $UnityMcpUrl
        }
    }
}

if (-not [bool]$Contract.security.loopbackOnly -or -not (Test-LoopbackHost $BlenderHost) -or -not (Test-LoopbackHost $UnityHost)) {
    throw "MCP contract violates the loopback-only security boundary."
}
if ([bool]$Contract.affectsProductCompletion) {
    throw "MCP authoring contract must not affect product COMPLETE."
}

if ($DoctorOnly) {
    Invoke-McpDoctor | ConvertTo-Json -Depth 10
    exit 0
}

if (-not (Test-Path (Join-Path $RepoRoot "AGENTS.md"))) { throw "Repository root was not resolved correctly: $RepoRoot" }
if (-not (Test-Executable "codex")) { throw "codex was not found on PATH. Install/update OpenAI Codex before running this setup." }
if (-not (Test-Executable "uvx")) { throw "uvx was not found on PATH. Install uv before running this setup." }
$projectVersion = Get-UnityProjectVersion
if ($projectVersion -and $projectVersion -ne [string]$Contract.unity.expectedUnityVersion) {
    throw "Unity project version '$projectVersion' is incompatible with MCP contract '$($Contract.unity.expectedUnityVersion)'."
}

New-Item -ItemType Directory -Force -Path $BlenderStateRoot | Out-Null
Write-Host "Downloading pinned Blender MCP addon from commit $BlenderMcpCommit ..."
Invoke-WebRequest -UseBasicParsing -Uri $BlenderAddonUrl -OutFile $BlenderAddonPath
$actualBlobSha1 = Get-GitBlobSha1 -Path $BlenderAddonPath
if ($actualBlobSha1 -ne $BlenderAddonGitBlobSha1) {
    Remove-Item -Force -LiteralPath $BlenderAddonPath
    throw "Pinned Blender MCP addon identity mismatch. Expected git blob $BlenderAddonGitBlobSha1, got $actualBlobSha1."
}
$addonSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $BlenderAddonPath).Hash.ToLowerInvariant()
$provenance = [ordered]@{
    schemaVersion = 2
    downloadedAtUtc = [DateTime]::UtcNow.ToString("o")
    upstream = [string]$Contract.blender.upstream
    serverVersion = $BlenderMcpVersion
    python = $BlenderMcpPython
    commit = $BlenderMcpCommit
    addonUrl = $BlenderAddonUrl
    addonGitBlobSha1 = $actualBlobSha1
    addonSha256 = $addonSha256
    telemetryDisabled = [bool]$Contract.blender.telemetryDisabled
}
$provenance | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $BlenderManifestPath -Encoding UTF8

$existingBlender = Get-CodexMcpRegistration -Name $BlenderCodexServerName
if ($null -ne $existingBlender -and $Force) {
    Remove-CodexMcpRegistration -Name $BlenderCodexServerName
    $existingBlender = $null
}
if ($null -eq $existingBlender) {
    & codex mcp add $BlenderCodexServerName `
        --env "BLENDER_HOST=$BlenderHost" `
        --env "BLENDER_PORT=$BlenderPort" `
        --env "UV_PYTHON_PREFERENCE=only-managed" `
        --env "DISABLE_TELEMETRY=true" `
        -- cmd /c uvx --python $BlenderMcpPython "blender-mcp==$BlenderMcpVersion"
    if ($LASTEXITCODE -ne 0) { throw "codex mcp add failed for '$BlenderCodexServerName'." }
}
elseif (-not (Test-RegistrationContains -Registration $existingBlender -RequiredTokens @("blender-mcp==$BlenderMcpVersion", $BlenderHost, "$BlenderPort"))) {
    throw "Existing '$BlenderCodexServerName' registration does not match the pinned contract. Re-run with -Force to replace it."
}

if (-not $SkipUnityRegistration) {
    $existingUnity = Get-CodexMcpRegistration -Name $UnityCodexServerName
    if ($null -ne $existingUnity -and $Force) {
        Remove-CodexMcpRegistration -Name $UnityCodexServerName
        $existingUnity = $null
    }
    if ($null -eq $existingUnity) {
        & codex mcp add $UnityCodexServerName --url $UnityMcpUrl
        if ($LASTEXITCODE -ne 0) { throw "codex mcp add failed for '$UnityCodexServerName'." }
    }
    elseif (-not (Test-RegistrationContains -Registration $existingUnity -RequiredTokens @($UnityMcpUrl))) {
        throw "Existing '$UnityCodexServerName' registration does not match the loopback contract. Re-run with -Force to replace it."
    }
}

Write-Host "Blender addon prepared at: $BlenderAddonPath"
Write-Host "Unity MCP package remains an explicit local Unity-package action: $UnityMcpPackageUrl"
Write-Host "Optional Image2Outfit sidebar addon: tools\blender_addons\image2outfit_assistant.py"
Invoke-McpDoctor | ConvertTo-Json -Depth 10
