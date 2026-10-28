# End-to-end smoke test of the Windows build, for CI (and any Windows machine).
#
#   pwsh desktop/scripts/smoke-windows.ps1 [-WithClaude]
#
# Run after `npm run dist` in desktop/. It installs release/LoopPrism-<v>-x64.exe silently
# for the current user, launches the app and checks, against the real installed app:
# the sidecar boots and serves the dashboard and proxy, sessions are read, the Claude Code /
# Codex installers work (Electron's own node, as the Apps page runs them), a hook command
# as written in hooks.json runs under cmd.exe and reaches the API, a crashed app's orphaned
# sidecar is cleaned up on the next start, and the self-updater installs a newer build over
# the running one. It leaves the machine with the app uninstalled.
param([switch]$WithClaude)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$dash = "http://127.0.0.1:8080"
$proxy = "http://127.0.0.1:4317"
$installDir = Join-Path $env:LOCALAPPDATA "Programs\loopprism-desktop" # electron-builder names it after the package
$appExe = Join-Path $installDir "LoopPrism.exe"
$resources = Join-Path $installDir "resources"
$logDir = Join-Path $env:APPDATA "LoopPrism\logs"
$sessionId = "aaaaaaaa-1111-2222-3333-444444444444" # tests/support_agents.py
$results = New-Object System.Collections.Generic.List[string]
$script:failed = $false

function Step([string]$name, [scriptblock]$body, [switch]$Fatal, [switch]$Soft) {
  Write-Host "`n=== $name"
  try {
    & $body
    $results.Add("PASS  $name")

  } catch {
    $msg = "$name -- $($_.Exception.Message)"
    Write-Host "FAILED: $($_.Exception.Message)"
    $flat = ($_.Exception.Message -replace "`r?`n", " | ")
    Write-Host "::error title=smoke FAIL::$name -- $flat"
    if ($Soft) { $results.Add("WARN  $msg") }
    else { $results.Add("FAIL  $msg"); $script:failed = $true }
    if ($Fatal) { throw "fatal step failed: $name" }
  }
}

function Wait-Until([scriptblock]$cond, [int]$seconds, [string]$what) {
  $end = (Get-Date).AddSeconds($seconds)
  while ((Get-Date) -lt $end) {
    try { if (& $cond) { return } } catch { }
    Start-Sleep -Milliseconds 500
  }
  throw "timed out after ${seconds}s waiting for $what"
}

function Test-Healthy {
  try {
    return ((Invoke-RestMethod "$dash/api/health" -TimeoutSec 2).status -eq "ok") -and
      ((Invoke-RestMethod "$proxy/health" -TimeoutSec 2).status -eq "ok")
  } catch { return $false }
}

function Assert([bool]$ok, [string]$what) { if (-not $ok) { throw "assertion failed: $what" } }

function Stop-App {
  Get-Process -Name LoopPrism, lprism -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  Wait-Until { -not (Get-Process -Name LoopPrism, lprism -ErrorAction SilentlyContinue) } 30 "LoopPrism to stop"
}

