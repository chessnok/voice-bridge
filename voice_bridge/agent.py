"""Роутинг к агенту: локальный мини-агент или удалённый бэкенд по HTTP."""
import json
import urllib.error
import urllib.request

from . import config


class AgentError(Exception):
    pass


def _ask_remote(message: str) -> str:
    url = config.AGENT_URL.rstrip("/") + "/ask"
    payload = json.dumps({"text": message}).encode("utf-8")
    request = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Content-Type": "application/json"},
    )
    if config.AGENT_TOKEN:
        request.add_header("Authorization", f"Bearer {config.AGENT_TOKEN}")
    try:
        with urllib.request.urlopen(request, timeout=config.AGENT_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read())
    except urllib.error.URLError as exc:
        raise AgentError(f"Сервер агента недоступен: {exc}") from exc
    if "reply" not in data:
        raise AgentError(f"Сервер вернул ошибку: {data.get('error', 'неизвестно')}")
    return data["reply"]


def ask_agent(message: str) -> str:
    if config.AGENT_URL:
        return _ask_remote(message)
    from . import mini_agent

    try:
        return mini_agent.ask(message)
    except AgentError:
        raise
    except Exception as exc:
        raise AgentError(f"мини-агент: {exc}") from exc
