# Algobot VPS Setup Script
# Run as Administrator in PowerShell on a fresh Windows Server 2019/2022
# Usage: Right-click PowerShell -> "Run as Administrator", then paste and run.
#
# What this does:
#   1. Installs Git, Python (via uv), NSSM
#   2. Clones the repo
#   3. Creates the venv and installs dependencies
#   4. Applies the WMI workaround (sitecustomize.py)
#   5. Writes .env with baked-in credentials (delete bot\.env to re-run prompt)
#   6. Installs MT5 terminal
#   7. Registers the bot as a Windows service via NSSM (auto-start + auto-restart)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$REPO_URL  = "https://github.com/Pokerxer/Algobot.git"
$INSTALL   = "C:\Algobot"
$BOT_DIR   = "$INSTALL\bot"
$VENV      = "$BOT_DIR\.venv"
$PYTHON    = "$VENV\Scripts\python.exe"
$SERVICE   = "Algobot"

Write-Host "`n=== Algobot VPS Setup ===" -ForegroundColor Cyan

# ── 1. Chocolatey (package manager) ──────────────────────────────────────────
if (-not (Get-Command choco -ErrorAction SilentlyContinue)) {
    Write-Host "Installing Chocolatey..." -ForegroundColor Yellow
    Set-ExecutionPolicy Bypass -Scope Process -Force
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
    Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
    $env:PATH += ";$env:ALLUSERSPROFILE\chocolatey\bin"
}
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

# ── 4. NSSM (service manager) ────────────────────────────────────────────────
if (-not (Get-Command nssm -ErrorAction SilentlyContinue)) {
    Write-Host "Installing NSSM..." -ForegroundColor Yellow
    choco install nssm -y --no-progress
    $env:PATH += ";C:\ProgramData\chocolatey\bin"
}
Write-Host "NSSM OK" -ForegroundColor Green

# ── 5. Clone repo ─────────────────────────────────────────────────────────────
if (Test-Path $INSTALL) {
    Write-Host "Updating existing repo..." -ForegroundColor Yellow
    git -C $INSTALL pull
} else {
    Write-Host "Cloning repo..." -ForegroundColor Yellow
    git clone $REPO_URL $INSTALL
}
Write-Host "Repo OK at $INSTALL" -ForegroundColor Green

# ── 6. Python venv + dependencies ────────────────────────────────────────────
Write-Host "Creating venv with Python 3.12..." -ForegroundColor Yellow
Set-Location $BOT_DIR
uv venv --python 3.12 .venv
uv pip install --python "$VENV\Scripts\python.exe" -r requirements.txt
Write-Host "Venv OK" -ForegroundColor Green

# ── 7. WMI workaround (sitecustomize.py) ─────────────────────────────────────
# Windows VPS WMI is usually healthy so this may not be needed, but applying
# it defensively costs nothing and prevents the pandas import hang if WMI
# is slow on first boot.
$SITE = & $PYTHON -c "import site; print([p for p in __import__('sys').path if 'site-packages' in p][0])"
$CUSTOMIZE = "$SITE\sitecustomize.py"
if (-not (Test-Path $CUSTOMIZE)) {
    Write-Host "Applying WMI workaround..." -ForegroundColor Yellow
    @'
# Defensive WMI workaround: if WMI is slow/hung, platform.uname() blocks
# pandas import. Force the registry fallback by making the query raise.
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

# ── 8. .env file ──────────────────────────────────────────────────────────────
# Credentials are baked in. To override, delete bot\.env and re-run the script.
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
    Write-Host ".env template written -- edit $ENV_FILE with your real credentials before starting the bot" -ForegroundColor Yellow
} else {
    Write-Host ".env already exists -- skipping" -ForegroundColor Yellow
}

# ── 9. MT5 terminal ───────────────────────────────────────────────────────────
$MT5_EXE = "C:\Program Files\MetaTrader 5\terminal64.exe"
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

# ── 10. Smoke-test the bot imports ───────────────────────────────────────────
Write-Host "Testing bot imports..." -ForegroundColor Yellow
$test = & $PYTHON -c "import pandas; import pandas_ta; from src.bot import TradingBot; print('imports OK')" 2>&1
if ($test -match "imports OK") {
    Write-Host "Import test OK" -ForegroundColor Green
} else {
    Write-Host "Import test FAILED:" -ForegroundColor Red
    Write-Host $test
    Write-Host "Fix the error above before continuing." -ForegroundColor Red
    exit 1
}

# ── 11. Register NSSM service ─────────────────────────────────────────────────
Write-Host "Registering '$SERVICE' Windows service..." -ForegroundColor Yellow

# Stop + remove if already exists
$existing = Get-Service -Name $SERVICE -ErrorAction SilentlyContinue
if ($existing) {
    nssm stop $SERVICE
    nssm remove $SERVICE confirm
}

nssm install $SERVICE $PYTHON
nssm set $SERVICE Arguments     "-u main.py"
nssm set $SERVICE AppDirectory  $BOT_DIR
nssm set $SERVICE AppEnvironmentExtra "PYTHONUNBUFFERED=1"
nssm set $SERVICE AppStdout     "$BOT_DIR\bot.log"
nssm set $SERVICE AppStderr     "$BOT_DIR\bot.err"
nssm set $SERVICE AppRotateFiles 1
nssm set $SERVICE AppRotateSeconds 86400
nssm set $SERVICE AppRotateBytes 10485760    # 10 MB rotate
nssm set $SERVICE Start         SERVICE_AUTO_START
nssm set $SERVICE ObjectName    LocalSystem
nssm set $SERVICE AppRestartDelay 5000       # 5s before restart on crash

nssm start $SERVICE
Start-Sleep -Seconds 5
$svc = Get-Service -Name $SERVICE
Write-Host "Service status: $($svc.Status)" -ForegroundColor $(if ($svc.Status -eq 'Running') { 'Green' } else { 'Red' })

Write-Host @"

=== Setup complete ===

Service '$SERVICE' is registered and $(if ($svc.Status -eq 'Running') { 'RUNNING' } else { 'NOT running — check bot.err' }).

Useful commands:
  nssm status Algobot          # check status
  nssm restart Algobot         # restart
  nssm stop Algobot            # stop
  Get-Content $BOT_DIR\bot.err -Tail 30   # view logs

Logs: $BOT_DIR\bot.log and $BOT_DIR\bot.err
"@ -ForegroundColor Cyan
