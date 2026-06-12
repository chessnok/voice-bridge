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
            ["pandoc", str(p), "-t", "plain"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30
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
            ["pandoc", tmp_path, "-o", str(p)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60
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


def fs_delete(path: str) -> str:
    """«Удаление» = перемещение в Корзину внутри рабочей папки — можно вернуть."""
    src = _safe_path(path)
    if not src.exists():
        raise ToolError(f"Файла нет: {path}")
    if src.is_dir():
        raise ToolError("Папки не удаляю, только файлы")
    trash = _workdir() / "Корзина"
    trash.mkdir(exist_ok=True)
    dst = trash / src.name
    counter = 1
    while dst.exists():
        dst = trash / f"{src.stem}_{counter}{src.suffix}"
        counter += 1
    src.rename(dst)
    return f"Файл {src.name} перемещён в Корзину"


def _desktop_dir() -> Path:
    """Рабочий стол пользователя: обычный, OneDrive (Windows) или локализованный (Linux)."""
    home = Path.home()
    for candidate in (home / "Desktop", home / "OneDrive" / "Desktop", home / "Рабочий стол"):
        if candidate.is_dir():
            return candidate
    raise ToolError("Не нашёл папку рабочего стола")


def _safe_desktop_path(rel: str) -> Path:
    """Путь строго внутри рабочего стола — только чтение, ../ отшибается."""
    base = _desktop_dir().resolve()
    p = (base / rel.lstrip("/\\")).resolve()
    if not p.is_relative_to(base):
        raise ToolError(f"Путь вне рабочего стола: {rel}")
    return p


def _read_pdf(p: Path, limit: int = 8000) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(p))
    pages = []
    total = 0
    for i, page in enumerate(reader.pages, 1):
        text = (page.extract_text() or "").strip()
        pages.append(text)
        total += len(text)
        if total > limit:
            pages.append(f"…(обрезано, всего страниц: {len(reader.pages)}, прочитано: {i})")
            break
    return "\n\n".join(pages) or "(в PDF нет текстового слоя)"


def desktop_list(subdir: str = "") -> str:
    """Список файлов на рабочем столе (только чтение)."""
    base = _safe_desktop_path(subdir) if subdir else _desktop_dir()
    if not base.is_dir():
        raise ToolError(f"Папки нет: {subdir}")
    items = sorted(
        p.name + ("/" if p.is_dir() else "")
        for p in base.iterdir() if not p.name.startswith((".", "~$"))
    )
    return "\n".join(items) or "(пусто)"


def desktop_read(path: str) -> str:
    """Прочитать файл с рабочего стола: txt/md — как есть, docx — pandoc, pdf — pypdf."""
    p = _safe_desktop_path(path)
    if not p.exists():
        raise ToolError(f"Файла нет: {path}")
    if p.is_dir():
        raise ToolError(f"Это папка, файлы внутри покажет desktop_list: {path}")
    if p.suffix.lower() == ".pdf":
        return _read_pdf(p)
    if p.suffix.lower() == ".docx":
        out = subprocess.run(
            ["pandoc", str(p), "-t", "plain"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30
        )
        if out.returncode != 0:
            raise ToolError(f"Не смог прочитать docx: {out.stderr[:200]}")
        return out.stdout
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return p.read_text(encoding="cp1251", errors="replace")


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


# Реальные подкоманды agent-browser CLI; "eval" намеренно исключён —
# произвольный JS равен полному доступу, что ломает белый список
_BROWSER_ALLOWED = {
    "open", "snapshot", "click", "dblclick", "type", "fill", "press",
    "keyboard", "hover", "focus", "check", "uncheck", "select", "drag",
    "upload", "download", "scroll", "scrollintoview", "wait", "screenshot",
    "get", "is", "find", "back", "forward", "reload", "close",
}


def browser(command: str) -> str:
    """Шаг браузера через agent-browser CLI (open/snapshot/click/type/...)."""
    parts = command.strip().split()
    if not parts or parts[0] not in _BROWSER_ALLOWED:
        raise ToolError(f"Разрешены только: {', '.join(sorted(_BROWSER_ALLOWED))}")
    out = subprocess.run(
        [config.AGENT_BROWSER_BIN, *parts], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60
    )
    result = (out.stdout + out.stderr).strip()
    return result[:4000] or "(пусто)"
