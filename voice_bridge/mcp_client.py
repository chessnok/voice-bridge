"""Клиент MCP-серверов: держит stdio-сессии живыми в фоновом event loop.

Серверы описываются в ~/voice-bridge/mcp_servers.json:
{
  "email": {"command": "/path/to/python", "args": ["-m", "voice_bridge.mcp_email"]}
}
Имя инструмента наружу: "<сервер>__<инструмент>" (email__email_send).
"""
import asyncio
import json
import threading
from contextlib import AsyncExitStack
from pathlib import Path

SERVERS_FILE = Path(__file__).resolve().parent.parent / "mcp_servers.json"

_loop: asyncio.AbstractEventLoop | None = None
_sessions: dict = {}
_tool_schemas: list[dict] = []
_started = threading.Event()
_lock = threading.Lock()


def _load_server_configs() -> dict:
    if not SERVERS_FILE.exists():
        return {}
    return json.loads(SERVERS_FILE.read_text(encoding="utf-8"))


async def _connect_all(stack: AsyncExitStack) -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    for name, cfg in _load_server_configs().items():
        try:
            params = StdioServerParameters(
                command=cfg["command"], args=cfg.get("args", []), env=cfg.get("env")
            )
            read, write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            tools = await session.list_tools()
            _sessions[name] = session
            for tool in tools.tools:
                _tool_schemas.append({
                    "type": "function",
                    "function": {
                        "name": f"{name}__{tool.name}",
                        "description": tool.description or tool.name,
                        "parameters": tool.inputSchema,
                    },
                })
        except Exception as exc:
            print(f"[mcp] сервер «{name}» не поднялся: {exc}")


def _loop_thread() -> None:
    global _loop
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)

    async def run_forever() -> None:
        async with AsyncExitStack() as stack:
            await _connect_all(stack)
            _started.set()
            await asyncio.Event().wait()  # держим сессии до конца процесса

    try:
        _loop.run_until_complete(run_forever())
    except Exception as exc:
        print(f"[mcp] фоновый цикл упал: {exc}")
        _started.set()


def ensure_started() -> None:
    with _lock:
        if _started.is_set():
            return
        threading.Thread(target=_loop_thread, daemon=True, name="mcp-loop").start()
    _started.wait(timeout=30)


def get_tool_schemas() -> list[dict]:
    """OpenAI-схемы всех инструментов всех подключённых MCP-серверов."""
    ensure_started()
    return list(_tool_schemas)


def call(full_name: str, args: dict) -> str:
    """Вызов инструмента "<сервер>__<имя>" — синхронно для агента."""
    ensure_started()
    server, _, tool = full_name.partition("__")
    session = _sessions.get(server)
    if session is None or _loop is None:
        return f"Ошибка: MCP-сервер «{server}» не подключён"

    async def do_call():
        result = await session.call_tool(tool, args)
        parts = [c.text for c in result.content if getattr(c, "text", None)]
        return "\n".join(parts) or "(пусто)"

    future = asyncio.run_coroutine_threadsafe(do_call(), _loop)
    try:
        return future.result(timeout=120)
    except Exception as exc:
        return f"Ошибка MCP-вызова {full_name}: {exc}"
