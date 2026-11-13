<#
  Project Zero v2 - the deployment logic behind deploy-release.ps1 (review 032c, Codex H-327). Dot-sourced.

  Every outside effect is one small function, so tests\deploy-release.tests.ps1 can replace it with a mock:
    Get-PzTaskEnabled / Set-PzTaskEnabled   the Windows task's state (Task Scheduler)
    Invoke-PzLockStatus                     python -m projectzero.jobs --lock-status (0 free, 10 held, else error)
    Invoke-PzEnsureEnv                      the runtime's own Python environment (scripts\ensure_python_env.ps1)
    Get-PzRuntimeCodePath                   where the runtime's Python imports projectzero from

  The rules:
    * every input is validated BEFORE the task is paused (the tag, the env file, the lock-status Python);
    * the task is resumed ONLY on a verified runtime: the new release when it verified, else the PREVIOUS release,
      restored and verified again; when no verified runtime remains (a first deployment that failed, or a previous
      release that no longer verifies) the task is left DISABLED and the failure says so.
#>
. (Join-Path $PSScriptRoot "runtime-check.ps1")

function Get-PzTaskEnabled([string]$TaskName) {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    return [bool]($task -and $task.Settings.Enabled)
}

function Set-PzTaskEnabled([string]$TaskName, [bool]$Enabled) {
    if ($Enabled) { Enable-ScheduledTask -TaskName $TaskName | Out-Null } else { Disable-ScheduledTask -TaskName $TaskName | Out-Null }
}

function Invoke-PzLockStatus([string]$DevPython) {
    $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    try { $line = (& $DevPython -m projectzero.jobs --lock-status 2>$null | Select-Object -First 1); return @{ code = $LASTEXITCODE; line = "$line" } }
    finally { $ErrorActionPreference = $prev }
}

function Invoke-PzEnsureEnv([string]$Runtime) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Runtime "scripts\ensure_python_env.ps1") | Out-Host
    return ($LASTEXITCODE -eq 0)
}

function Get-PzRuntimeCodePath([string]$Runtime) {
    $py = Join-Path $Runtime "backend\.venv\Scripts\python.exe"
    if (-not (Test-Path $py)) { return "" }
    $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    try { $env:PYTHONPATH = ""; return "$(& $py -c "import projectzero, os; print(os.path.dirname(projectzero.__file__))" 2>$null | Select-Object -First 1)" }
    finally { $ErrorActionPreference = $prev }
}

function Invoke-PzGit([string]$GitExe, [string]$Dir) {
    $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    try { & $GitExe -C $Dir @args 2>&1 } finally { $ErrorActionPreference = $prev }
}

# The runtime at HEAD is usable: the production-runtime rules hold and its Python imports its own code.
function Test-PzRuntime([string]$Runtime) {
    $problem = Get-RuntimeProblem $Runtime
    if ($problem) { return $problem }
    $codeFrom = Get-PzRuntimeCodePath $Runtime
    $own = Join-Path $Runtime "backend\src\projectzero"
    if (-not $codeFrom -or -not (Test-Path $codeFrom) -or ((Resolve-Path $codeFrom).Path -ne (Resolve-Path $own).Path)) {
        return "the runtime imports Project Zero from '$codeFrom' instead of its own checkout"
    }
    return ""
}

# Check out the exact $Commit in the runtime, prepare its environment and verify it. "" when verified, else the
# reason. HEAD is compared with $Commit itself (Codex H-329): never with what a name resolves to in the runtime.
function Set-PzRuntimeTo([string]$GitExe, [string]$Runtime, [string]$Commit, [string]$From) {
    Invoke-PzGit $GitExe $Runtime checkout --quiet --detach $Commit | Out-Null
    $now = (Invoke-PzGit $GitExe $Runtime rev-parse HEAD) | Select-Object -First 1
    if ("$now" -ne $Commit) { return "the runtime is at $now, expected $Commit" }
    $venv = Join-Path $Runtime "backend\.venv"
    if ($From -and (Test-Path $venv)) {
        Invoke-PzGit $GitExe $Runtime diff --quiet $From $now -- backend/pyproject.toml | Out-Null
        if ($LASTEXITCODE -ne 0) { Remove-Item -Recurse -Force $venv }  # the dependency list changed: rebuild
    }
    if (-not (Invoke-PzEnsureEnv $Runtime)) { return "the runtime Python environment could not be prepared" }
    return (Test-PzRuntime $Runtime)
}

