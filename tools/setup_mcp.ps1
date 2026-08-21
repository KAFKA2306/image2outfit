[CmdletBinding()]
param(
    [switch]$DoctorOnly,
    [switch]$Force,
    [switch]$SkipUnityRegistration
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$StateRoot = Join-Path $RepoRoot ".image2outfit\mcp"
$BlenderStateRoot = Join-Path $StateRoot "blender-mcp"
$BlenderAddonPath = Join-Path $BlenderStateRoot "addon.py"
$BlenderManifestPath = Join-Path $BlenderStateRoot "provenance.json"

$BlenderMcpVersion = "1.8.0"
$BlenderMcpPython = "3.11"
$BlenderMcpCommit = "3ab892510cc0e5435ba5e611c01fb1021fbde8de"
$BlenderAddonUrl = "https://raw.githubusercontent.com/ahujasid/blender-mcp/$BlenderMcpCommit/addon.py"
$UnityMcpVersion = "10.1.2"
$UnityMcpPackageUrl = "https://github.com/CoplayDev/unity-mcp.git?path=/MCPForUnity#v$UnityMcpVersion"
$UnityMcpUrl = "http://127.0.0.1:8080/mcp"
$BlenderCodexServerName = "image2outfit-blender"
$UnityCodexServerName = "image2outfit-unity"

function Test-Executable {
    param([Parameter(Mandatory = $true)][string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
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
        if (-not $task.Wait($TimeoutMs)) {
            return $false
        }
        return $client.Connected
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Get-CodexMcpRegistration {
    param([Parameter(Mandatory = $true)][string]$Name)

    if (-not (Test-Executable "codex")) {
        return $null
    }

    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & codex mcp get $Name --json 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $output) {
            return $null
        }
        return ($output | Out-String | ConvertFrom-Json)
    }
    catch {
        return $null
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Remove-CodexMcpRegistration {
    param([Parameter(Mandatory = $true)][string]$Name)

    & codex mcp remove $Name
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to remove existing Codex MCP server '$Name'."
    }
}

function Get-UnityMcpDetected {
    $manifestPath = Join-Path $RepoRoot "Packages\manifest.json"
    if (Test-Path $manifestPath) {
        $manifestText = Get-Content -Raw -LiteralPath $manifestPath
        if ($manifestText -match 'com\.coplaydev\.unity-mcp') {
            return $true
        }
    }

    $packageCache = Join-Path $RepoRoot "Library\PackageCache"
    if (Test-Path $packageCache) {
        $resolved = Get-ChildItem -LiteralPath $packageCache -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like "com.coplaydev.unity-mcp*" } |
            Select-Object -First 1
        if ($null -ne $resolved) {
            return $true
        }
    }

    return $false
}

function Get-UnityProjectVersion {
    $versionPath = Join-Path $RepoRoot "ProjectSettings\ProjectVersion.txt"
    if (-not (Test-Path $versionPath)) {
        return $null
    }

    $line = Get-Content -LiteralPath $versionPath |
        Where-Object { $_ -match '^m_EditorVersion:\s*(.+)$' } |
        Select-Object -First 1
    if ($line -and $line -match '^m_EditorVersion:\s*(.+)$') {
        return $Matches[1].Trim()
    }
    return $null
}

function Invoke-McpDoctor {
    $blenderRegistration = Get-CodexMcpRegistration -Name $BlenderCodexServerName
    $unityRegistration = Get-CodexMcpRegistration -Name $UnityCodexServerName
    $report = [ordered]@{
        repoRoot = $RepoRoot
        codexAvailable = (Test-Executable "codex")
        uvxAvailable = (Test-Executable "uvx")
        blenderMcpRegistered = ($null -ne $blenderRegistration)
        unityMcpRegistered = ($null -ne $unityRegistration)
        blenderPort9876Listening = (Test-LoopbackPort -Port 9876)
        unityPort8080Listening = (Test-LoopbackPort -Port 8080)
        blenderAddonDownloaded = (Test-Path $BlenderAddonPath)
        blenderAddonPath = $BlenderAddonPath
        blenderMcpPython = $BlenderMcpPython
        expectedBlenderTelemetryDisabled = $true
        unityMcpPackageDetected = (Get-UnityMcpDetected)
        unityMcpExpectedVersion = $UnityMcpVersion
        unityProjectVersion = (Get-UnityProjectVersion)
        unityMcpPackageUrl = $UnityMcpPackageUrl
        unityMcpUrl = $UnityMcpUrl
    }

    if ($null -ne $blenderRegistration) {
        $report["blenderMcpRegistration"] = $blenderRegistration
    }
    if ($null -ne $unityRegistration) {
        $report["unityMcpRegistration"] = $unityRegistration
    }

    return [pscustomobject]$report
}

if ($DoctorOnly) {
    Invoke-McpDoctor | ConvertTo-Json -Depth 10
    exit 0
}

if (-not (Test-Path (Join-Path $RepoRoot "AGENTS.md"))) {
    throw "Repository root was not resolved correctly: $RepoRoot"
}
if (-not (Test-Executable "codex")) {
    throw "codex was not found on PATH. Install/update OpenAI Codex before running this setup."
}
if (-not (Test-Executable "uvx")) {
    throw "uvx was not found on PATH. Install uv before running this setup."
}

New-Item -ItemType Directory -Force -Path $BlenderStateRoot | Out-Null

Write-Host "Downloading pinned Blender MCP addon from commit $BlenderMcpCommit ..."
Invoke-WebRequest -UseBasicParsing -Uri $BlenderAddonUrl -OutFile $BlenderAddonPath
$addonHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $BlenderAddonPath).Hash.ToLowerInvariant()

$provenance = [ordered]@{
    schemaVersion = 1
    downloadedAtUtc = [DateTime]::UtcNow.ToString("o")
    upstream = "https://github.com/ahujasid/blender-mcp"
    serverVersion = $BlenderMcpVersion
    python = $BlenderMcpPython
    commit = $BlenderMcpCommit
    addonUrl = $BlenderAddonUrl
    addonSha256 = $addonHash
    telemetryDisabled = $true
}
$provenance | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $BlenderManifestPath -Encoding UTF8

$existingBlender = Get-CodexMcpRegistration -Name $BlenderCodexServerName
if ($null -ne $existingBlender -and $Force) {
    Write-Host "Replacing Codex MCP server '$BlenderCodexServerName' ..."
    Remove-CodexMcpRegistration -Name $BlenderCodexServerName
    $existingBlender = $null
}
if ($null -eq $existingBlender) {
    Write-Host "Registering pinned Blender MCP server with Codex ..."
    & codex mcp add $BlenderCodexServerName `
        --env "BLENDER_HOST=localhost" `
        --env "BLENDER_PORT=9876" `
        --env "UV_PYTHON_PREFERENCE=only-managed" `
        --env "DISABLE_TELEMETRY=true" `
        -- cmd /c uvx --python $BlenderMcpPython "blender-mcp==$BlenderMcpVersion"
    if ($LASTEXITCODE -ne 0) {
        throw "codex mcp add failed for '$BlenderCodexServerName'."
    }
}
else {
    Write-Host "Codex MCP server '$BlenderCodexServerName' already exists; use -Force to replace it."
}

if (-not $SkipUnityRegistration) {
    $existingUnity = Get-CodexMcpRegistration -Name $UnityCodexServerName
    if ($null -ne $existingUnity -and $Force) {
        Write-Host "Replacing Codex MCP server '$UnityCodexServerName' ..."
        Remove-CodexMcpRegistration -Name $UnityCodexServerName
        $existingUnity = $null
    }
    if ($null -eq $existingUnity) {
        Write-Host "Registering Unity MCP HTTP endpoint with Codex ..."
        & codex mcp add $UnityCodexServerName --url $UnityMcpUrl
        if ($LASTEXITCODE -ne 0) {
            throw "codex mcp add failed for '$UnityCodexServerName'."
        }
    }
    else {
        Write-Host "Codex MCP server '$UnityCodexServerName' already exists; use -Force to replace it."
    }
}

Write-Host ""
Write-Host "Blender addon prepared at:"
Write-Host "  $BlenderAddonPath"
Write-Host ""
Write-Host "Unity MCP package is an explicit local Unity-package action:"
Write-Host "  $UnityMcpPackageUrl"
Write-Host "Then use: Window > MCP for Unity > Configure All Detected Clients"
Write-Host "and start the local HTTP transport on 127.0.0.1:8080."
Write-Host ""
Write-Host "Run Blender 4.4.3, enable Blender MCP, and start its localhost:9876 server."
Write-Host "Optional Image2Outfit sidebar addon: tools\blender_addons\image2outfit_assistant.py"
Write-Host ""

Invoke-McpDoctor | ConvertTo-Json -Depth 10
