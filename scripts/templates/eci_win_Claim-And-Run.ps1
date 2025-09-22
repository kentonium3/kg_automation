# eci_win_Claim-And-Run.ps1 — Template (copy to Scripts folder in PATH)
# Purpose: Minimal ECI worker for Windows. Claims only jobs targeted to this machine.
# Identity source: C:\temp\MACHINE_ID.txt (first non-empty line).

param(
    [string]$QueueRoot = ""
)

# Canonical roots (Windows)
$DropboxRoot = "$env:USERPROFILE\Dropbox"
$AutomationRoot = "$DropboxRoot\Automation"
# Global queue (cross-project)
if (-not $QueueRoot) {
    $QueueRoot = "$AutomationRoot\.queue"
}

# 1) Determine local machine_id (local-only; never in Dropbox)
$IdFile = "C:\temp\MACHINE_ID.txt"
if (Test-Path $IdFile) {
    $MachineId = (Get-Content $IdFile | Where-Object { $_.Trim() -ne "" } | Select-Object -First 1).Trim()
} else {
    $MachineId = if ($env:KG_PLATFORM) { $env:KG_PLATFORM } else { $env:COMPUTERNAME }
}

$Inbox = "$QueueRoot\inbox"
$Claimed = "$QueueRoot\claimed"
$Done = "$QueueRoot\done"
$Events = "$QueueRoot\events"

# Ensure directories exist
@($Claimed, $Done, $Events) | ForEach-Object {
    if (-not (Test-Path $_)) {
        New-Item -ItemType Directory -Path $_ -Force | Out-Null
    }
}

# 2) First job in inbox
$JobFile = Get-ChildItem -Path "$Inbox\*.json" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $JobFile) {
    Write-Host "No jobs."
    exit 0
}

# 3) Check targeting (reads requested_executor array)
$JobContent = Get-Content -Path $JobFile.FullName -Raw | ConvertFrom-Json
$Targets = $JobContent.requested_executor

$Eligible = $false
if (-not $Targets -or $Targets.Count -eq 0) {
    $Eligible = $true
} else {
    foreach ($Target in $Targets) {
        if ($Target -eq $MachineId) {
            $Eligible = $true
            break
        }
    }
}

if (-not $Eligible) {
    Write-Host "Skipping job (not targeted for $MachineId): $($JobFile.BaseName)"
    exit 0
}

# 4) Claim & minimal work
$Base = $JobFile.Name
$Timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")

Move-Item -Path $JobFile.FullName -Destination "$Claimed\$Base"
Add-Content -Path "$Events\$($JobFile.BaseName).log" -Value "$Timestamp  CLAIM  $MachineId"

Start-Sleep -Seconds 2

$Timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
Add-Content -Path "$Events\$($JobFile.BaseName).log" -Value "$Timestamp  DONE   $MachineId"
Move-Item -Path "$Claimed\$Base" -Destination "$Done\$Base"

Write-Host "Job completed: $($JobFile.BaseName) on $MachineId"