function Invoke-PzDeploy {
    param(
        [Parameter(Mandatory = $true)][string]$Tag,
        [Parameter(Mandatory = $true)][string]$EnvFile,
        [Parameter(Mandatory = $true)][string]$Dev,
        [Parameter(Mandatory = $true)][string]$Runtime,
        [string]$Schema = "pz",
        [string]$TaskName = "Project Zero v2 - background jobs",
        [string]$DevPython = "",
        [string]$RecordDir = "",
        [int]$WaitMinutes = 30,
        [int]$PollSeconds = 20
    )
    if ($TaskName -eq "Project Zero - background jobs") { throw "That is the OLD app's task; this script manages only the v2 task." }
    $gitExe = (Get-Command git.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
    if (-not $DevPython) { $DevPython = Join-Path $Dev "backend\.venv\Scripts\python.exe" }

    # 1. validate EVERY input before anything is paused or changed (Codex H-327)
    $kind = (Invoke-PzGit $gitExe $Dev cat-file -t "refs/tags/$Tag") | Select-Object -First 1
    if ("$kind" -ne "tag") { throw "$Tag is not an annotated tag in $Dev - nothing changed" }
    $msg = (Invoke-PzGit $gitExe $Dev for-each-ref "refs/tags/$Tag" --format="%(contents)") -join " "
    if ($msg -notmatch "ALL CHECKS PASSED") { throw "$Tag does not record a passed release gate - nothing changed" }
    $commit = (Invoke-PzGit $gitExe $Dev rev-list -n 1 $Tag) | Select-Object -First 1
    $names = Import-EnvFile $EnvFile
    if (-not ($names -contains "SUPABASE_DB_URL")) { throw "$EnvFile sets no SUPABASE_DB_URL - nothing changed" }
    $env:PZ_SCHEMA = $Schema
    if (-not (Test-Path $DevPython)) { throw "the lock-status Python was not found at $DevPython - nothing changed" }
    if ((Test-Path $Runtime) -and -not (Test-Path (Join-Path $Runtime ".git"))) { throw "$Runtime exists but is not a git clone - nothing changed" }
    if (Test-Path (Join-Path $Runtime ".git")) {
        if ((Invoke-PzGit $gitExe $Runtime config --local --get pz.runtime) -ne "true") { throw "$Runtime exists but is not a production runtime - nothing changed" }
        if (Invoke-PzGit $gitExe $Runtime status --porcelain --untracked-files=normal) { throw "$Runtime has local changes - inspect them; nothing changed" }
    }

    # 2. pause the task and wait until no job runner holds the database lock
    $wasEnabled = Get-PzTaskEnabled $TaskName
    if ($wasEnabled) { Set-PzTaskEnabled $TaskName $false; "Paused '$TaskName' for the deployment." }
    $deadline = (Get-Date).AddMinutes($WaitMinutes)
    while ($true) {
        $st = Invoke-PzLockStatus $DevPython
        if ($st.code -eq 0) { break }
        if ($st.code -ne 10) { if ($wasEnabled) { Set-PzTaskEnabled $TaskName $true }; throw "the lock status could not be read (exit $($st.code)) - nothing changed" }
        if ((Get-Date) -ge $deadline) { if ($wasEnabled) { Set-PzTaskEnabled $TaskName $true }; throw "A job runner has been busy for $WaitMinutes minutes - deployment postponed, nothing changed." }
        "Waiting for the running job runner to finish... $($st.line)"; Start-Sleep $PollSeconds
    }

    # 3. the runtime clone at the tag; on any failure, the PREVIOUS release restored and verified before resuming
    $old = ""
    if (-not (Test-Path (Join-Path $Runtime ".git"))) {
        Invoke-PzGit $gitExe (Split-Path -Parent $Runtime) clone --quiet --no-checkout $Dev $Runtime | Out-Null
        if (-not (Test-Path (Join-Path $Runtime ".git"))) { throw "could not create the runtime clone at $Runtime - task left disabled" }
        Invoke-PzGit $gitExe $Runtime config --local pz.runtime true | Out-Null
        Invoke-PzGit $gitExe $Runtime config --local advice.detachedHead false | Out-Null
    } else {
        $old = (Invoke-PzGit $gitExe $Runtime rev-parse HEAD) | Select-Object -First 1
    }
    # Codex H-329: a fetch that git rejected (e.g. a conflicting tag of the same name already in the runtime) is a
    # failure, and the runtime's tag must name the APPROVED commit; then the exact commit is checked out
    $failure = ""
    Invoke-PzGit $gitExe $Runtime fetch --quiet --tags origin | Out-Null
    if ($LASTEXITCODE -ne 0) { $failure = "the runtime could not fetch the release tags from $Dev (exit ${LASTEXITCODE}: a conflicting tag?)" }
    if (-not $failure) {
        $tagged = (Invoke-PzGit $gitExe $Runtime rev-parse "refs/tags/$Tag^{commit}") | Select-Object -First 1
        if ("$tagged" -ne $commit) { $failure = "the runtime's tag $Tag names $tagged, not the approved commit $commit" }
    }
    if (-not $failure) { $failure = Set-PzRuntimeTo $gitExe $Runtime $commit $old }
    if (-not $failure) {
        $head = (Invoke-PzGit $gitExe $Runtime rev-parse HEAD) | Select-Object -First 1
        if ("$head" -ne $commit) { $failure = "the runtime is at $head, not the approved commit $commit" }
    }
    if (-not $failure) {
        if (-not $RecordDir) { $RecordDir = Join-Path $env:LOCALAPPDATA "ProjectZero\v2" }
        if (-not (Test-Path $RecordDir)) { New-Item -ItemType Directory -Force $RecordDir | Out-Null }
        $row = @{ at = (Get-Date -Format "yyyy-MM-ddTHH:mm:ss"); tag = $Tag; commit = $commit; previous = $old; runtime = $Runtime; by = $env:USERNAME } | ConvertTo-Json -Compress
        [System.IO.File]::AppendAllText((Join-Path $RecordDir "deployments.jsonl"), $row + "`n", (New-Object System.Text.UTF8Encoding $false))
        if ($wasEnabled) { Set-PzTaskEnabled $TaskName $true; "Re-enabled '$TaskName'." }
        return "Deployed $Tag ($($commit.Substring(0, 7))) to $Runtime"
    }
    # the new release did not verify: back to the previous one, and resume only if THAT verifies again
    if ($old) {
        $restored = Set-PzRuntimeTo $gitExe $Runtime $old ""
        if (-not $restored) {
            if ($wasEnabled) { Set-PzTaskEnabled $TaskName $true; "Re-enabled '$TaskName' on the previous release." }
            throw "deployment of $Tag failed ($failure); the previous release $($old.Substring(0, 7)) was restored and verified"
        }
        throw "deployment of $Tag failed ($failure), and the previous release no longer verifies ($restored) - task left DISABLED"
    }
    throw "deployment of $Tag failed ($failure) and there is no previous release - task left DISABLED"
}
