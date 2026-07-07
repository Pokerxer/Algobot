# Algobot VPS Setup Script
# Run as Administrator in PowerShell on a fresh Windows Server 2019/2022
# Usage: Right-click PowerShell -> "Run as Administrator", then paste and run.
#
# What this does:
#   1. Installs Git, Python (via uv)
#   2. Clones the repo
#   3. Creates the venv and installs dependencies
#   4. Applies the WMI workaround (sitecustomize.py)
#   5. Writes .env with credentials
#   6. Installs MT5 terminal
#   7. Configures Windows auto-login (so desktop is always up after reboot)
#   8. Creates start_bot.ps1 wrapper (restart loop + logging)
#   9. Registers Task Scheduler tasks for MT5 and the bot (interactive session,
#      not a service — MT5 requires a real desktop, not Session 0)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$REPO_URL  = "https://github.com/Pokerxer/Algobot.git"
$INSTALL   = "C:\Algobot"
$BOT_DIR   = "$INSTALL\bot"
$VENV      = "$BOT_DIR\.venv"
$PYTHON    = "$VENV\Scripts\python.exe"
$MT5_EXE   = "C:\Program Files\MetaTrader 5\terminal64.exe"
$LOG_DIR   = $BOT_DIR

Write-Host "`n=== Algobot VPS Setup ===" -ForegroundColor Cyan

# ── 1. Chocolatey (package manager) ──────────────────────────────────────────
if (-not (Get-Command choco -ErrorAction SilentlyContinue)) {
    Write-Host "Installing Chocolatey..." -ForegroundColor Yellow
    Set-ExecutionPolicy Bypass -Scope Process -Force
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
    Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
}
$env:PATH += ";$env:ALLUSERSPROFILE\chocolatey\bin"
Write-Host "Chocolatey OK" -ForegroundColor Green

# ── 2. Git ────────────────────────────────────────────────────────────────────
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "Installing Git..." -ForegroundColor Yellow
    choco install git -y --no-progress
    $env:PATH += ";C:\Program Files\Git\cmd"
}
Write-Host "Git OK" -ForegroundColor Green

# ── 3. uv (Python package manager — installs Python 3.12 automatically) ──────
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv..." -ForegroundColor Yellow
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:PATH += ";$env:USERPROFILE\.local\bin"
}
Write-Host "uv OK" -ForegroundColor Green

# ── 4. Clone repo ─────────────────────────────────────────────────────────────
if (Test-Path $INSTALL) {
    Write-Host "Updating existing repo..." -ForegroundColor Yellow
    git -C $INSTALL pull
} else {
    Write-Host "Cloning repo..." -ForegroundColor Yellow
    git clone $REPO_URL $INSTALL
}
Write-Host "Repo OK at $INSTALL" -ForegroundColor Green

# ── 5. Python venv + dependencies ────────────────────────────────────────────
Write-Host "Creating venv with Python 3.12..." -ForegroundColor Yellow
Set-Location $BOT_DIR
uv venv --python 3.12 .venv
uv pip install --python "$VENV\Scripts\python.exe" -r requirements.txt
Write-Host "Venv OK" -ForegroundColor Green

# ── 6. WMI workaround (sitecustomize.py) ─────────────────────────────────────
$SITE = & $PYTHON -c "import site; print([p for p in __import__('sys').path if 'site-packages' in p][0])"
$CUSTOMIZE = "$SITE\sitecustomize.py"
if (-not (Test-Path $CUSTOMIZE)) {
    Write-Host "Applying WMI workaround..." -ForegroundColor Yellow
    @'
try:
    import platform
    def _wmi_disabled(*a, **k):
        raise OSError("WMI disabled by sitecustomize.py")
    platform._wmi_query = _wmi_disabled
except Exception:
    pass
'@ | Out-File -FilePath $CUSTOMIZE -Encoding utf8
}
Write-Host "WMI workaround OK" -ForegroundColor Green

