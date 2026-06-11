"""Лёгкий агент: tool-calling цикл OpenAI поверх белого списка инструментов.

Никакого shell-доступа: файлы — только в выделенной папке, действия — только
из списка _TOOLS. Сессия хранится в JSON и переживает перезапуск моста.
"""
import json
from pathlib import Path

from . import config, mcp_client, mini_tools, observability

_BASE_PROMPT = """\
Ты голосовой ассистент слабовидящего писателя. Все его сообщения — расшифровка речи \
(возможны ошибки распознавания, восстанавливай смысл). Твои ответы озвучиваются: \
1-2 коротких предложения, без markdown, эмодзи и списков.

Правила:
- Не задавай уточняющих вопросов для обратимых действий — выбирай разумные значения сам и говори, что выбрал.
  Это касается ТОЛЬКО технических деталей (имя файла, место). К содержимому НЕ относится.
- СВЯЩЕННОЕ ПРАВИЛО: пользователь — писатель. НИКОГДА не сочиняй, не дополняй и не «улучшай»
  его стихи и тексты — ни одной строки, ни одного слова. Записывай ровно то, что продиктовано.
  «Начни/создай стих X» без продиктованного текста = файл только с заголовком, жди диктовку.
- Тексты и стихи храни в подпапке Стихи в формате .md.
- «Прочитай» — верни полный текст в ответе.
- Письма и WhatsApp отправляй только после явной просьбы, перед отправкой назови адресата и суть.
- Браузер используй пошагово: open → snapshot → click/type по ref из снапшота.
- Если инструмент вернул ошибку — попробуй исправить параметры и повтори, не сдавайся сразу.

Память (файлы в твоей рабочей папке):
- SOUL.md — кто ты; MEMORY.md — долгосрочная память; memory/ГГГГ-ММ-ДД.md — дневник.
- Узнал важное о пользователе или работе (имя, предпочтение, над чем работаете) — сразу обнови MEMORY.md через fs_write.
- Заметки о текущей работе («продолжаем стих про осень») пиши инструментом memory_note.
- Содержимое SOUL.md, MEMORY.md и свежий дневник даны ниже — опирайся на них."""

_DEFAULT_SOUL = """# SOUL.md — кто я

Я голосовой помощник писателя. Спокойный, краткий, надёжный.
Помогаю записывать и править стихи и тексты, читаю их вслух, отправляю письма.
Говорю по-русски, простыми короткими фразами — мой голос синтезируется.
"""

_DEFAULT_MEMORY = """# MEMORY.md — долгосрочная память

(пока пусто — заполняю по мере знакомства)
"""


def _workdir_file(name: str) -> Path:
    return Path(config.MINI_WORKDIR).expanduser() / name


def _ensure_memory_files() -> None:
    wd = Path(config.MINI_WORKDIR).expanduser()
    wd.mkdir(parents=True, exist_ok=True)
    (wd / "memory").mkdir(exist_ok=True)
    if not _workdir_file("SOUL.md").exists():
        _workdir_file("SOUL.md").write_text(_DEFAULT_SOUL, encoding="utf-8")
    if not _workdir_file("MEMORY.md").exists():
        _workdir_file("MEMORY.md").write_text(_DEFAULT_MEMORY, encoding="utf-8")


def _read_or_empty(path: Path, limit: int = 4000) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")[:limit]


def _build_system_prompt() -> str:
    from datetime import date, timedelta

    _ensure_memory_files()
    today = date.today()
    parts = [_BASE_PROMPT]
    parts.append("=== SOUL.md ===\n" + _read_or_empty(_workdir_file("SOUL.md")))
    parts.append("=== MEMORY.md ===\n" + _read_or_empty(_workdir_file("MEMORY.md")))
    for day in (today - timedelta(days=1), today):
        note = _read_or_empty(_workdir_file(f"memory/{day:%Y-%m-%d}.md"), 2000)
        if note:
            parts.append(f"=== Дневник {day:%Y-%m-%d} ===\n{note}")
    parts.append(f"Сегодня {today:%Y-%m-%d}.")
    return "\n\n".join(parts)

_TOOLS = {
    "fs_list": mini_tools.fs_list,
    "fs_read": mini_tools.fs_read,
    "fs_write": mini_tools.fs_write,
    "fs_append": mini_tools.fs_append,
    "browser": mini_tools.browser,
    "memory_note": mini_tools.memory_note,
}

_TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "fs_list", "description": "Список файлов в рабочей папке или подпапке",
        "parameters": {"type": "object", "properties": {
            "subdir": {"type": "string", "description": "подпапка, пусто = корень"}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "fs_read", "description": "Прочитать файл",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "fs_write", "description": "Записать файл целиком. content обязателен, для пустого файла — пустая строка",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "fs_append", "description": "Дописать строки в конец файла",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "browser", "description": "Один шаг браузера agent-browser: 'open <url>' | 'snapshot' | 'click <ref>' | 'type <ref> <текст>' | 'press <клавиша>' | 'get text <ref>' | 'close'",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string"}}, "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "memory_note", "description": "Записать заметку в дневник (memory/сегодня.md): над чем работаем, что решили",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"}}, "required": ["text"]}}},
]


def _session_file() -> Path:
    d = Path(config.MINI_SESSION_DIR).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{config.SESSION_NAME}.json"


def _load_history() -> list:
    f = _session_file()
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
    return []


def _save_history(messages: list) -> None:
    # системное сообщение не храним, историю подрезаем
    tail = [m for m in messages if m.get("role") != "system"][-config.MINI_HISTORY_LIMIT:]
    # история не должна начинаться с ответа инструмента (валидность для API)
    while tail and tail[0].get("role") == "tool":
        tail.pop(0)
    _session_file().write_text(
        json.dumps(tail, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def _run_tool(name: str, args: dict) -> str:
    if "__" in name:  # инструмент MCP-сервера
        return mcp_client.call(name, args)
    fn = _TOOLS.get(name)
    if fn is None:
        return f"Ошибка: нет инструмента {name}"
    try:
        return fn(**args)
    except mini_tools.ToolError as exc:
        return f"Ошибка: {exc}"
    except Exception as exc:
        return f"Ошибка ({type(exc).__name__}): {exc}"


_client = None


def _get_client():
    global _client
    if _client is None:
        _client = observability.make_openai_client()
    return _client


@observability.observe_or_noop()
def ask(message: str) -> str:
    with observability.trace_attrs("voice-task", message):
        return _ask_inner(message)


def _ask_inner(message: str) -> str:
    client = _get_client()
    messages = [{"role": "system", "content": _build_system_prompt()}]
    messages += _load_history()
    messages.append({"role": "user", "content": message})
    tools = _TOOL_SCHEMAS + mcp_client.get_tool_schemas()

    reply = ""
    for _step in range(config.MINI_MAX_STEPS):
        response = client.chat.completions.create(
            model=config.MINI_MODEL,
            messages=messages,
            tools=tools,
            reasoning_effort=config.MINI_REASONING,
        )
        msg = response.choices[0].message
        if not msg.tool_calls:
            reply = (msg.content or "").strip()
            messages.append({"role": "assistant", "content": reply})
            break
        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ],
        })
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = _run_tool(tc.function.name, args)
            print(f"  [инструмент] {tc.function.name}({tc.function.arguments[:80]}) → {result[:80]}")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
    else:
        reply = "Я запутался в шагах, попробуй переформулировать."
        messages.append({"role": "assistant", "content": reply})

    _save_history(messages)
    observability.flush()
    return reply or "Готово."
