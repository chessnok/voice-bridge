# Автостарт на Windows: задача планировщика при входе пользователя.
# Службой Windows делать нельзя — службы не имеют доступа к микрофону/динамикам
# пользовательской сессии. Запуск:  .\install-autostart.ps1   (один раз)
#          другой режим:  .\install-autostart.ps1 -Mode --talk
# Удалить:  Unregister-ScheduledTask -TaskName VoiceBridge -Confirm:$false
param([string]$Mode = "--talk-cascade")
$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$repo\run.ps1`" $Mode" `
    -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
# задержка после входа: даём подняться сети (git pull/uv) и аудиоустройствам,
# иначе клиент падает на старте и кажется, что автостарт «не сработал»
$trigger.Delay = "PT30S"
$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName "VoiceBridge" -Action $action -Trigger $trigger `
    -Settings $settings -Description "Голосовой ассистент: автозапуск при входе" -Force

Write-Host "Готово: ассистент будет стартовать при входе в Windows (задача VoiceBridge)."
Write-Host "Запустить прямо сейчас:  Start-ScheduledTask -TaskName VoiceBridge"
