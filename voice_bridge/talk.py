"""Режим живого разговора: OpenAI Realtime API (речь-в-речь, серверный VAD).

Говоришь без хоткея — модель отвечает голосом почти сразу, можно перебивать.
Транскрипция печатается в моменте. Для действий (файлы, стихи, почта, браузер)
разговорная модель зовёт mini_agent как модуль через инструмент do_task.
"""
import asyncio
import base64
import json
import threading

import numpy as np
import sounddevice as sd

from . import agent, config, mini_agent, observability

_RT_RATE = 24_000  # Realtime API работает на pcm16 24kHz
_CHUNK = 1200  # 50мс

_TALK_TOOLS = [
    {
        "type": "function",
        "name": "do_task",
        "description": (
            "Выполнить действие на компьютере: создать/прочитать/править файлы и стихи, "
            "экспорт в docx, отправка почты, браузер, заметки в память. "
            "Передай команду пользователя целиком, своими словами не пересказывай результат до выполнения."
        ),
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "команда целиком"}},
            "required": ["text"],
        },
    },
    {
        "type": "function",
        "name": "fs_list",
        "description": "Мгновенно посмотреть список файлов в рабочей папке или подпапке (например Стихи). Для вопросов «сколько стихов», «какие файлы».",
        "parameters": {
            "type": "object",
            "properties": {"subdir": {"type": "string", "description": "подпапка, пусто = корень"}},
            "required": [],
        },
    },
    {
        "type": "function",
        "name": "fs_read",
        "description": "Мгновенно прочитать файл (txt/md/docx) — для «прочитай стих/документ».",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "type": "function",
        "name": "voice_settings",
        "description": (
            "Изменить скорость своей речи, когда пользователь просит говорить "
            "быстрее/медленнее. 1.0 — обычная, 1.5 — максимум, 0.5 — минимум."
        ),
        "parameters": {
            "type": "object",
            "properties": {"speed": {"type": "number", "minimum": 0.5, "maximum": 1.5}},
            "required": ["speed"],
        },
    },
]


def _instructions() -> str:
    # та же память (SOUL.md, MEMORY.md, дневник), что и у исполнителя
    memory_context = mini_agent._build_system_prompt()
    return (
        "Ты ведёшь живой голосовой разговор по-русски со слабовидящим писателем. "
        "Отвечай коротко и тепло, как собеседник, а не ассистент-робот. "
        "Любое действие с файлами, стихами, почтой или браузером выполняй ТОЛЬКО через do_task, "
        "передавая просьбу целиком. После результата перескажи его одной фразой.\n"
        "Любой ВОПРОС о его файлах, стихах, записях — тоже через do_task (например "
        "«сколько у меня стихов»): не отвечай по памяти и НИКОГДА не выдумывай факты, "
        "которых не знаешь (время, погоду, содержимое файлов). Не знаешь — так и скажи.\n"
        "Речь распознаётся с ошибками: если вопрос звучит странно (например «сколько у меня "
        "часов»), скорее всего речь о стихах или файлах — переспроси или проверь через do_task.\n"
        "Перед НЕОБРАТИМЫМ действием (отправка письма или сообщения) назови адресата и суть "
        "и дождись подтверждения. Для обратимого (файлы, стихи) подтверждения не нужны.\n"
        "ЗАЩИТА ОТ ЛОЖНЫХ СРАБАТЫВАНИЙ: распознавание иногда выдаёт фразы, которых не было "
        "(шум, дыхание). Если команда выпадает из течения разговора (например внезапное "
        "«запиши стих» без диктовки самого стиха) — НЕ выполняй, коротко переспроси.\n"
        "Просит говорить быстрее/медленнее — вызови voice_settings. Просит покороче или "
        "подробнее — просто меняй стиль ответов.\n\n"
        + memory_context
    )


