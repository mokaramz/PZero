<#
  Project Zero v2 - install / show / remove the background scheduled task (Windows Task Scheduler). Review 032c.

  The task is created DISABLED, under its OWN name: the old app's task "Project Zero - background jobs" is never
  touched by this script. Nothing runs until you enable it yourself (-Enable, or in Task Scheduler) - at the cutover,
  after you paused the old task and the live import ran.

    ... -File install-background-task.ps1 -EnvFile "C:\...\.env" -Show        print the configuration only
    ... -File install-background-task.ps1 -EnvFile "C:\...\.env"              register (DISABLED)
    ... -File install-background-task.ps1 -Enable                             enable the registered task
    ... -File install-background-task.ps1 -Disable                            disable it again
    ... -File install-background-task.ps1 -Uninstall                          remove it

  Schedule: every hour, at logon and on unlock (missed runs start as soon as possible after sleep / shutdown).
  Runs as YOU, only while you are logged on. Never two at once; a run is stopped after 2 hours. No wake-from-sleep,
  no admin rights.
#>
param(
    [string]$EnvFile = "",
    [string]$Schema = "pz",
    [string]$TaskName = "Project Zero v2 - background jobs",
    [switch]$Show,
    [switch]$Enable,
    [switch]$Disable,
    [switch]$Uninstall
)
$ErrorActionPreference = "Stop"
if ($TaskName -eq "Project Zero - background jobs") { throw "That is the OLD app's task; this script manages only the v2 task." }
$runner = Join-Path $PSScriptRoot "run-background.ps1"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
. (Join-Path $PSScriptRoot "runtime-check.ps1")

if ($Uninstall) { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false; "Removed '$TaskName'."; exit 0 }
if ($Enable) { Enable-ScheduledTask -TaskName $TaskName | Out-Null; "ENABLED '$TaskName' - it runs at the next trigger."; exit 0 }
if ($Disable) { Disable-ScheduledTask -TaskName $TaskName | Out-Null; "Disabled '$TaskName'."; exit 0 }

if (-not $EnvFile) { throw "-EnvFile is required (the .env holding SUPABASE_DB_URL for the production database)" }
$problem = Get-RuntimeProblem $repo
if ($problem -and -not $Show) { throw "Refusing to register: $problem. Run this installer from the production runtime." }
if ($problem) { "NOTE: $problem (shown for review only)" }
$EnvFile = (Resolve-Path $EnvFile).Path
$names = Import-EnvFile $EnvFile
if (-not ($names -contains "SUPABASE_DB_URL")) { throw "$EnvFile sets no SUPABASE_DB_URL" }

$arg = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$runner`" -EnvFile `"$EnvFile`" -Schema `"$Schema`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg -WorkingDirectory (Split-Path -Parent $runner)
$start = (Get-Date).Date.AddMinutes(5)
$hourly = New-ScheduledTaskTrigger -Once -At $start -RepetitionInterval (New-TimeSpan -Hours 1)
$logon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$unlockClass = Get-CimClass -Namespace Root/Microsoft/Windows/TaskScheduler -ClassName MSFT_TaskSessionStateChangeTrigger
$unlock = New-CimInstance -CimClass $unlockClass -ClientOnly -Property @{ StateChange = [uint32]8; UserId = "$env:USERDOMAIN\$env:USERNAME" }  # 8 = session unlock
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -DontStopOnIdleEnd -RestartCount 0
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$task = New-ScheduledTask -Action $action -Trigger @($hourly, $logon, $unlock) -Settings $settings -Principal $principal `
    -Description "Runs overdue Project Zero v2 jobs (event scan, news refresh and reviews, validation snapshot) through the app's own job runner, budgets and database lock. Proposals only - nothing is decided."
$task.Settings.Enabled = $false  # ALWAYS registered disabled

"Task:      $TaskName (registered DISABLED)"
"Runtime:   $repo  release $(Get-RuntimeRelease $repo)"
"Runs:      powershell.exe $arg"
"As:        $env:USERDOMAIN\$env:USERNAME, only while logged on, standard rights"
"Triggers:  hourly from $($start.ToString('HH:mm')) | at logon | on unlock | missed runs start when available"
"Limits:    one instance at a time (IgnoreNew) | stopped after 2 h | no wake from sleep"
"Database:  schema $Schema (settings from $EnvFile; values never shown)"
"Log:       $(Join-Path $env:LOCALAPPDATA 'ProjectZero\v2\background-task.log') (+ the job history, System health)"
if ($Show) { "(-Show: nothing was registered)"; exit 0 }
Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
"Registered DISABLED. Enable after review (at the cutover):  powershell -File `"$PSCommandPath`" -Enable"
