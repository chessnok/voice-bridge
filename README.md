# voice-bridge

Голосовой ассистент для слабовидящего писателя. Два режима: **живой разговор**
(говоришь — отвечает голосом через ~0.5 с, можно перебивать) и **push-to-talk**
(зажал Ctrl+K — сказал — отпустил). Агент пишет и читает стихи и документы (docx),
шлёт почту, водит браузер — всё строго внутри выделенной папки, без shell-доступа.

Архитектура: [docs/architecture.md](docs/architecture.md) ·
Оценка качества: `evals/run_eval.py` (Langfuse) ·
Ресерч-материалы: [docs/research-realtime-voice.md](docs/research-realtime-voice.md)

## Установка на Windows

```powershell
# 1. Зависимости (один раз)
winget install Git.Git astral-sh.uv pandoc ffmpeg

# 2. Код
git clone https://github.com/chessnok/voice-bridge.git
cd voice-bridge

# 3. Ключ
copy .env.example .env
notepad .env        # вставить OPENAI_API_KEY=sk-...

# 4. Проверка
powershell -ExecutionPolicy Bypass -File run.ps1 --talk

# 5. Автостарт при входе в Windows (фоновый режим)
powershell -ExecutionPolicy Bypass -File install-autostart.ps1
```

## Установка на Linux

```bash
sudo apt install -y git pandoc ffmpeg   # + uv: https://docs.astral.sh/uv/
git clone https://github.com/chessnok/voice-bridge.git && cd voice-bridge
cp .env.example .env && $EDITOR .env    # OPENAI_API_KEY
./run.sh --talk                          # проверка
./install-autostart.sh                   # автостарт (systemd --user)
```

## Обновления

Автоматически: каждый запуск `run.sh` / `run.ps1` делает `git pull --ff-only`
и `uv sync`. Нет сети или конфликт — молча работает на текущей версии.
Отключить: `VB_NO_UPDATE=1`.

## Режимы

| Команда | Режим |
|---|---|
| `run.ps1 --talk` / `./run.sh --talk` | живой разговор: Realtime API (быстро, ~1 с, перебивания) |
| `... --talk-cascade` | живой разговор: каскад STT→LLM→TTS (медленнее, ~4-6 с, понимает заметно лучше) |
| `run.ps1` / `./run.sh` | push-to-talk по Ctrl+K |
| `... --text "команда"` | текстовый прогон без микрофона (отладка) |

## Опции

- **Почта**: `copy email_accounts.json.example email_accounts.json` + реквизиты SMTP
  (несколько ящиков), `copy mcp_servers.json.example mcp_servers.json`.
- **Браузер**: `npm i -g agent-browser` (или форк: `VB_AGENT_BROWSER_BIN=путь`).
- **Бэкенд на сервере**: там — `python -m voice_bridge.server` (`VB_SERVER_BIND`,
  обязателен `VB_AGENT_TOKEN`), на клиенте — `VB_AGENT_URL` в .env.
- **Трейсинг/оценки**: ключи Langfuse в .env; offline-оценка — `python evals/run_eval.py`.
- Рабочая папка агента: `~/Ассистент` (память: SOUL.md, MEMORY.md, memory/).

## Безопасность

Файлы — только внутри рабочей папки (jail), инструменты — белый список без shell,
браузер — ограниченные подкоманды, почта — после голосового подтверждения,
HTTP-бэкенд не стартует наружу без токена.
