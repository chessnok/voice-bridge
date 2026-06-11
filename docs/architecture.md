# Архитектура voice-bridge

Голосовой ассистент для слабовидящего писателя. Два режима ввода, один агент-исполнитель,
вся работа с файлами — в изолированной папке.

```mermaid
flowchart TB
    subgraph CLIENT["КЛИЕНТ (машина пользователя)"]
        MIC[Микрофон]
        SPK[Динамики]
        subgraph TALK["Talk-режим (./run.sh --talk)"]
            WS[WebSocket-клиент talk.py]
            PLAYER[Player: барж-ин,<br/>учёт проигранного, earcons]
        end
        subgraph PTT["PTT-режим (Ctrl+K)"]
            REC[Recorder: кольцевой буфер 0.3с]
            STT[STT gpt-4o-transcribe<br/>+ словарь жаргона]
            REF[Корректор gpt-5-mini<br/>чинит расшифровку по контексту]
            TTS[edge-tts стрим → ffplay]
        end
    end

    subgraph OAI["OpenAI Realtime API"]
        RT[gpt-realtime-2<br/>semantic VAD eagerness=high<br/>голос marin, speed 0.5-1.5]
        RTSTT[транскрипция gpt-4o-transcribe]
    end

    subgraph BACKEND["БЭКЕНД (локально или сервер: python -m voice_bridge.server)"]
        ROUTER[agent.py роутер:<br/>VB_AGENT_URL? HTTP : локально]
        HTTP[server.py HTTP /ask<br/>Bearer-токен]
        subgraph MINI["mini_agent (gpt-5.1, tool-loop, без shell)"]
            PROMPT[Системный промпт =<br/>правила + SOUL.md + MEMORY.md + дневник]
            TOOLS[fs_list / fs_read / fs_write / fs_append<br/>export_docx · browser · memory_note]
            SESS[sessions/voice.json<br/>история диалога]
        end
        subgraph MCPS["MCP-серверы (mcp_servers.json)"]
            EMAIL[mcp_email: несколько ящиков<br/>email_accounts.json]
        end
        JAIL[(~/Ассистент<br/>jail: Стихи/*.md, *.docx,<br/>SOUL.md, MEMORY.md, memory/)]
        PANDOC[pandoc → docx]
        ABR[agent-browser CLI<br/>форк chessnok/agent-browser]
    end

    LF[(Langfuse<br/>трейсы, токены, стоимость<br/>опционально)]

    MIC -->|pcm16 24kHz| WS <-->|аудио + события| RT
    RT --> RTSTT
    RT -->|"fs_list/fs_read (read-only, мгновенно)"| TOOLS
    RT -->|do_task| ROUTER
    RT -->|voice_settings| WS
    WS --> PLAYER --> SPK

    MIC --> REC --> STT --> REF --> ROUTER
    ROUTER -->|ответ| TTS --> SPK

    ROUTER <--> HTTP
    ROUTER --> MINI
    HTTP --> MINI
    TOOLS --> JAIL
    TOOLS --> PANDOC
    TOOLS --> ABR
    MINI <--> MCPS
    MINI -.->|langfuse.openai| LF
```

## Потоки

**Живой разговор**: микрофон → Realtime API (VAD сам режет реплики) → голос в ответ ~0.5с.
Болтовня — модель сама; вопросы о файлах — прямые fs_list/fs_read (1 шаг);
действия — do_task → mini_agent (earcon «работаю» → earcon «готово»).
Перебивание: flush плеера + conversation.item.truncate по проигранным мс.
Сессия >12k токенов → старые ходы сжимаются в summary (gpt-5-mini).

**PTT**: зажал Ctrl+K → говоришь → отпустил → STT → корректор → агент → озвучка стримом.

**Клиент-сервер**: бэкенд выносится на сервер (VB_SERVER_BIND + VB_AGENT_TOKEN),
локально остаётся только звук. Память и файлы живут рядом с бэкендом.

## Безопасность

- Файлы — только внутри ~/Ассистент (`_safe_path` отбивает ../ и абсолютные пути).
- Белый список инструментов, shell-доступа нет вообще.
- Браузер — только разрешённые подкоманды agent-browser.
- HTTP-бэкенд наружу не стартует без токена.
- Почта/WhatsApp — только после голосового подтверждения адресата.

## Конфигурация (всё через .env / VB_*)

| Группа | Ключи |
|---|---|
| Realtime | VB_REALTIME_MODEL, VB_REALTIME_VOICE, VB_REALTIME_STT_MODEL, VB_VAD_EAGERNESS, VB_RT_SUMMARY_TOKENS |
| PTT | VB_HOTKEY, VB_STT, VB_STT_PROMPT, VB_REWRITE_MODEL, VB_TTS_VOICE |
| Агент | VB_MINI_MODEL, VB_MINI_REASONING, VB_MINI_WORKDIR, VB_MINI_MAX_STEPS |
| Клиент-сервер | VB_AGENT_URL, VB_AGENT_TOKEN, VB_SERVER_BIND, VB_SERVER_PORT |
| Интеграции | VB_AGENT_BROWSER_BIN, mcp_servers.json, email_accounts.json |
| Трейсинг | LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_BASE_URL |
