# Quality gate: run before every review request. ASCII only (Windows PowerShell 5.1).
# Usage: powershell -ExecutionPolicy Bypass -File scripts\check.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$failed = @()

function Step($name, [scriptblock]$body) {
    Write-Host "== $name" -ForegroundColor Cyan
    & $body
    if ($LASTEXITCODE -ne 0) { $script:failed += $name; Write-Host "   FAILED: $name" -ForegroundColor Red }
}

$py = Join-Path $root "backend\.venv\Scripts\python.exe"
Push-Location (Join-Path $root "backend")
try {
    Step "backend: ruff check" { & $py -m ruff check src tests }
    Step "backend: ruff format" { & $py -m ruff format --check src tests }
    Step "backend: mypy" { & $py -m mypy }
    Step "backend: pytest" { & $py -m pytest }
} finally { Pop-Location }

Step "contracts: ECMA pattern parity" { node --test (Join-Path $root "contracts\tests\patterns.test.mjs") }

Push-Location (Join-Path $root "supabase\tests")
try {
    if (-not (Test-Path "node_modules")) { npm ci --no-audit --no-fund | Out-Null }
    Step "schema: PGlite tests" { npm test --silent }
} finally { Pop-Location }

if ($failed.Count -gt 0) { Write-Host "GATE FAILED: $($failed -join ', ')" -ForegroundColor Red; exit 1 }
Write-Host "ALL CHECKS PASSED" -ForegroundColor Green
