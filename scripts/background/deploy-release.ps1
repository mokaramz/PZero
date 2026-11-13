<#
  Project Zero v2 - deploy a TESTED release to the production runtime that the background task runs. Review 032c.

  The scheduler never runs code from the development checkout. It runs a separate clone (the production runtime,
  default: next to the development folder, "project-zero-optimized-runtime"), pinned to an annotated release tag
  created only after the full gate passed:

    1. In the development checkout, on the commit to release, run the gate:
         powershell -ExecutionPolicy Bypass -File scripts\check.ps1        -> must end with ALL CHECKS PASSED
    2. Tag that exact commit (the message must say the gate passed):
         git tag -a pz-release-YYYYMMDD-N -m "Release gate: ALL CHECKS PASSED (backend N, frontend N, PGlite N)"
    3. Deploy it (from the development checkout):
         powershell -ExecutionPolicy Bypass -File scripts\background\deploy-release.ps1 -Tag pz-release-YYYYMMDD-N -EnvFile "C:\...\.env"

  What it does (deploy-lib.ps1, Codex H-327): validates every input first (nothing is paused for a bad tag or env
  file); pauses the v2 task and waits until no job runner holds the database lock; checks out the tag in the runtime,
  prepares its own Python environment and verifies it imports its own code; resumes the task ONLY on a verified
  runtime - the new release, or else the previous release restored and verified again; with no verified runtime the
  task stays DISABLED. The old app's task and data folder are never touched.
#>
param(
    [Parameter(Mandatory = $true)][string]$Tag,
    [Parameter(Mandatory = $true)][string]$EnvFile,
    [string]$Schema = "pz",
    [string]$Runtime = "",
    [string]$TaskName = "Project Zero v2 - background jobs"
)
$ErrorActionPreference = "Stop"
$dev = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $Runtime) { $Runtime = Join-Path (Split-Path -Parent $dev) "project-zero-optimized-runtime" }
. (Join-Path $PSScriptRoot "deploy-lib.ps1")
Invoke-PzDeploy -Tag $Tag -EnvFile $EnvFile -Dev $dev -Runtime $Runtime -Schema $Schema -TaskName $TaskName
