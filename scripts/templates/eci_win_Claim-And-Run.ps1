# eci_win_Claim-And-Run.ps1 â€” Template (copy to Dropbox\Automation\.queue\Claim-And-Run.ps1)
# Purpose: Minimal ECI worker for Windows. Claims only jobs targeted to this machine.
# Identity source: C:\temp\MACHINE_ID.txt (first non-empty line).
param(
  [string]$QueueRoot = (Join-Path $env:USERPROFILE 'Dropbox\Automation\.queue')
)

# 1) Determine local machine_id (from MACHINE_ID.txt, then env, then hostname)
$idFile = 'C:\temp\MACHINE_ID.txt'
if (Test-Path $idFile) {
    $machineId = Get-Content $idFile | Where-Object { $_.Trim() -ne "" } | Select-Object -First 1
    $machineId = $machineId.Trim()
} else {
    $machineId = $env:KG_PLATFORM
    if (-not $machineId -or $machineId -eq '') { $machineId = $env:COMPUTERNAME }
}

$inbox   = Join-Path $QueueRoot 'inbox'
$claimed = Join-Path $QueueRoot 'claimed'
$done    = Join-Path $QueueRoot 'done'
$events  = Join-Path $QueueRoot 'events'
New-Item -ItemType Directory -Force -Path $claimed,$done,$events | Out-Null

# 2) First job in inbox
$jobFile = Get-ChildItem -Path $inbox -Filter '*.json' -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $jobFile) { Write-Host "No jobs."; exit 0 }

# 3) Check targeting
try {
  $job = Get-Content $jobFile.FullName -Raw | ConvertFrom-Json
} catch {
  Write-Warning "Bad JSON: $($jobFile.Name) â€” skipping."
  exit 0
}
$targets = @()
if ($job.PSObject.Properties.Name -contains 'requested_executor') { $targets = $job.requested_executor }
$eligible = ($targets.Count -eq 0) -or ($targets -contains $machineId)
if (-not $eligible) { Write-Host "Skipping (not targeted for $machineId): $($job.id)"; exit 0 }

# 4) Claim & minimal work
$base = $jobFile.Name
$claimedPath = Join-Path $claimed $base
Move-Item -Path $jobFile.FullName -Destination $claimedPath -Force

$evt = Join-Path $events ($job.id + '.log')
"$(Get-Date -AsUTC -Format o)  CLAIM  $machineId" | Out-File -Append $evt -Encoding utf8
Start-Sleep -Seconds 2
"$(Get-Date -AsUTC -Format o)  DONE   $machineId"  | Out-File -Append $evt -Encoding utf8
Move-Item -Path $claimedPath -Destination (Join-Path $done $base) -Force
Write-Host "Job completed: $($job.id) on $machineId"

