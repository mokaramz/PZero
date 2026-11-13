<#
  Project Zero v2 - is this checkout a deployable PRODUCTION RUNTIME? (dot-sourced by run-background.ps1,
  install-background-task.ps1 and deploy-release.ps1). Review 032c: the old runtime rules, unchanged.

  A production runtime is a separate clone made by deploy-release.ps1. It must be:
    * marked as such (git config --local pz.runtime true - never set in a development checkout)
    * clean (no modified or untracked files)
    * exactly at an annotated release tag pz-release-* whose message records a passed release gate
  Returns "" when all hold, else the reason.
#>
function Get-RuntimeProblem([string]$repo) {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) { return "git is not available" }
    $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    try {
        $mark = (& git -C $repo config --local --get pz.runtime 2>$null)
        if ("$mark".Trim() -ne "true") { return "$repo is not the production runtime (a development checkout never runs scheduled jobs; deploy with deploy-release.ps1)" }
        $dirty = (& git -C $repo status --porcelain --untracked-files=normal 2>$null)
        if ($dirty) { return "the production runtime has local changes - redeploy a release instead of editing it" }
        $tags = @(Get-ReleaseTagsAtHead $repo)
        if (-not $tags) { return "the production runtime is not at a pz-release-* tag" }
        if (@(Get-PassedReleaseTags $repo).Count) { return "" }
        return "no ANNOTATED release tag at HEAD ($($tags -join ', ')) records a passed release gate"
    } finally {
        $ErrorActionPreference = $prev
    }
}

# Every pz-release-* tag pointing at HEAD (git describe picks just one when a commit carries several).
function Get-ReleaseTagsAtHead([string]$repo) {
    $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    try { return @(& git -C $repo tag --points-at HEAD 2>$null | Where-Object { "$_" -match '^pz-release-' }) }
    finally { $ErrorActionPreference = $prev }
}

# The release tags at HEAD that record a passed gate: ANNOTATED tag objects only (Codex H-331). For a lightweight tag
# %(contents) would read the COMMIT message, which is not a gate record. Shared by both checks below.
function Get-PassedReleaseTags([string]$repo) {
    $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    try {
        $out = @()
        foreach ($tag in (Get-ReleaseTagsAtHead $repo)) {
            if ("$(& git -C $repo cat-file -t "refs/tags/$tag" 2>$null)".Trim() -ne "tag") { continue }  # lightweight
            $msg = (& git -C $repo for-each-ref "refs/tags/$tag" --format="%(contents)" 2>$null) -join " "
            if ($msg -match "ALL CHECKS PASSED") { $out += $tag }
        }
        return $out
    } finally { $ErrorActionPreference = $prev }
}

function Get-RuntimeRelease([string]$repo) {
    $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    try {
        $passed = @(Get-PassedReleaseTags $repo)
        $tags = @(Get-ReleaseTagsAtHead $repo)
        $tag = if ($passed) { $passed[0] } elseif ($tags) { $tags[0] } else { "" }
        $sha = (& git -C $repo rev-parse --short HEAD 2>$null)
        return "$tag ($sha)"
    } finally { $ErrorActionPreference = $prev }
}

# Load KEY=value lines from an env file into THIS process only, never printing a value. Returns the names set.
function Import-EnvFile([string]$path) {
    if (-not (Test-Path $path)) { throw "env file not found: $path" }
    $names = @()
    foreach ($l in Get-Content $path) {
        if ($l -match '^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$') {
            Set-Item -Path ("Env:" + $Matches[1]) -Value $Matches[2].Trim()
            $names += $Matches[1]
        }
    }
    return $names
}
