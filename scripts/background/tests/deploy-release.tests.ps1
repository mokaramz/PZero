<#
  Project Zero v2 - tests of deploy-lib.ps1 (Codex H-327). No real task, no real Python, no network:
  Task Scheduler, the lock status, the environment build and the import check are mocked; the development checkout
  and the runtime are disposable git repositories in a temporary folder.

    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\background\tests\deploy-release.tests.ps1
  Exit 0 when every case passes, 1 otherwise.
#>
$ErrorActionPreference = "Stop"
. (Join-Path (Split-Path -Parent $PSScriptRoot) "deploy-lib.ps1")

# ---- mocks (functions defined after the dot-source replace the library's) ----
$script:TaskEnabled = $true
$script:TaskCalls = @()
$script:FailEnvFor = @()
$script:FailImportFor = @()
function Get-PzTaskEnabled([string]$TaskName) { return $script:TaskEnabled }
function Set-PzTaskEnabled([string]$TaskName, [bool]$Enabled) { $script:TaskEnabled = $Enabled; $script:TaskCalls += $Enabled }
function Invoke-PzLockStatus([string]$DevPython) { return @{ code = 0; line = '{"held": false}' } }
function Head([string]$dir) { return "$(& git -C $dir rev-parse HEAD)" }
function Invoke-PzEnsureEnv([string]$Runtime) { return -not ($script:FailEnvFor -contains (Head $Runtime)) }
function Get-PzRuntimeCodePath([string]$Runtime) {
    if ($script:FailImportFor -contains (Head $Runtime)) { return $env:TEMP }
    return (Join-Path $Runtime "backend\src\projectzero")
}