# ── 7. .env file ──────────────────────────────────────────────────────────────
$ENV_FILE = "$BOT_DIR\.env"
if (-not (Test-Path $ENV_FILE)) {
    Write-Host "Writing .env template..." -ForegroundColor Yellow
    $envLines = @(
        "SUPABASE_URL=FILL_IN",
        "SUPABASE_SERVICE_KEY=FILL_IN",
        "ANTHROPIC_API_KEY=FILL_IN",
        "MT5_LOGIN=FILL_IN",
        "MT5_PASSWORD=FILL_IN",
        "MT5_SERVER=FILL_IN",
        "MT5_PATH=C:/Program Files/MetaTrader 5/terminal64.exe",
        "MCP_SERVER_COMMAND=metatrader-mcp-server"
    )
    $envLines | Out-File -FilePath $ENV_FILE -Encoding utf8
    Write-Host ".env template written — edit $ENV_FILE with your real credentials before starting the bot" -ForegroundColor Yellow
} else {
    Write-Host ".env already exists — skipping" -ForegroundColor Yellow
}

# ── 8. MT5 terminal ───────────────────────────────────────────────────────────
if (-not (Test-Path $MT5_EXE)) {
    Write-Host "Downloading MetaTrader 5 installer..." -ForegroundColor Yellow
    $MT5_INSTALLER = "$env:TEMP\mt5setup.exe"
    Invoke-WebRequest -Uri "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe" `
        -OutFile $MT5_INSTALLER -UseBasicParsing
    Write-Host "Launching MT5 installer — complete the GUI install, then press Enter here to continue." -ForegroundColor Cyan
    Start-Process $MT5_INSTALLER -Wait
    Read-Host "  Press Enter once MT5 is installed and you have logged into your broker account"
} else {
    Write-Host "MT5 already installed" -ForegroundColor Green
}

# ── 9. Smoke-test the bot imports ─────────────────────────────────────────────
Write-Host "Testing bot imports..." -ForegroundColor Yellow
$test = & $PYTHON -c "import pandas; import pandas_ta; from src.bot import TradingBot; print('imports OK')"
if ($LASTEXITCODE -eq 0) {
    Write-Host "Import test OK" -ForegroundColor Green
} else {
    Write-Host "Import test FAILED:" -ForegroundColor Red
    Write-Host $test
    Write-Host "Fix the error above before continuing." -ForegroundColor Red
    exit 1
}

# ── 10. Auto-login ────────────────────────────────────────────────────────────
# MT5 requires a real interactive desktop (Session 0 services cannot open a GUI).
# Auto-login ensures the desktop is always up after a reboot so the Task Scheduler
# logon tasks below actually fire.
# NOTE: password is stored in plain text at HKLM\...\Winlogon\DefaultPassword.
#       Acceptable on a single-user trading VPS; do not use on shared machines.
Write-Host "Configuring auto-login for $env:USERNAME..." -ForegroundColor Yellow
$adminPassword = Read-Host "  Enter Administrator password (stored for auto-login)" -AsSecureString
$plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($adminPassword)
)
$wlPath = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"
Set-ItemProperty -Path $wlPath -Name "AutoAdminLogon"   -Value "1"            -Type String
Set-ItemProperty -Path $wlPath -Name "DefaultUserName"  -Value $env:USERNAME  -Type String
Set-ItemProperty -Path $wlPath -Name "DefaultDomainName"-Value $env:COMPUTERNAME -Type String
Set-ItemProperty -Path $wlPath -Name "DefaultPassword"  -Value $plain         -Type String
Remove-ItemProperty -Path $wlPath -Name "AutoLogonCount" -ErrorAction SilentlyContinue
Write-Host "Auto-login configured — takes effect on next reboot" -ForegroundColor Green

# ── 11. Create start_bot.ps1 wrapper ─────────────────────────────────────────
# Task Scheduler fires this once at logon. The while-loop inside handles
# restarts so the bot comes back automatically if it crashes.
Write-Host "Writing start_bot.ps1 wrapper..." -ForegroundColor Yellow
$wrapperContent = @"
# Auto-generated by vps_setup.ps1 — do not edit by hand
`$env:PYTHONUNBUFFERED = "1"
Set-Location "$BOT_DIR"

# Wait for MT5 to finish connecting to the broker before the bot starts
Start-Sleep 60

while (`$true) {
    `$ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content "$LOG_DIR\run.log" "[START `$ts]"

    & "$PYTHON" -u main.py >> "$LOG_DIR\run.log" 2>> "$LOG_DIR\run.err"

    `$code = `$LASTEXITCODE
    `$ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content "$LOG_DIR\run.log" "[EXIT `$code at `$ts -- restarting in 5s]"
    Start-Sleep 5
}
"@
Set-Content -Path "$BOT_DIR\start_bot.ps1" -Value $wrapperContent -Encoding utf8
Write-Host "start_bot.ps1 written" -ForegroundColor Green

# ── 12. Register Task Scheduler tasks ────────────────────────────────────────
Write-Host "Registering Task Scheduler tasks..." -ForegroundColor Yellow

# Remove old tasks if they exist
foreach ($name in @("Algobot", "AlgobotMT5")) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
}

$user = "$env:COMPUTERNAME\$env:USERNAME"

# -- MT5 task: launch terminal at logon, restart on failure --
$mt5Action   = New-ScheduledTaskAction -Execute $MT5_EXE
$mt5Trigger  = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$mt5Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 10 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew
$mt5Principal = New-ScheduledTaskPrincipal `
    -UserId $user -LogonType Interactive -RunLevel Highest

Register-ScheduledTask `
    -TaskName  "AlgobotMT5" `
    -Action    $mt5Action `
    -Trigger   $mt5Trigger `
    -Settings  $mt5Settings `
    -Principal $mt5Principal `
    -Description "MetaTrader 5 — launched at logon for Algobot" `
    -Force | Out-Null

# -- Bot task: run start_bot.ps1 at logon (60s delay is inside the wrapper) --
$botAction   = New-ScheduledTaskAction `
    -Execute   "powershell.exe" `
    -Argument  "-NonInteractive -ExecutionPolicy Bypass -File `"$BOT_DIR\start_bot.ps1`"" `
    -WorkingDirectory $BOT_DIR
$botTrigger  = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$botSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 10 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew
$botPrincipal = New-ScheduledTaskPrincipal `
    -UserId $user -LogonType Interactive -RunLevel Highest

Register-ScheduledTask `
    -TaskName  "Algobot" `
    -Action    $botAction `
    -Trigger   $botTrigger `
    -Settings  $botSettings `
    -Principal $botPrincipal `
    -Description "Algobot trading bot — started at logon, self-restarts on crash" `
    -Force | Out-Null

Write-Host "Tasks registered" -ForegroundColor Green

# ── 13. Start both tasks now (no need to reboot to verify) ───────────────────
Write-Host "Starting tasks..." -ForegroundColor Yellow
Start-ScheduledTask -TaskName "AlgobotMT5"
Start-Sleep 3
Start-ScheduledTask -TaskName "Algobot"
Start-Sleep 3

$mt5State = (Get-ScheduledTask -TaskName "AlgobotMT5").State
$botState  = (Get-ScheduledTask -TaskName "Algobot").State

Write-Host "AlgobotMT5 : $mt5State" -ForegroundColor $(if ($mt5State -eq 'Running') { 'Green' } else { 'Red' })
Write-Host "Algobot     : $botState"  -ForegroundColor $(if ($botState  -eq 'Running') { 'Green' } else { 'Red' })

Write-Host @"

=== Setup complete ===

Both tasks are registered and will restart automatically at every logon.
MT5 starts immediately; the bot waits 60s then loops forever.

Useful commands:
  Start-ScheduledTask -TaskName Algobot          # start bot manually
  Stop-ScheduledTask  -TaskName Algobot          # stop bot
  Start-ScheduledTask -TaskName AlgobotMT5       # start MT5 manually
  (Get-ScheduledTask  -TaskName Algobot).State   # check status

Logs:
  $LOG_DIR\run.log   (stdout)
  $LOG_DIR\run.err   (stderr)
  Get-Content $LOG_DIR\run.err -Tail 30 -Wait

After a reboot the sequence is:
  1. Windows boots and auto-logs in as $env:USERNAME
  2. MT5 launches (AlgobotMT5 task fires)
  3. Bot launches 60s later (Algobot task fires, wrapper sleeps first)
"@ -ForegroundColor Cyan