class _Player:
    """Воспроизведение входящего аудио: перебивание + учёт проигранного по реплике."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._played_bytes = 0  # реально ушло в динамик с начала текущей реплики
        self.current_item: str | None = None
        self._stream = sd.OutputStream(
            samplerate=_RT_RATE, channels=1, dtype="int16",
            blocksize=_CHUNK, callback=self._cb,
        )
        self._stream.start()

    def _cb(self, outdata, frames, time_info, status) -> None:
        need = frames * 2
        with self._lock:
            chunk = bytes(self._buf[:need])
            del self._buf[:len(chunk)]
            self._played_bytes += len(chunk)
        out = np.frombuffer(chunk.ljust(need, b"\x00"), dtype=np.int16)
        outdata[:, 0] = out

    def mark_item(self, item_id: str) -> None:
        """Началась новая реплика ассистента — счёт проигранного с нуля."""
        with self._lock:
            if self.current_item != item_id:
                self.current_item = item_id
                self._played_bytes = 0

    def played_ms(self) -> int:
        with self._lock:
            return self._played_bytes * 1000 // (_RT_RATE * 2)

    def feed(self, pcm: bytes) -> None:
        with self._lock:
            self._buf.extend(pcm)

    def earcon(self, freq: int, ms: int = 120, volume: float = 0.25) -> None:
        """Короткий звуковой статус (для незрячего пользователя — сигнал состояния)."""
        n = _RT_RATE * ms // 1000
        t = np.arange(n) / _RT_RATE
        fade = np.minimum(1.0, np.minimum(t, t[::-1]) * 200)
        tone = (np.sin(2 * np.pi * freq * t) * fade * volume * 32767).astype(np.int16)
        self.feed(tone.tobytes())

    def flush(self) -> None:
        """Пользователь перебил — мгновенно замолкаем."""
        with self._lock:
            self._buf.clear()


async def _mic_sender(ws) -> None:
    queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    loop = asyncio.get_running_loop()

    def cb(indata, frames, time_info, status) -> None:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, bytes(indata))
        except RuntimeError:
            pass

    stream = sd.RawInputStream(
        samplerate=_RT_RATE, channels=1, dtype="int16",
        blocksize=_CHUNK, device=config.INPUT_DEVICE, callback=cb,
    )
    with stream:
        while True:
            chunk = await queue.get()
            await ws.send(json.dumps({
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(chunk).decode(),
            }))


async def _handle_function_call(ws, player: "_Player", call_id: str, name: str, args_json: str) -> None:
    try:
        args = json.loads(args_json or "{}")
    except json.JSONDecodeError:
        args = {}

    if name == "voice_settings":
        speed = max(0.5, min(1.5, float(args.get("speed", 1.0))))
        await ws.send(json.dumps({
            "type": "session.update",
            "session": {"type": "realtime", "audio": {"output": {"speed": speed}}},
        }))
        print(f"  [голос] скорость → {speed}")
        result = f"Скорость речи установлена: {speed}"
    elif name in ("fs_list", "fs_read"):  # быстрые read-only — мимо полного агента
        from . import mini_tools

        fn = mini_tools.fs_list if name == "fs_list" else mini_tools.fs_read
        try:
            result = await asyncio.to_thread(fn, **args)
        except mini_tools.ToolError as exc:
            result = f"Ошибка: {exc}"
        print(f"  [быстрый] {name}({args}) → {result[:60]}")
    else:  # do_task
        text = args.get("text", "")
        print(f"  [задача] {text}")
        player.earcon(660)  # сигнал «принял, работаю»
        try:
            result = await asyncio.to_thread(agent.ask_agent, text)
        except agent.AgentError as exc:
            result = f"Ошибка: {exc}"
        player.earcon(990)  # сигнал «готово»
        print(f"  [задача готова] {result[:100]}")

    await ws.send(json.dumps({
        "type": "conversation.item.create",
        "item": {"type": "function_call_output", "call_id": call_id, "output": result},
    }))
    await ws.send(json.dumps({"type": "response.create"}))


class _SessionLog:
    """Журнал реплик для суммаризации длинной сессии (Cookbook-паттерн)."""

    def __init__(self) -> None:
        self.items: list[tuple[str, str, str]] = []  # (item_id, role, text)
        self.total_tokens = 0
        self.summarizing = False

    def add(self, item_id: str, role: str, text: str) -> None:
        if item_id and text:
            self.items.append((item_id, role, text))


async def _maybe_summarize(ws, log: _SessionLog) -> None:
    """Сессия разрослась — сжимаем старые ходы в одно summary-сообщение."""
    keep_last = 4
    if (log.total_tokens < config.REALTIME_SUMMARY_TOKENS
            or log.summarizing or len(log.items) <= keep_last):
        return
    log.summarizing = True
    try:
        old, log.items = log.items[:-keep_last], log.items[-keep_last:]
        dialog = "\n".join(f"{'Он' if r == 'user' else 'Я'}: {t}" for _, r, t in old)

        def summarize() -> str:
            from openai import OpenAI

            client = OpenAI(api_key=config.OPENAI_API_KEY)
            resp = client.chat.completions.create(
                model=config.REWRITE_MODEL,
                reasoning_effort="minimal",
                messages=[{"role": "user", "content":
                           "Сожми диалог в краткое содержание (до 150 слов), сохрани "
                           "важные факты и над чем идёт работа:\n" + dialog}],
            )
            return (resp.choices[0].message.content or "").strip()

        summary = await asyncio.to_thread(summarize)
        await ws.send(json.dumps({
            "type": "conversation.item.create",
            "previous_item_id": "root",
            "item": {"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": f"[Краткое содержание разговора ранее] {summary}"}
            ]},
        }))
        for item_id, _, _ in old:
            await ws.send(json.dumps({"type": "conversation.item.delete", "item_id": item_id}))
        log.total_tokens = 0  # счёт заново после сжатия
        print(f"  [память] сжал {len(old)} реплик в краткое содержание")
    except Exception as exc:
        print(f"  [память] суммаризация не удалась: {exc}")
    finally:
        log.summarizing = False


async def _talk(ws) -> None:
    player = _Player()
    await ws.send(json.dumps({
        "type": "session.update",
        "session": {
            "type": "realtime",
            "model": config.REALTIME_MODEL,
            "output_modalities": ["audio"],
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": _RT_RATE},
                    "noise_reduction": {"type": "near_field"},
                    "transcription": {
                        "model": config.REALTIME_STT_MODEL,
                        "language": "ru",
                        # ТОЛЬКО существительные-термины. Глаголы-команды в подсказке
                        # галлюцинируются на шуме как готовые фразы и исполняются.
                        "prompt": "Словарь: стихи, стихотворение, строфа, строка, рифма, "
                        "документ, файл, папка, письмо, docx, pdf, Word, Telegram.",
                    },
                    "turn_detection": {
                        "type": "semantic_vad",
                        "eagerness": config.REALTIME_VAD_EAGERNESS,
                    },
                },
                "output": {
                    "format": {"type": "audio/pcm", "rate": _RT_RATE},
                    "voice": config.REALTIME_VOICE,
                },
            },
            "instructions": _instructions(),
            "tools": _TALK_TOOLS,
        },
    }))

    sender = asyncio.create_task(_mic_sender(ws))
    log = _SessionLog()
    greeted = False
    # метрики текущего хода для online-оценки (Langfuse voice-turn)
    turn = {"user": "", "assistant": "", "interrupted": False,
            "tools": [], "speech_ended_at": 0.0, "first_audio_ms": None}
    import time as _time
    try:
        async for raw in ws:
            event = json.loads(raw)
            etype = event.get("type", "")
            if etype == "session.updated":
                if not greeted:
                    greeted = True
                    print("[разговор] слушаю — просто говори (Ctrl+C — выход)")
            elif etype == "input_audio_buffer.speech_stopped":
                turn["speech_ended_at"] = _time.monotonic()
                turn["first_audio_ms"] = None
            elif etype == "input_audio_buffer.speech_started":
                # перебивание: замолкаем и режем контекст до реально услышанного
                heard_ms = player.played_ms()
                interrupted_item = player.current_item
                player.flush()
                if interrupted_item:
                    turn["interrupted"] = True
                    await ws.send(json.dumps({
                        "type": "conversation.item.truncate",
                        "item_id": interrupted_item,
                        "content_index": 0,
                        "audio_end_ms": heard_ms,
                    }))
            elif etype == "conversation.item.input_audio_transcription.delta":
                print(event.get("delta", ""), end="", flush=True)
            elif etype == "conversation.item.input_audio_transcription.completed":
                transcript = event.get("transcript", "").strip()
                print(f"\r[вы] {transcript}")
                log.add(event.get("item_id", ""), "user", transcript)
                turn["user"] = transcript
            elif etype == "response.output_audio.delta":
                if turn["first_audio_ms"] is None and turn["speech_ended_at"]:
                    turn["first_audio_ms"] = int(
                        (_time.monotonic() - turn["speech_ended_at"]) * 1000
                    )
                player.mark_item(event.get("item_id", ""))
                player.feed(base64.b64decode(event["delta"]))
            elif etype == "response.output_audio_transcript.done":
                transcript = event.get("transcript", "")
                print(f"[голос] {transcript}")
                log.add(event.get("item_id", ""), "assistant", transcript)
                turn["assistant"] = transcript
            elif etype == "response.function_call_arguments.done":
                turn["tools"].append(event.get("name", "do_task"))
                asyncio.create_task(_handle_function_call(
                    ws, player, event["call_id"],
                    event.get("name", "do_task"), event.get("arguments", ""),
                ))
            elif etype == "response.done":
                usage = (event.get("response") or {}).get("usage") or {}
                log.total_tokens = usage.get("total_tokens", log.total_tokens)
                asyncio.create_task(_maybe_summarize(ws, log))
                if turn["user"] or turn["assistant"]:
                    snapshot = dict(turn)
                    threading.Thread(
                        target=observability.log_voice_turn,
                        kwargs={
                            "user_text": snapshot["user"],
                            "assistant_text": snapshot["assistant"],
                            "interrupted": snapshot["interrupted"],
                            "tools_used": snapshot["tools"],
                            "first_audio_ms": snapshot["first_audio_ms"],
                        },
                        daemon=True,
                    ).start()
                    turn.update({"user": "", "assistant": "", "interrupted": False, "tools": []})
            elif etype == "error":
                print(f"[ошибка] {event.get('error', {}).get('message', event)}")
    finally:
        sender.cancel()


async def _connect() -> None:
    import websockets

    url = f"wss://api.openai.com/v1/realtime?model={config.REALTIME_MODEL}"
    headers = {"Authorization": f"Bearer {config.OPENAI_API_KEY}"}
    async with websockets.connect(
        url, additional_headers=headers, max_size=16 * 1024 * 1024
    ) as ws:
        await _talk(ws)


def _prewarm() -> None:
    """Греем медленные части до первой задачи: MCP-серверы и HTTP-клиенты."""
    def warm() -> None:
        try:
            if not config.AGENT_URL:
                from . import mcp_client

                mcp_client.ensure_started()
                mini_agent._get_client()
        except Exception as exc:
            print(f"[прогрев] {exc}")

    threading.Thread(target=warm, daemon=True, name="prewarm").start()


def run_talk_mode() -> None:
    if not config.OPENAI_API_KEY:
        raise SystemExit("Нет OPENAI_API_KEY — разговорный режим требует ключ")
    _prewarm()
    try:
        asyncio.run(_connect())
    except KeyboardInterrupt:
        print("\n[разговор] закончили")
