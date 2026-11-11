# Database tasks against the hosted Supabase project. ASCII only (Windows PowerShell 5.1).
#   powershell -ExecutionPolicy Bypass -File scripts\db.ps1 status   # connectivity + which migrations are applied
#   powershell -ExecutionPolicy Bypass -File scripts\db.ps1 plan     # dry run: what push would apply
#   powershell -ExecutionPolicy Bypass -File scripts\db.ps1 push     # apply pending migrations
#   powershell -ExecutionPolicy Bypass -File scripts\db.ps1 verify   # hosted checks (lockdown, atomic intake, locks)
#   powershell -ExecutionPolicy Bypass -File scripts\db.ps1 itest    # hosted integration tests (scratch schemas)
#   powershell -ExecutionPolicy Bypass -File scripts\db.ps1 cleanup  # drop scratch schemas left by an interrupted run
# Reads SUPABASE_DB_URL from .env. The connection string is passed to the tools, never printed.
param([Parameter(Mandatory = $true)][ValidateSet("status", "plan", "push", "verify", "itest", "cleanup")] [string]$Task)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

$envFile = Join-Path $root ".env"
if (-not (Test-Path $envFile)) { throw ".env not found. Copy .env.example to .env and fill it in." }
foreach ($line in Get-Content $envFile) {
    if ($line -match '^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$') { Set-Item -Path ("Env:" + $Matches[1]) -Value $Matches[2].Trim() }
}
if (-not $env:SUPABASE_DB_URL) { throw "SUPABASE_DB_URL is empty in .env (Session pooler string, port 5432)." }
if ($env:SUPABASE_DB_URL -match '\[YOUR-PASSWORD\]') { throw "SUPABASE_DB_URL still contains [YOUR-PASSWORD]." }
if ($env:SUPABASE_DB_URL -match ':6543/') { throw "That is the transaction pooler (6543). Use the session pooler (5432)." }

$cli = Join-Path $root "supabase\tests\node_modules\.bin\supabase.cmd"
$py = Join-Path $root "backend\.venv\Scripts\python.exe"

switch ($Task) {
    "status" { & $py -m projectzero.ops.db_check status }
    "plan"   { & $cli db push --workdir $root --db-url $env:SUPABASE_DB_URL --dry-run }
    "push"   { & $cli db push --workdir $root --db-url $env:SUPABASE_DB_URL }
    "verify" { & $py -m projectzero.ops.db_check verify }
    "cleanup" { & $py -m projectzero.ops.db_check cleanup }
    "itest"  { Push-Location (Join-Path $root "backend"); try { & $py -m pytest -m hosted tests/hosted } finally { Pop-Location } }
}
exit $LASTEXITCODE
