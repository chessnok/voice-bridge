"""HTTP-бэкенд агента: голосовой клиент шлёт текст, сервер выполняет и отвечает.

Запуск на сервере:  python -m voice_bridge.server
Клиент локально:    VB_AGENT_URL=http://host:8765 + VB_AGENT_TOKEN в .env
"""
import sys

# Windows: консоль/редиректы по умолчанию cp1251 — кириллица и «→» в print роняют процесс
for stream in (sys.stdout, sys.stderr):
    if stream and hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config, mini_agent


class AgentHandler(BaseHTTPRequestHandler):
    def _reply(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        if not config.AGENT_TOKEN:
            return True  # токен не задан — доверяем только loopback-bind
        return self.headers.get("Authorization") == f"Bearer {config.AGENT_TOKEN}"

    def do_POST(self) -> None:
        if self.path != "/ask":
            self._reply(404, {"error": "только POST /ask"})
            return
        if not self._authorized():
            self._reply(401, {"error": "неверный токен"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length) or b"{}")
            text = str(data.get("text", "")).strip()
            if not text:
                self._reply(400, {"error": "пустой text"})
                return
            self._reply(200, {"reply": mini_agent.ask(text)})
        except Exception as exc:
            self._reply(500, {"error": str(exc)})

    def log_message(self, fmt: str, *args) -> None:
        print(f"[сервер] {self.address_string()} {fmt % args}")


def main() -> None:
    if config.SERVER_BIND not in ("127.0.0.1", "localhost") and not config.AGENT_TOKEN:
        raise SystemExit("Небезопасно: bind наружу без VB_AGENT_TOKEN. Задай токен в .env.")
    server = ThreadingHTTPServer((config.SERVER_BIND, config.SERVER_PORT), AgentHandler)
    print(f"[сервер] агент слушает {config.SERVER_BIND}:{config.SERVER_PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
