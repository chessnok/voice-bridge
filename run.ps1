# Запуск голосового ассистента на Windows: сервер агента + голосовой клиент.
# Использование:  .\run.ps1            (push-to-talk, Ctrl+K)
#                 .\run.ps1 --talk     (живой разговор)
# Ctrl+C гасит обоих. Автообновление при каждом запуске (VB_NO_UPDATE=1 отключает).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
New-Item -ItemType Directory -Force -Path logs | Out-Null

# --- автообновление ---
if (-not $env:VB_NO_UPDATE) {
    try {
        git pull --ff-only --quiet 2>$null
        Write-Host "[run] версия: $(git log -1 --format='%h %s')"
    } catch {
        Write-Host "[run] обновление недоступно - работаю на текущей версии"
    }
}
uv sync -q

$py = ".venv\Scripts\python.exe"
$port = if ($env:VB_SERVER_PORT) { $env:VB_SERVER_PORT } else { "8765" }

# --- добиваем предыдущий сервер, если висит ---
Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
    Where-Object { $_.CommandLine -match "voice_bridge\.server" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

# --- сервер агента (фоном) ---
$env:VB_SERVER_PORT = $port
$server = Start-Process -FilePath $py -ArgumentList "-m", "voice_bridge.server" `
    -RedirectStandardOutput "logs\server.log" -RedirectStandardError "logs\server.err.log" `
    -WindowStyle Hidden -PassThru

try {
    # ждём порт
    $ready = $false
    foreach ($i in 1..20) {
        try {
            Invoke-WebRequest -Uri "http://127.0.0.1:$port/" -TimeoutSec 1 -ErrorAction Stop | Out-Null
            $ready = $true; break
        } catch {
            if ($_.Exception.Response) { $ready = $true; break }  # 404 = сервер жив
        }
        if ($server.HasExited) {
            Write-Host "[run] сервер не стартовал, лог:"; Get-Content logs\server.err.log -Tail 5
            exit 1
        }
        Start-Sleep -Milliseconds 500
    }
    Write-Host "[run] сервер агента: http://127.0.0.1:$port (лог: logs\server.log)"

    # --- голосовой клиент (на переднем плане) ---
    $env:VB_AGENT_URL = "http://127.0.0.1:$port"
    & $py -m voice_bridge.main @args
} finally {
    if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id -Force }
    Write-Host "[run] сервер остановлен"
}
