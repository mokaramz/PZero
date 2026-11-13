<#
  Project Zero v2 - make sure this checkout has its own Python environment (backend\.venv) with the backend
  installed in editable mode. Used by scripts\background\deploy-release.ps1 for the production runtime. Review 032c.

    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ensure_python_env.ps1

  Creates backend\.venv with the Python launcher when it is missing, then installs the backend (no dev tools) into it.
  Exit 0 when the environment imports projectzero from THIS checkout; 1 otherwise.
#>
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $repo "backend"
$venv = Join-Path $backend ".venv"
$py = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $py)) {
    "Creating $venv"
    & py -3 -m venv $venv
    if ($LASTEXITCODE -ne 0) { "could not create the environment"; exit 1 }
}
$env:PYTHONPATH = ""
& $py -m pip install --quiet --disable-pip-version-check -e $backend
if ($LASTEXITCODE -ne 0) { "pip install failed"; exit 1 }
$codeFrom = (& $py -c "import projectzero, os; print(os.path.dirname(projectzero.__file__))" | Select-Object -First 1)
if ((Resolve-Path $codeFrom).Path -ne (Resolve-Path (Join-Path $backend "src\projectzero")).Path) {
    "the environment imports Project Zero from $codeFrom instead of this checkout"; exit 1
}
"Python environment ready: $py"
exit 0
