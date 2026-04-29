param(
    [Parameter(Mandatory = $true)]
    [string]$ServerHost,

    [string]$ServerUser = "root",
    [string]$RemoteRoot = "/home/bylou/xuebao",
    [int]$SshPort = 22,
    [string]$SshKeyPath = "",
    [switch]$AllowDirtyWorktree,
    [switch]$PromptOnDirtyWorktree,
    [switch]$SkipDeploy,
    [switch]$DisableSshKey
)

$ErrorActionPreference = "Stop"
if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}

function Require-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $Name"
    }
}

function Get-RepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

function Resolve-SshKeyPath {
    param([string]$ConfiguredPath)

    $candidates = @()
    if ($ConfiguredPath) {
        $candidates += $ConfiguredPath
    }
    $candidates += (Join-Path $HOME ".ssh\xuebao_selfhost_ed25519")
    $candidates += (Join-Path $HOME ".ssh\learningpyramid_selfhost_ed25519")

    foreach ($candidate in $candidates) {
        if (-not $candidate) {
            continue
        }
        if (Test-Path -LiteralPath $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    return $null
}

function Assert-CleanGitWorktree {
    param(
        [string]$RepoRoot,
        [switch]$AllowDirty,
        [switch]$PromptOnDirty
    )

    if ($AllowDirty) {
        return
    }
    if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot ".git"))) {
        return
    }

    $statusLines = @(& git -C $RepoRoot status --short 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "git status failed: $($statusLines -join [Environment]::NewLine)"
    }
    if ($statusLines.Count -eq 0) {
        return
    }

    $preview = ($statusLines | Select-Object -First 30) -join [Environment]::NewLine
    if ($PromptOnDirty) {
        Write-Warning "Git worktree is dirty. This deploy pulls origin/main on the server; uncommitted local changes are not included unless already pushed."
        Write-Host $preview
        $confirmation = Read-Host "Continue deploy anyway? [y/N]"
        if ($confirmation -match '^(?i:y|yes)$') {
            return
        }
        throw "Deploy cancelled because git worktree is dirty."
    }

    throw "Git worktree is dirty. Commit or stash changes before deploying, or rerun with -AllowDirtyWorktree.`n$preview"
}

function ConvertTo-ShellSingleQuoted {
    param([string]$Value)
    return "'" + ($Value -replace "'", "'\''") + "'"
}

function Invoke-ExternalCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Description,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $outputLines = @(& $Command 2>&1)
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    foreach ($line in $outputLines) {
        if ($null -ne $line) {
            Write-Host $line
        }
    }

    if ($exitCode -ne 0) {
        throw "$Description failed with exit code $exitCode."
    }
}

Require-Command git
Require-Command ssh

$repoRoot = Get-RepoRoot
Assert-CleanGitWorktree -RepoRoot $repoRoot -AllowDirty:$AllowDirtyWorktree -PromptOnDirty:$PromptOnDirtyWorktree

$sshArgs = @(
    "-p", "$SshPort",
    "-o", "ServerAliveInterval=15",
    "-o", "ServerAliveCountMax=8",
    "-o", "TCPKeepAlive=yes",
    "-o", "ConnectTimeout=15",
    "-o", "StrictHostKeyChecking=accept-new"
)

if (-not $DisableSshKey) {
    $resolvedSshKeyPath = Resolve-SshKeyPath -ConfiguredPath $SshKeyPath
    if (-not $resolvedSshKeyPath) {
        throw "No SSH key found. Provide -SshKeyPath or create ~/.ssh/xuebao_selfhost_ed25519."
    }
    $sshArgs += @("-i", $resolvedSshKeyPath, "-o", "IdentitiesOnly=yes")
    Write-Host "SSH key: $resolvedSshKeyPath"
}
else {
    Write-Host "SSH key disabled; SSH may prompt for password."
}

$destination = "${ServerUser}@${ServerHost}"
$remoteRootQuoted = ConvertTo-ShellSingleQuoted -Value $RemoteRoot
$deployCommand = if ($SkipDeploy) {
    "echo 'Skipping scripts/deploy.sh because -SkipDeploy was set.'"
}
else {
    "scripts/deploy.sh"
}

$remoteScript = @"
set -eu
REMOTE_ROOT=$remoteRootQuoted

retry() {
  desc="`$1"
  shift
  attempt=1
  while :; do
    if "`$@"; then
      return 0
    else
      code="`$?"
    fi
    if [ "`$attempt" -ge 6 ]; then
      echo "`$desc failed after `$attempt attempts." >&2
      return "`$code"
    fi
    echo "`$desc failed on attempt `$attempt/6; retrying in 3s..." >&2
    attempt=`$((attempt + 1))
    sleep 3
  done
}

cd "`$REMOTE_ROOT"
echo "Remote path: `$REMOTE_ROOT"
echo "Before: `$(git rev-parse --short HEAD)"
retry "git fetch" timeout 60s git fetch --prune origin || exit "`$?"
git checkout main
retry "git pull" timeout 60s git pull --ff-only origin main || exit "`$?"
chmod +x scripts/deploy.sh scripts/validate-deploy-env.sh scripts/backup-data.sh
echo "After: `$(git rev-parse --short HEAD)"
$deployCommand
docker compose ps
"@

$remoteScript = $remoteScript -replace "`r", ""
$remoteScriptBase64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($remoteScript))

Write-Host "Checking SSH authentication..."
Invoke-ExternalCommand -Description "SSH authentication check" -Command {
    & ssh @sshArgs $destination "printf 'ssh-ok\n'"
}

Write-Host "Syncing and deploying on server..."
Invoke-ExternalCommand -Description "Remote sync and deploy" -Command {
    & ssh @sshArgs $destination "printf '%s' '$remoteScriptBase64' | base64 -d | bash"
}

Write-Host ""
Write-Host "Deploy finished."
Write-Host "Server: $destination"
Write-Host "Remote path: $RemoteRoot"
