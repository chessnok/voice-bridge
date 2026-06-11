# Автостарт на Windows: задача планировщика при входе пользователя.
# Службой Windows делать нельзя — службы не имеют доступа к микрофону/динамикам
# пользовательской сессии. Запуск:  .\install-autostart.ps1   (один раз)
# Удалить:  Unregister-ScheduledTask -TaskName VoiceBridge -Confirm:$false
$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$repo\run.ps1`" --talk" `
    -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName "VoiceBridge" -Action $action -Trigger $trigger `
    -Settings $settings -Description "Голосовой ассистент: автозапуск при входе" -Force

Write-Host "Готово: ассистент будет стартовать при входе в Windows (задача VoiceBridge)."
Write-Host "Запустить прямо сейчас:  Start-ScheduledTask -TaskName VoiceBridge"
