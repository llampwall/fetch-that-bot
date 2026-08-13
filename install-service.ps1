## Install fetch-bot as a Windows service via NSSM
## Run as Administrator

$nssm = "C:\ProgramData\chocolatey\bin\nssm.exe"

# Remove if already exists
& $nssm stop fetch-bot 2>$null
& $nssm remove fetch-bot confirm 2>$null

# Install
& $nssm install fetch-bot "P:\software\fetch\.venv\Scripts\pythonw.exe" "P:\software\fetch\main.py"
& $nssm set fetch-bot AppDirectory "P:\software\fetch"
& $nssm set fetch-bot AppStdout "P:\software\fetch\logs\out.log"
& $nssm set fetch-bot AppStderr "P:\software\fetch\logs\error.log"
# Rotate logs at 10MB; AppRotateOnline lets NSSM rotate without a service restart
& $nssm set fetch-bot AppRotateFiles 1
& $nssm set fetch-bot AppRotateOnline 1
& $nssm set fetch-bot AppRotateBytes 10485760
& $nssm set fetch-bot AppRestartDelay 5000
& $nssm set fetch-bot AppStopMethodSkip 6
& $nssm set fetch-bot AppExit Default Restart
& $nssm set fetch-bot DisplayName "Fetch Bot"
& $nssm set fetch-bot Description "Telegram media extraction bot"
# Delayed start: SERVICE_AUTO_START raced the P: volume at boot on 2026-08-10 and
# failed with "The system cannot open the file" before the app ever ran.
& $nssm set fetch-bot Start SERVICE_DELAYED_AUTO_START

# Start the service
& $nssm start fetch-bot

Write-Host "`nDone. Service status:"
& $nssm status fetch-bot