# ---- a disposable development checkout with three tags ----
$root = Join-Path $env:TEMP ("pz-deploy-test-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
$dev = Join-Path $root "dev"
New-Item -ItemType Directory -Force (Join-Path $dev "backend\src\projectzero") | Out-Null
function G([string]$dir) { $p = $ErrorActionPreference; $ErrorActionPreference = "Continue"; try { & git -C $dir @args 2>&1 | Out-Null } finally { $ErrorActionPreference = $p } }
G $dev init --quiet
G $dev config user.email "deploy-test@invented.example"
G $dev config user.name "Deploy Test"
Set-Content -Path (Join-Path $dev "backend\src\projectzero\__init__.py") -Value "# r1" -Encoding ascii
Set-Content -Path (Join-Path $dev "backend\pyproject.toml") -Value "[project]" -Encoding ascii
G $dev add -A; G $dev commit --quiet -m "r1"
G $dev tag -a pz-release-1 -m "Release gate: ALL CHECKS PASSED (test)"
$r1 = Head $dev
Set-Content -Path (Join-Path $dev "backend\src\projectzero\__init__.py") -Value "# r2" -Encoding ascii
G $dev add -A; G $dev commit --quiet -m "r2"
G $dev tag -a pz-release-2 -m "Release gate: ALL CHECKS PASSED (test)"
G $dev tag -a pz-release-unchecked -m "no gate recorded"
$r2 = Head $dev
$devPy = Join-Path $root "devpython.exe"; Set-Content -Path $devPy -Value "" -Encoding ascii  # only Test-Path'd: the lock status is mocked
$envOk = Join-Path $root "ok.env"; Set-Content -Path $envOk -Value "SUPABASE_DB_URL=postgresql://invented.example/db" -Encoding ascii
$envBad = Join-Path $root "bad.env"; Set-Content -Path $envBad -Value "PZ_SCHEMA=pz" -Encoding ascii

$failures = @()
function Case([string]$name, [scriptblock]$body) {
    $script:TaskCalls = @(); $script:FailEnvFor = @(); $script:FailImportFor = @(); $script:TaskEnabled = $true
    try { & $body; "PASS  $name" } catch { $script:failures += $name; "FAIL  $name :: $($_.Exception.Message)" }
}
function Expect([bool]$ok, [string]$what) { if (-not $ok) { throw $what } }
function Deploy([string]$tag, [string]$runtime, [string]$envFile = $envOk) {
    Invoke-PzDeploy -Tag $tag -EnvFile $envFile -Dev $dev -Runtime $runtime -DevPython $devPy -RecordDir (Join-Path $root "rec") -PollSeconds 0 | Out-Null
}
function Throws([scriptblock]$b, [string]$pattern) {
    try { & $b } catch { if ($_.Exception.Message -notmatch $pattern) { throw "wrong failure: $($_.Exception.Message)" }; return }
    throw "expected a failure matching '$pattern'"
}

try {
    $rt = Join-Path $root "runtime"
    Case "a missing database setting fails BEFORE the task is paused" {
        Throws { Deploy "pz-release-1" $rt $envBad } "sets no SUPABASE_DB_URL - nothing changed"
        Expect ($script:TaskEnabled -eq $true) "the task was left disabled"
        Expect ($script:TaskCalls.Count -eq 0) "the task was touched: $($script:TaskCalls)"
        Expect (-not (Test-Path $rt)) "the runtime was created"
    }
    Case "a tag without a passed gate fails BEFORE the task is paused" {
        Throws { Deploy "pz-release-unchecked" $rt } "does not record a passed release gate"
        Expect ($script:TaskCalls.Count -eq 0) "the task was touched"
    }
    Case "a failed FIRST deployment leaves the task disabled" {
        $script:FailEnvFor = @($r1)
        $first = Join-Path $root "runtime-first"
        Throws { Deploy "pz-release-1" $first } "no previous release - task left DISABLED"
        Expect ($script:TaskEnabled -eq $false) "the task was re-enabled on an unverified runtime"
    }
    Case "a successful deployment resumes the task on the verified release" {
        Deploy "pz-release-1" $rt
        Expect ((Head $rt) -eq $r1) "the runtime is not at release 1"
        Expect ($script:TaskEnabled -eq $true -and ($script:TaskCalls -join ",") -eq "False,True") "pause/resume: $($script:TaskCalls)"
    }
    Case "an environment-build failure restores and verifies the previous release before resuming" {
        $script:FailEnvFor = @($r2)
        Throws { Deploy "pz-release-2" $rt } "previous release .* was restored and verified"
        Expect ((Head $rt) -eq $r1) "the runtime was left on the failed release"
        Expect ($script:TaskEnabled -eq $true -and ($script:TaskCalls -join ",") -eq "False,True") "pause/resume: $($script:TaskCalls)"
    }
    Case "an import-check failure restores and verifies the previous release before resuming" {
        $script:FailImportFor = @($r2)
        Throws { Deploy "pz-release-2" $rt } "previous release .* was restored and verified"
        Expect ((Head $rt) -eq $r1) "the runtime was left on the failed release"
        Expect ($script:TaskEnabled -eq $true) "the task was not resumed on the restored release"
    }
    Case "a previous release that no longer verifies leaves the task disabled" {
        $script:FailEnvFor = @($r2, $r1)
        Throws { Deploy "pz-release-2" $rt } "previous release no longer verifies .* task left DISABLED"
        Expect ($script:TaskEnabled -eq $false) "the task was re-enabled on an unverified runtime"
    }
    Case "a conflicting same-name tag in the runtime never resumes on the wrong commit" {
        # the runtime holds its OWN pz-release-2, on release 1's commit: the fetch of the development tags is refused
        $p = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        & git -C $rt tag -d pz-release-2 2>&1 | Out-Null  # the earlier cases fetched the real one: replace it
        & git -C $rt tag -a pz-release-2 -m "Release gate: ALL CHECKS PASSED (a conflicting tag)" $r1 2>&1 | Out-Null
        $ErrorActionPreference = $p
        Expect ("$(& git -C $rt rev-parse 'refs/tags/pz-release-2^{commit}')" -eq $r1) "the conflicting tag was not created"
        $rec = Join-Path $root "rec\deployments.jsonl"
        $before = if (Test-Path $rec) { @(Get-Content $rec) } else { @() }
        Throws { Deploy "pz-release-2" $rt } "could not fetch the release tags .* previous release .* was restored and verified"
        Expect ((Head $rt) -eq $r1) "the runtime is not on the verified previous release"
        Expect ($script:TaskEnabled -eq $true -and ($script:TaskCalls -join ",") -eq "False,True") "pause/resume: $($script:TaskCalls)"
        $after = if (Test-Path $rec) { @(Get-Content $rec) } else { @() }
        Expect ($after.Count -eq $before.Count) "a deployment was recorded"
        foreach ($line in $after) {
            $row = $line | ConvertFrom-Json
            Expect ($row.commit -ne $r2 -or (Head $rt) -eq $r2) "a record claims $r2 while the runtime is at $(Head $rt)"
        }
        $p = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        & git -C $rt tag -d pz-release-2 2>&1 | Out-Null  # clear the conflict for the next case
        $ErrorActionPreference = $p
    }
    Case "a later successful deployment moves to the new release" {
        Deploy "pz-release-2" $rt
        Expect ((Head $rt) -eq $r2) "the runtime is not at release 2"
        Expect ($script:TaskEnabled -eq $true) "the task was not resumed"
        $last = (Get-Content (Join-Path $root "rec\deployments.jsonl") | Select-Object -Last 1) | ConvertFrom-Json
        Expect ($last.commit -eq $r2 -and (Head $rt) -eq $last.commit) "the record does not name the runtime HEAD"
    }
    # ---- the runtime check itself (Codex H-331): only ANNOTATED tags carry a gate record ----
    $lw = Join-Path $root "lightweight"
    G $root clone --quiet $dev $lw
    G $lw config --local pz.runtime true
    G $lw config user.email "deploy-test@invented.example"
    G $lw config user.name "Deploy Test"
    Set-Content -Path (Join-Path $lw "backend\src\projectzero\__init__.py") -Value "# lw" -Encoding ascii
    G $lw add -A
    G $lw commit --quiet -m "Release gate: ALL CHECKS PASSED (in a COMMIT message, not a tag record)"
    G $lw tag pz-release-lightweight  # a lightweight tag: %(contents) would read the commit message above
    Case "a lightweight-only release tag is refused, even when the commit message says the gate passed" {
        $problem = Get-RuntimeProblem $lw
        Expect ($problem -match "no ANNOTATED release tag at HEAD") "accepted: '$problem'"
        Expect (@(Get-PassedReleaseTags $lw).Count -eq 0) "a lightweight tag was counted as a gate record"
    }
    Case "an annotated tag WITHOUT the gate record beside the lightweight one is still refused" {
        G $lw tag -a pz-release-unrecorded -m "no gate here"
        Expect ((Get-RuntimeProblem $lw) -match "no ANNOTATED release tag at HEAD") "accepted"
    }
    Case "a qualifying annotated tag at the same HEAD is accepted and selected by both checks" {
        G $lw tag -a pz-release-annotated -m "Release gate: ALL CHECKS PASSED (test)"
        Expect ((Get-RuntimeProblem $lw) -eq "") "refused: $(Get-RuntimeProblem $lw)"
        Expect (@(Get-PassedReleaseTags $lw) -join "," -eq "pz-release-annotated") "selected: $(@(Get-PassedReleaseTags $lw) -join ',')"
        Expect ((Get-RuntimeRelease $lw) -match "^pz-release-annotated \(") "the release label: $(Get-RuntimeRelease $lw)"
    }

} finally {
    Remove-Item -Recurse -Force $root -ErrorAction SilentlyContinue
}
if ($failures.Count) { "FAILED: $($failures.Count) case(s)"; exit 1 }
"ALL DEPLOY CASES PASSED"
exit 0
