<#
.SYNOPSIS
  Lists (and optionally terminates) orphaned QA-Again-owned Chromium
  processes on Windows.

.DESCRIPTION
  QA-Again's runner/recorder/verification code (see
  runner/src/browser/browserRun.ts and runner/scripts/lib/browserLifecycle.mjs)
  launches every headed Chromium instance with its own uniquely-named
  profile directory under the OS temp folder, prefixed
  "qa-again-playwright-". This script finds chrome.exe / msedge.exe
  processes whose command line references such a profile directory and
  reports them. It NEVER matches or terminates a chrome.exe process that
  does not reference one of these profile directories -- a tester's
  normal browser session is always left alone.

.PARAMETER Kill
  Also terminate the matched processes and remove their profile
  directories. Without this switch, the script only lists what it found
  (safe, read-only default).

.PARAMETER OlderThanMinutes
  Only act on processes whose profile directory is older than this many
  minutes (default 0 = no age filter). Useful to avoid racing a run that
  is still legitimately in progress.

.EXAMPLE
  .\cleanup-qa-again-browsers.ps1
    Lists any orphaned QA-Again Chromium processes without touching them.

.EXAMPLE
  .\cleanup-qa-again-browsers.ps1 -Kill -OlderThanMinutes 10
    Terminates and cleans up QA-Again Chromium processes whose profile
    directory is more than 10 minutes old.
#>
param(
  [switch]$Kill,
  [int]$OlderThanMinutes = 0
)

$ErrorActionPreference = "Stop"
$profileMarker = "qa-again-playwright-"

function Get-QaAgainOwnedProcesses {
  $processNames = @("chrome", "chromium", "msedge")
  $matches = @()
  foreach ($name in $processNames) {
    $procs = Get-CimInstance Win32_Process -Filter "Name = '$name.exe'" -ErrorAction SilentlyContinue
    foreach ($proc in $procs) {
      if ($proc.CommandLine -and $proc.CommandLine -match [regex]::Escape($profileMarker)) {
        $matches += $proc
      }
    }
  }
  return $matches
}

function Get-ProfileDirFromCommandLine {
  param([string]$CommandLine)
  if ($CommandLine -match "--user-data-dir=(`"[^`"]+`"|\S+)") {
    return $Matches[1].Trim('"')
  }
  return $null
}

$owned = Get-QaAgainOwnedProcesses

if (-not $owned -or $owned.Count -eq 0) {
  Write-Host "No QA-Again-owned Chromium processes found (matched by profile-dir prefix '$profileMarker')."
  exit 0
}

Write-Host "Found $($owned.Count) QA-Again-owned Chromium process(es):"
$cutoff = (Get-Date).AddMinutes(-1 * $OlderThanMinutes)
$toAct = @()

foreach ($proc in $owned) {
  $profileDir = Get-ProfileDirFromCommandLine -CommandLine $proc.CommandLine
  $age = if ($proc.CreationDate) { (Get-Date) - $proc.CreationDate } else { $null }
  $ageStr = if ($age) { "{0:N1} min" -f $age.TotalMinutes } else { "unknown" }
  Write-Host "  PID $($proc.ProcessId)  age=$ageStr  profile=$profileDir"

  $eligible = ($OlderThanMinutes -eq 0) -or ($proc.CreationDate -and $proc.CreationDate -lt $cutoff)
  if ($eligible) {
    $toAct += [PSCustomObject]@{ Pid = $proc.ProcessId; ProfileDir = $profileDir }
  }
}

if (-not $Kill) {
  Write-Host ""
  Write-Host "Read-only mode (default) -- pass -Kill to terminate these and remove their profile directories."
  exit 0
}

Write-Host ""
Write-Host "Terminating $($toAct.Count) eligible process(es) and removing their profile directories..."
foreach ($item in $toAct) {
  try {
    Stop-Process -Id $item.Pid -Force -ErrorAction Stop
    Write-Host "  Killed PID $($item.Pid)"
  } catch {
    Write-Warning "  Could not kill PID $($item.Pid): $_"
  }
  if ($item.ProfileDir -and (Test-Path $item.ProfileDir)) {
    try {
      Remove-Item -Path $item.ProfileDir -Recurse -Force -ErrorAction Stop
      Write-Host "  Removed profile dir $($item.ProfileDir)"
    } catch {
      Write-Warning "  Could not remove profile dir $($item.ProfileDir): $_"
    }
  }
}

# Also sweep the registry dir (runner/scripts/lib/browserLifecycle.mjs and
# runner/src/browser/browserRun.ts both write here) for stale entries
# whose profile directory no longer exists -- these are leftover
# bookkeeping files from runs that were already cleaned up some other way.
$registryDir = Join-Path $env:TEMP "qa-again-playwright-registry"
if (Test-Path $registryDir) {
  Get-ChildItem -Path $registryDir -Filter "*.json" | ForEach-Object {
    try {
      $entry = Get-Content $_.FullName -Raw | ConvertFrom-Json
      if ($entry.userDataDir -and -not (Test-Path $entry.userDataDir)) {
        Remove-Item $_.FullName -Force
      }
    } catch {
      # unreadable/partial registry file -- leave it, next run will retry
    }
  }
}

Write-Host "Done."
