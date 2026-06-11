"""Инструменты мини-агента. Файловая система — только внутри выделенной папки (jail)."""
import subprocess
from pathlib import Path

from . import config


class ToolError(Exception):
    pass


def _workdir() -> Path:
    wd = Path(config.MINI_WORKDIR).expanduser()
    wd.mkdir(parents=True, exist_ok=True)
    return wd


def _safe_path(rel: str) -> Path:
    """Путь строго внутри рабочей папки — ../ и абсолютные пути отшибаются."""
    wd = _workdir().resolve()
    p = (wd / rel.lstrip("/")).resolve()
    if not p.is_relative_to(wd):
        raise ToolError(f"Путь вне рабочей папки: {rel}")
    return p


def fs_list(subdir: str = "") -> str:
    base = _safe_path(subdir) if subdir else _workdir()
    if not base.exists():
        return "(папка пуста)"
    items = sorted(
        p.name + ("/" if p.is_dir() else "")
        for p in base.iterdir() if not p.name.startswith(".")
    )
    return "\n".join(items) or "(папка пуста)"


def fs_read(path: str) -> str:
    p = _safe_path(path)
    if not p.exists():
        raise ToolError(f"Файла нет: {path}")
    if p.suffix == ".docx":
        out = subprocess.run(
            ["pandoc", str(p), "-t", "plain"], capture_output=True, text=True, timeout=30
        )
        if out.returncode != 0:
            raise ToolError(f"Не смог прочитать docx: {out.stderr[:200]}")
        return out.stdout
    return p.read_text(encoding="utf-8")


def _write_docx(p, content: str) -> None:
    """Текст → docx через pandoc (бинарный формат, напрямую писать нельзя)."""
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    try:
        out = subprocess.run(
            ["pandoc", tmp_path, "-o", str(p)], capture_output=True, text=True, timeout=60
        )
        if out.returncode != 0 or not p.exists():
            raise ToolError(f"pandoc не справился: {out.stderr[:200]}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def fs_write(path: str, content: str) -> str:
    """Формат по расширению: .docx собирается pandoc'ом, остальное — текстом."""
    p = _safe_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.suffix == ".docx":
        _write_docx(p, content)
    else:
        p.write_text(content, encoding="utf-8")
    return f"Записано: {path} ({len(content)} символов)"


def fs_append(path: str, content: str) -> str:
    p = _safe_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = fs_read(path) if p.exists() else ""
    joined = existing + ("\n" if existing and not existing.endswith("\n") else "") + content
    if p.suffix == ".docx":
        _write_docx(p, joined)
    else:
        p.write_text(joined, encoding="utf-8")
    return f"Дописано в {path}"


def memory_note(text: str) -> str:
    """Дописать заметку в дневник memory/ГГГГ-ММ-ДД.md."""
    from datetime import datetime

    now = datetime.now()
    daily = _safe_path(f"memory/{now:%Y-%m-%d}.md")
    daily.parent.mkdir(parents=True, exist_ok=True)
    line = f"- {now:%H:%M} {text.strip()}\n"
    existing = daily.read_text(encoding="utf-8") if daily.exists() else f"# {now:%Y-%m-%d}\n\n"
    daily.write_text(existing + line, encoding="utf-8")
    return "Записал в дневник"


_BROWSER_ALLOWED = {
    "open", "snapshot", "click", "type", "press", "get", "screenshot",
    "close", "list-tabs", "wait", "scroll", "fill", "back",
}


def browser(command: str) -> str:
    """Шаг браузера через agent-browser CLI (open/snapshot/click/type/...)."""
    parts = command.strip().split()
    if not parts or parts[0] not in _BROWSER_ALLOWED:
        raise ToolError(f"Разрешены только: {', '.join(sorted(_BROWSER_ALLOWED))}")
    out = subprocess.run(
        [config.AGENT_BROWSER_BIN, *parts], capture_output=True, text=True, timeout=60
    )
    result = (out.stdout + out.stderr).strip()
    return result[:4000] or "(пусто)"
