#!/usr/bin/env bash
# Запуск голосового ассистента целиком: сервер агента + голосовой клиент.
# Сервер на loopback:8765, клиент ходит в него по HTTP. Ctrl+C гасит обоих.
set -euo pipefail

cd "$(dirname "$0")"
PY=".venv/bin/python"
PORT="${VB_SERVER_PORT:-8765}"
mkdir -p logs

# автообновление: тихий git pull + синк зависимостей; при сбое едем на текущей версии
if [ -z "${VB_NO_UPDATE:-}" ] && git rev-parse --git-dir >/dev/null 2>&1; then
  if git pull --ff-only --quiet 2>/dev/null; then
    echo "[run] версия: $(git log -1 --format='%h %s' 2>/dev/null)"
  else
    echo "[run] обновление недоступно (нет сети/конфликт) — работаю на текущей версии"
  fi
fi
uv sync -q 2>/dev/null || { echo "Ставлю зависимости..."; uv sync; }

# добиваем предыдущий сервер, если порт занят (иначе bind упадёт)
if pkill -f "python -m voice_bridge.server" 2>/dev/null; then
  echo "[run] остановил предыдущий сервер"
  sleep 0.5
fi

# сервер агента (фоном); лог с метками времени пишет сам через vblog,
# редирект ловит только вывод до его включения (ошибки самого старта)
VB_SERVER_PORT="$PORT" VB_SERVER_LOG="logs/server.log" "$PY" -m voice_bridge.server >> logs/server.log 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null; wait $SERVER_PID 2>/dev/null; echo; echo "[run] сервер остановлен"' EXIT

# ждём порт
for _ in $(seq 1 20); do
  if curl -s -o /dev/null "http://127.0.0.1:$PORT/"; then break; fi
  if ! kill -0 $SERVER_PID 2>/dev/null; then
    echo "[run] сервер не стартовал, лог:"; tail -5 logs/server.log; exit 1
  fi
  sleep 0.5
done
echo "[run] сервер агента: http://127.0.0.1:$PORT (лог: logs/server.log)"

# голосовой клиент (на переднем плане)
VB_AGENT_URL="http://127.0.0.1:$PORT" "$PY" -m voice_bridge.main "$@"
