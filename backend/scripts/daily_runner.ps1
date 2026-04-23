# daily_runner.ps1 — Windows Task Scheduler wrapper for turbo.az daily scrape.
#
# Registers into Task Scheduler once (see register-task.ps1 in the same folder),
# then this script fires at the configured time each day:
#
#   1. Verify Chrome is reachable on CDP port 9222 (aborts cleanly if not,
#      since Cloudflare needs a human click and no point running headless).
#   2. Invoke scripts/run_local.py and stream its output to scraper_local.log.
#   3. Write a heartbeat to .last_run.json so the user can see the state.
#
# Exits:
#   0  success
#   2  preflight failed (Chrome not up on 9222) — skipped, not a crash
#   1  scraper exited non-zero

$ErrorActionPreference = "Stop"

$BackendDir   = Split-Path -Parent $PSScriptRoot
$RunnerScript = Join-Path $BackendDir "scripts\run_local.py"
$LogFile      = Join-Path $BackendDir "scraper_local.log"
$Heartbeat    = Join-Path $BackendDir ".last_run.json"
$CdpPort      = 9222

$startedAt = (Get-Date).ToUniversalTime().ToString("o")
$exitCode  = 0
$reason    = ""

# ── Preflight: Chrome must be reachable on the CDP port ───────────────────────
try {
    $null = Invoke-WebRequest -Uri "http://localhost:$CdpPort/json/version" `
        -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
} catch {
    $reason = "preflight_failed: Chrome not reachable on CDP port $CdpPort. Open Chrome with --remote-debugging-port=$CdpPort and leave it running during the scheduled window."
    $finishedAt = (Get-Date).ToUniversalTime().ToString("o")
    @{
        started_at  = $startedAt
        finished_at = $finishedAt
        exit_code   = 2
        reason      = $reason
    } | ConvertTo-Json | Out-File -Encoding utf8 -FilePath $Heartbeat
    Write-Host $reason
    exit 2
}

# ── Invoke the scraper. Tee output to the log and to host so Task Scheduler
#    captures it in the task's last-run output pane. ──────────────────────────
Push-Location $BackendDir
try {
    & python.exe $RunnerScript --headless 2>&1 | Tee-Object -FilePath $LogFile -Append
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        $reason = "scraper_exit_$exitCode"
    } else {
        $reason = "ok"
    }
} catch {
    $exitCode = 1
    $reason   = "exception: $($_.Exception.Message)"
} finally {
    Pop-Location
}

$finishedAt = (Get-Date).ToUniversalTime().ToString("o")

# ── Heartbeat file — picked up by monitoring / UI / future dashboards ─────────
@{
    started_at  = $startedAt
    finished_at = $finishedAt
    exit_code   = $exitCode
    reason      = $reason
} | ConvertTo-Json | Out-File -Encoding utf8 -FilePath $Heartbeat

exit $exitCode
