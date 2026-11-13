<#
  Project Zero v2 - unattended background run (what the Windows scheduled task executes). Review 032c.

  Runs the overdue Project Zero jobs ONCE through the job runner (python -m projectzero.jobs --background): the
  ported jobs only, the same budgets and cost caps, the history in the database, and the one database lock shared
  with the app's own catch-up (never two runners at once). Before the live import the runner writes nothing to the
  live schema. Nothing is decided: jobs only produce proposals.

  Usage:
    powershell -NoProfile -ExecutionPolicy Bypass -File run-background.ps1 -EnvFile "C:\...\.env"
    ... -DryRun     list what is due, run nothing, write nothing
  Exit codes: 0 ok / nothing due / skipped because another runner holds the lock | 2 a job failed | 3 refused
#>
param(
    [Parameter(Mandatory = $true)][string]$EnvFile,
    [string]$Schema = "pz",
    [switch]$DryRun
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$py = Join-Path $repo "backend\.venv\Scripts\python.exe"
$logDir = Join-Path $env:LOCALAPPDATA "ProjectZero\v2"
$log = Join-Path $logDir "background-task.log"

function Write-Log([string]$line) {
    if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force $logDir | Out-Null }
    if ((Test-Path $log) -and ((Get-Item $log).Length -gt 5MB)) { Move-Item -Force $log "$log.1" }  # keep it bounded
    [System.IO.File]::AppendAllText($log, $line + "`r`n", (New-Object System.Text.UTF8Encoding $false))  # no BOM
    Write-Output $line
}

$stamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
. (Join-Path $PSScriptRoot "runtime-check.ps1")
$problem = Get-RuntimeProblem $repo
if ($problem -and -not $DryRun) { Write-Log "$stamp REFUSED: $problem"; exit 3 }  # never run jobs from a dev checkout
if ($problem) { Write-Log "$stamp NOTE: $problem - dry run only" }
if (-not (Test-Path $py)) { Write-Log "$stamp REFUSED: Python environment not found at $py"; exit 3 }

# explicit configuration: the database settings from the given env file (values are never printed or logged)
try { $loaded = Import-EnvFile $EnvFile } catch { Write-Log "$stamp REFUSED: $($_.Exception.Message)"; exit 3 }
if (-not ($loaded -contains "SUPABASE_DB_URL")) { Write-Log "$stamp REFUSED: $EnvFile sets no SUPABASE_DB_URL"; exit 3 }
$env:PZ_SCHEMA = $Schema
$env:PZ_CATCHUP = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONPATH = ""  # only this runtime's own code (its editable install) - never a path from the user environment
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8  # decode Python's UTF-8 output correctly (PS 5.1)
# PRESENCE only (values are never read here or logged): paid calls stay off unless PZ_AI_PAID=on and a key are set
$keys = foreach ($k in "PZ_AI_PAID", "DEEPINFRA_API_KEY") { if ([Environment]::GetEnvironmentVariable($k)) { "$k=set" } else { "$k=MISSING" } }

$pyArgs = @("-m", "projectzero.jobs", "--background")
if ($DryRun) { $pyArgs += "--dry-run" }
# the code that will run must be THIS runtime's code
$prevEap = $ErrorActionPreference; $ErrorActionPreference = "Continue"
$codeFrom = (& $py -c "import projectzero, os; print(os.path.dirname(projectzero.__file__))" 2>$null | Select-Object -First 1)
$ErrorActionPreference = $prevEap
$expected = Join-Path $repo "backend\src\projectzero"
if (-not $DryRun -and ((Resolve-Path $codeFrom -ErrorAction SilentlyContinue).Path -ne (Resolve-Path $expected).Path)) {
    Write-Log "$stamp REFUSED: Python would import Project Zero from '$codeFrom', not this runtime ($expected)"; exit 3
}
Write-Log "$stamp START $(if ($DryRun) {'dry-run'} else {'run'}) | release=$(Get-RuntimeRelease $repo) | code=$codeFrom | schema=$Schema | $($keys -join ' ') | user=$env:USERNAME"
Push-Location (Join-Path $repo "backend")
$ErrorActionPreference = "Continue"  # Python logs to stderr; in Windows PowerShell 5.1 that must not abort the run
try {
    $out = & $py @pyArgs 2>&1 | ForEach-Object { "$_" } | Out-String
    $code = $LASTEXITCODE
} finally {
    Pop-Location
    $ErrorActionPreference = "Stop"
}
foreach ($l in ($out -split "`r?`n" | Where-Object { $_ -and $_ -notmatch "^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+ (INFO|DEBUG)" })) { Write-Log "  $l" }
Write-Log "$(Get-Date -Format 'yyyy-MM-ddTHH:mm:ss') END exit=$code"
exit $code