# Runs src/agent-worker.js the way the app does: Electron's node, hooks bundled in resources.
function Invoke-Worker([string[]]$workerArgs) {
  $out = Join-Path $env:TEMP "lp-worker-$([guid]::NewGuid().ToString('N')).json"
  $env:ELECTRON_RUN_AS_NODE = "1"
  $env:LPRISM_AGENT_ROOT = Join-Path $resources "agent-hooks"
  try {
    $script = Join-Path $resources "app.asar\src\agent-worker.js"
    $p = Start-Process $appExe -ArgumentList (@("`"$script`"") + $workerArgs) -Wait -NoNewWindow -PassThru -RedirectStandardOutput $out
    $text = (Get-Content $out -Raw)
    Assert ($p.ExitCode -eq 0) "worker exit code $($p.ExitCode): $text"
    return ($text | ConvertFrom-Json)
  } finally {
    Remove-Item Env:ELECTRON_RUN_AS_NODE, Env:LPRISM_AGENT_ROOT -ErrorAction SilentlyContinue
    Remove-Item $out -ErrorAction SilentlyContinue
  }
}

$installer = Get-ChildItem (Join-Path $repo "desktop\release") -Filter "LoopPrism-*-x64.exe" | Select-Object -First 1
if (-not $installer) { throw "no installer in desktop\release - run npm run dist first" }
$installedVersion = [regex]::Match($installer.Name, "LoopPrism-(.+)-x64\.exe").Groups[1].Value
Write-Host "Installer: $($installer.Name) ($([math]::Round($installer.Length / 1MB)) MB), version $installedVersion"

$feed = $null
try {
  Step "installs silently for the current user" -Fatal {
    $p = Start-Process $installer.FullName -ArgumentList "/S" -Wait -PassThru
    Assert ($p.ExitCode -eq 0) "installer exit code $($p.ExitCode)"
    # The NSIS stub may hand over to another process, so the files can land after it returns.
    try { Wait-Until { Test-Path $appExe } 120 "$appExe" } catch {
      $found = Get-ChildItem $env:LOCALAPPDATA, $env:ProgramFiles, ${env:ProgramFiles(x86)} -Filter "LoopPrism.exe" -Recurse -Depth 4 -ErrorAction SilentlyContinue |
        Select-Object -First 5 -ExpandProperty FullName
      $programs = (Get-ChildItem (Join-Path $env:LOCALAPPDATA "Programs") -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name) -join ", "
      throw "missing $appExe; LoopPrism.exe found at: [$($found -join '; ')]; LOCALAPPDATA\Programs holds: [$programs]"
    }
    Assert (Test-Path (Join-Path $resources "sidecar\lprism\lprism.exe")) "missing bundled lprism.exe"
    Assert (Test-Path (Join-Path $resources "agent-hooks\plugin\scripts\hook.js")) "missing bundled hooks"
    Assert (Test-Path (Join-Path $resources "agent-hooks\.claude-plugin\marketplace.json")) "missing bundled marketplace"
  }

  Step "sets up fixtures (a Claude Code session with subagents, a Codex home)" -Fatal {
    python (Join-Path $repo "tests\support_agents.py") $env:USERPROFILE | Out-Host
    Assert ($LASTEXITCODE -eq 0) "support_agents.py failed"
    New-Item -ItemType Directory -Force (Join-Path $env:USERPROFILE ".codex") | Out-Null
  }

  Step "launches and the sidecar becomes healthy" -Fatal {
    $script:app = Start-Process $appExe -PassThru
    Wait-Until { Test-Healthy } 120 "proxy and dashboard health"
    Assert ([bool](Get-Process -Name lprism -ErrorAction SilentlyContinue)) "no lprism.exe process"
    Assert (Test-Path (Join-Path $logDir "sidecar.log")) "no sidecar.log"
  }

  Step "serves the dashboard UI" {
    $html = (Invoke-WebRequest "$dash/" -UseBasicParsing).Content
    Assert ($html -match 'id="root"') "index.html has no #root"
  }

  Step "reads Claude Code sessions and their subagents" {
    $list = Invoke-RestMethod "$dash/api/sessions"
    Assert ($list.total -ge 1) "no sessions listed"
    Assert (@($list.sessions | Where-Object { $_.id -eq $sessionId }).Count -eq 1) "fixture session missing"
    $tree = Invoke-RestMethod "$dash/api/sessions/$sessionId/agents"
    Assert ($tree.supported -and $tree.totals.subagents -ge 3) "expected the fixture's subagents, got $($tree.totals.subagents)"
  }

  Step "Codex hooks install, as the Apps page runs it" {
    $st = Invoke-Worker @("status")
    Assert (-not $st.error) "status error: $($st.error)"
    Assert ($st.codex.found) "codex home not detected"
    $r = Invoke-Worker @("install", "codex")
    Assert ($r.ok) "install failed: $($r | ConvertTo-Json -Compress)"
    Assert ((Invoke-Worker @("status")).codex.connected) "codex not connected after install"
    Assert (Test-Path (Join-Path $env:USERPROFILE ".loopprism\hooks\hook.js")) "hook.js not copied"
  }

  Step "the hook command from hooks.json runs under cmd.exe and reaches the API" {
    $cfg = Get-Content (Join-Path $env:USERPROFILE ".codex\hooks.json") -Raw | ConvertFrom-Json
    $command = $cfg.hooks.UserPromptSubmit[0].hooks[0].command
    Write-Host "command: $command"
    $bat = Join-Path $env:TEMP "lp-hook.cmd"
    Set-Content $bat -Value "@echo off`r`n$command" -Encoding ASCII
    $payload = '{"hook_event_name":"UserPromptSubmit","session_id":"smoke-sess-1","cwd":"C:\\work","prompt":"hello from windows"}'
    $out = $payload | cmd /c $bat
    Assert ("$out".Trim() -eq "{}") "hook printed '$out', expected {}"
    Wait-Until {
      @((Invoke-RestMethod "$dash/api/traces?limit=50").traces | Where-Object { $_.session_id -eq "smoke-sess-1" }).Count -ge 1
    } 20 "the run to appear in /api/traces"
  }

  Step "lpa status lists the run" {
    $out = (node (Join-Path $repo "npm\bin\lpa.js") status) -join "`n"
    Write-Host $out
    Assert ($LASTEXITCODE -eq 0) "lpa status exit code $LASTEXITCODE"
    Assert ($out -match "codex") "lpa status does not show the codex run"
  }

  Step "Codex hooks uninstall" {
    Invoke-Worker @("uninstall", "codex") | Out-Null
    Assert (-not (Invoke-Worker @("status")).codex.connected) "still connected after uninstall"
  }

  if ($WithClaude) {
    Step "Claude Code plugin installs through the claude CLI (best effort)" -Soft {
      npm install -g "@anthropic-ai/claude-code" 2>&1 | Out-Host
      claude --version | Out-Host
      $st = Invoke-Worker @("status")
      Assert ($st.claude.cli) "claude CLI not found by the worker"
      $r = Invoke-Worker @("install", "claude")
      Assert ($r.ok) "install failed: $($r | ConvertTo-Json -Compress)"
      Assert ((Invoke-Worker @("status")).claude.connected) "claude plugin not listed after install"
      Invoke-Worker @("uninstall", "claude") | Out-Null
    }
  }

  Step "UI tour: screenshots of every page (and the real desktop) for comparison with macOS" {
    Stop-App
    $shots = Join-Path $repo "smoke-logs\screenshots"
    New-Item -ItemType Directory -Force $shots | Out-Null
    $env:LPRISM_TOUR_DIR = $shots
    $env:LPRISM_TOUR_SESSION = $sessionId
    $env:LPRISM_TOUR_QUIT = "1"
    try { $script:app = Start-Process $appExe -PassThru } finally {
      Remove-Item Env:LPRISM_TOUR_DIR, Env:LPRISM_TOUR_SESSION, Env:LPRISM_TOUR_QUIT -ErrorAction SilentlyContinue
    }
    # The window is still on the second page when live.png lands: grab the whole screen then,
    # so the real title bar and window frame are in the picture.
    Wait-Until { Test-Path (Join-Path $shots "live.png") } 120 "the tour to reach the Live runs page"
    try {
      Add-Type -AssemblyName System.Windows.Forms, System.Drawing
      $b = [System.Windows.Forms.SystemInformation]::VirtualScreen
      $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
      $g = [System.Drawing.Graphics]::FromImage($bmp)
      $g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)
      $bmp.Save((Join-Path $shots "desktop-native.png"), [System.Drawing.Imaging.ImageFormat]::Png)
      Write-Host "desktop screenshot $($b.Width)x$($b.Height)"
    } catch { Write-Host "no desktop screenshot: $($_.Exception.Message)" }
    Wait-Until { Test-Path (Join-Path $shots "narrow.png") } 120 "the tour to finish"
    Assert (@(Get-ChildItem $shots -Filter *.png).Count -ge 9) "expected at least 9 screenshots"
    Wait-Until { -not (Get-Process -Name LoopPrism -ErrorAction SilentlyContinue) } 60 "the app to quit after the tour"
    $script:app = Start-Process $appExe -PassThru
    Wait-Until { Test-Healthy } 120 "health after the tour"
  }

  Step "a crashed app's orphaned sidecar is cleaned up on the next start" {
    $old = @(Get-Process -Name lprism).Id
    Get-Process -Name LoopPrism | Stop-Process -Force
    Start-Sleep -Seconds 2
    Write-Host "orphaned lprism pid(s) after the crash: $(@(Get-Process -Name lprism -ErrorAction SilentlyContinue).Id -join ', ')"
    $script:app = Start-Process $appExe -PassThru
    Wait-Until { Test-Healthy } 120 "health after restart"
    Wait-Until { -not (Get-Process -Id $old -ErrorAction SilentlyContinue) } 30 "the stale sidecar to be killed"
    Assert ([bool](Get-Process -Name lprism -ErrorAction SilentlyContinue)) "no sidecar running after restart"
  }

  Step "self-update downloads the new installer, replaces the running app and restarts it" {
    Stop-App
    $feedPort = 18999
    $script:feed = Start-Process node -ArgumentList @(
      "`"$(Join-Path $repo 'desktop\scripts\smoke-feed.js')`"", "`"$($installer.FullName)`"", $feedPort, $installedVersion
    ) -PassThru -NoNewWindow
    Wait-Until { (Invoke-RestMethod "http://127.0.0.1:$feedPort/stats").downloads -ge 0 } 20 "the fake feed"
    $before = (Get-Item $appExe).LastWriteTime
    $env:LPRISM_UPDATE_API = "http://127.0.0.1:$feedPort/releases"
    $env:LPRISM_UPDATE_AUTOINSTALL = "1"
    try { $first = Start-Process $appExe -PassThru } finally {
      Remove-Item Env:LPRISM_UPDATE_API, Env:LPRISM_UPDATE_AUTOINSTALL -ErrorAction SilentlyContinue
    }
    Wait-Until { Test-Healthy } 120 "health before the update"
    Wait-Until { (Invoke-RestMethod "http://127.0.0.1:$feedPort/stats").downloads -ge 1 } 90 "the app to download the update"
    Wait-Until { -not (Get-Process -Id $first.Id -ErrorAction SilentlyContinue) } 60 "the old app to quit"
    Wait-Until {
      $now = Get-Process -Name LoopPrism -ErrorAction SilentlyContinue
      $now -and (@($now.Id) -notcontains $first.Id) -and (Test-Healthy)
    } 240 "the updated app to start and become healthy"
    # The new process must be the installed app (NSIS keeps file times, so don't compare those).
    $running = @(Get-Process -Name LoopPrism | Where-Object { $_.Id -ne $first.Id } | Select-Object -ExpandProperty Path)
    Assert ($running -contains $appExe) "the restarted app is not running from $appExe (got: $($running -join ', '))"
  }

  Step "uninstalls cleanly" {
    Stop-App
    $un = Get-ChildItem $installDir -Filter "Uninstall*.exe" | Select-Object -First 1
    Assert ($null -ne $un) "no uninstaller found"
    Start-Process $un.FullName -ArgumentList "/S" -Wait
    Wait-Until { -not (Test-Path $appExe) } 60 "the app to be removed"
  }
} catch {
  Write-Host "`nStopped early: $($_.Exception.Message)"
  $script:failed = $true
} finally {
  if ($feed) { Stop-Process -Id $feed.Id -Force -ErrorAction SilentlyContinue }
  Write-Host "`n================ sidecar.log (tail) ================"
  $log = Join-Path $logDir "sidecar.log"
  if (Test-Path $log) {
    Get-Content $log -Tail 60 | Out-Host
    # Annotations are readable without logging in, so surface the end of the log there too.
    $tail = (Get-Content $log -Tail 25) -join "%0A"
    Write-Host "::warning title=sidecar.log (tail)::$tail"
  } else { Write-Host "(none)" }
  New-Item -ItemType Directory -Force (Join-Path $repo "smoke-logs") | Out-Null
  if (Test-Path $log) { Copy-Item $log (Join-Path $repo "smoke-logs\sidecar.log") -Force }
  Get-ChildItem (Join-Path $env:TEMP "loopprism-update*") -ErrorAction SilentlyContinue |
    ForEach-Object { Copy-Item $_.FullName (Join-Path $repo "smoke-logs") -Force -ErrorAction SilentlyContinue }
  Write-Host "`n================ results ================"
  $results | ForEach-Object { Write-Host $_ }
  $results | Out-File (Join-Path $repo "smoke-logs\results.txt")
  # One annotation for all results: GitHub keeps only 10 notices per step.
  Write-Host "::notice title=smoke results::$($results -join '%0A')"
  if ($env:GITHUB_STEP_SUMMARY) {
    "### Windows smoke test`n" | Out-File $env:GITHUB_STEP_SUMMARY -Append
    $results | ForEach-Object { "- $_" } | Out-File $env:GITHUB_STEP_SUMMARY -Append
  }
}
if ($script:failed) { exit 1 }
