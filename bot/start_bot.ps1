$env:PYTHONUNBUFFERED = "1"
Set-Location "C:\Algobot\bot"

Start-Sleep 60

while ($true) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content "C:\Algobot\bot\run.log" "[START $ts]"

    & "C:\Algobot\bot\.venv\Scripts\python.exe" -u main.py >> "C:\Algobot\bot\run.log" 2>> "C:\Algobot\bot\run.err"

    $code = $LASTEXITCODE
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content "C:\Algobot\bot\run.log" "[EXIT $code at $ts -- restarting in 5s]"
    Start-Sleep 5
}
