"""MCP-сервер почты (stdio). Несколько ящиков из email_accounts.json.

Формат ~/voice-bridge/email_accounts.json:
[
  {"name": "личная", "host": "smtp.gmail.com", "port": 465,
   "user": "me@gmail.com", "password": "app-password", "from": "me@gmail.com"}
]
Запуск вручную для проверки: python -m voice_bridge.mcp_email
"""
import json
import smtplib
from email.message import EmailMessage
from pathlib import Path

from mcp.server.fastmcp import FastMCP

ACCOUNTS_FILE = Path(__file__).resolve().parent.parent / "email_accounts.json"

mcp = FastMCP("email")


def _load_accounts() -> dict[str, dict]:
    if not ACCOUNTS_FILE.exists():
        return {}
    data = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
    return {a["name"]: a for a in data}


@mcp.tool()
def email_accounts() -> str:
    """Список подключённых почтовых ящиков (имена для параметра account)."""
    names = list(_load_accounts())
    if not names:
        return "Ни одного ящика не настроено (email_accounts.json пуст)"
    return "\n".join(names)


@mcp.tool()
def email_send(account: str, to: str, subject: str, body: str) -> str:
    """Отправить письмо с указанного ящика. account — имя из email_accounts."""
    accounts = _load_accounts()
    acc = accounts.get(account)
    if acc is None:
        available = ", ".join(accounts) or "нет ни одного"
        return f"Ошибка: ящика «{account}» нет. Доступны: {available}"
    msg = EmailMessage()
    msg["From"] = acc.get("from", acc["user"])
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP_SSL(acc["host"], int(acc.get("port", 465)), timeout=30) as smtp:
            smtp.login(acc["user"], acc["password"])
            smtp.send_message(msg)
    except Exception as exc:
        return f"Ошибка отправки: {exc}"
    return f"Письмо отправлено с «{account}» на {to}"


if __name__ == "__main__":
    mcp.run()
