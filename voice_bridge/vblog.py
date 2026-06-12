"""Логи: метка времени на каждой строке + дневной архив старых файлов.

setup_file("server.log") — весь вывод процесса в logs/server.log (для фоновых процессов);
setup_tee("client.log")  — вывод и в консоль, и в logs/client.log (для интерактивных).

При старте: если текущий лог писался в прошлый день — уезжает в
logs/archive/<имя>-ГГГГ-ММ-ДД.log; архив старше KEEP_DAYS дней удаляется.
Ротация только на старте процесса: ассистент перезапускается при входе в систему,
поэтому файл длиннее суток — редкость, а дата есть в каждой строке.
"""
import sys
import time
from datetime import date, datetime
from pathlib import Path

KEEP_DAYS = 30
LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
_STAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


class _Stamper:
    """Обёртка потока: «ГГГГ-ММ-ДД ЧЧ:ММ:СС » в начале каждой непустой строки.

    fileno() отдаёт настоящий файл — дочерние процессы (MCP-серверы) наследуют
    его и пишут в тот же лог напрямую, без меток, но и без потери вывода.
    """

    def __init__(self, raw, mirror=None):
        self._raw = raw
        self._mirror = mirror
        self._at_line_start = True

    def write(self, text: str) -> int:
        if not text:
            return 0
        parts: list[str] = []
        for chunk in text.splitlines(keepends=True):
            if self._at_line_start and chunk.strip():
                parts.append(datetime.now().strftime(_STAMP_FORMAT) + " ")
            parts.append(chunk)
            self._at_line_start = chunk.endswith("\n")
        self._raw.write("".join(parts))
        if self._mirror is not None:
            try:
                self._mirror.write(text)
            except Exception:
                pass  # консоль могла исчезнуть (скрытое окно автостарта)
        return len(text)

    def flush(self) -> None:
        self._raw.flush()
        if self._mirror is not None:
            try:
                self._mirror.flush()
            except Exception:
                pass

    def fileno(self) -> int:
        return self._raw.fileno()

    def isatty(self) -> bool:
        return False

    @property
    def encoding(self) -> str:
        return getattr(self._raw, "encoding", "utf-8")


def _resolve(path: str | Path) -> Path:
    p = Path(path)
    if p.is_absolute():
        return p
    # голое имя файла — в стандартный каталог логов;
    # путь с каталогом (VB_SERVER_LOG=logs/server.log) — от текущей директории
    return LOGS_DIR / p if len(p.parts) == 1 else Path.cwd() / p


def _archive_old(current: Path) -> None:
    """Лог прошлого дня — в archive/<имя>-ГГГГ-ММ-ДД.log; чистка старше KEEP_DAYS."""
    archive = current.parent / "archive"
    try:
        if current.exists() and current.stat().st_size:
            last_day = date.fromtimestamp(current.stat().st_mtime)
            if last_day < date.today():
                archive.mkdir(parents=True, exist_ok=True)
                target = archive / f"{current.stem}-{last_day.isoformat()}{current.suffix}"
                counter = 1
                while target.exists():
                    target = archive / f"{current.stem}-{last_day.isoformat()}-{counter}{current.suffix}"
                    counter += 1
                current.rename(target)
        cutoff = time.time() - KEEP_DAYS * 86400
        if archive.is_dir():
            for old in archive.glob("*.log"):
                if old.stat().st_mtime < cutoff:
                    old.unlink(missing_ok=True)
    except OSError as exc:
        print(f"[лог] ротация {current.name} не удалась: {exc}", file=sys.stderr)


def _open_log(path: str | Path):
    target = _resolve(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    _archive_old(target)
    return open(target, "a", encoding="utf-8", buffering=1)


def setup_file(path: str | Path) -> None:
    """Весь stdout/stderr процесса — в файл с метками времени (фоновый режим)."""
    log_file = _open_log(path)
    stamper = _Stamper(log_file)
    sys.stdout = stamper
    sys.stderr = stamper


def setup_tee(path: str | Path) -> None:
    """Вывод в консоль как раньше + копия с метками времени в файл."""
    log_file = _open_log(path)
    sys.stdout = _Stamper(log_file, mirror=sys.stdout)
    sys.stderr = _Stamper(log_file, mirror=sys.stderr)
