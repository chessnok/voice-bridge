"""Настройки голосового моста. Все значения можно переопределить env-переменными VB_*."""
import os

# Хоткей push-to-talk: зажал — говоришь, отпустил — выполняется.
# Одиночная клавиша ("space", "f9") или комбинация ("ctrl+k", "alt+v").
HOTKEY = os.environ.get("VB_HOTKEY", "ctrl+k")

# Минимальная длительность удержания, чтобы запись считалась командой
MIN_UTTERANCE_SECONDS = float(os.environ.get("VB_MIN_UTTERANCE", "0.6"))

# Запись
SAMPLE_RATE = 16_000
CHANNELS = 1
MAX_RECORD_SECONDS = int(os.environ.get("VB_MAX_RECORD_SECONDS", "60"))
INPUT_DEVICE = os.environ.get("VB_INPUT_DEVICE")  # None = системный дефолт

# STT: "api" — OpenAI API (нужен OPENAI_API_KEY), "local" — faster-whisper на CPU
STT_BACKEND = os.environ.get("VB_STT", "api")
WHISPER_API_MODEL = os.environ.get("VB_WHISPER_API_MODEL", "gpt-4o-transcribe")
WHISPER_MODEL = os.environ.get("VB_WHISPER_MODEL", "small")
WHISPER_LANGUAGE = os.environ.get("VB_LANGUAGE", "ru")
# Сколько секунд звука до нажатия клавиши подхватывать из кольцевого буфера
PREROLL_SECONDS = float(os.environ.get("VB_PREROLL", "0.3"))

# Детерминированная расшифровка
STT_TEMPERATURE = float(os.environ.get("VB_STT_TEMPERATURE", "0"))

# Корректор: LLM исправляет ошибки распознавания по контексту диалога
REWRITE_ENABLED = os.environ.get("VB_REWRITE", "1") != "0"
REWRITE_MODEL = os.environ.get("VB_REWRITE_MODEL", "gpt-5-mini")
HISTORY_TURNS = int(os.environ.get("VB_HISTORY_TURNS", "3"))

# Куда сохранять последнюю запись для диагностики качества микрофона
LAST_RECORDING = os.path.join(os.path.dirname(os.path.dirname(__file__)), "recordings", "last.wav")


def _load_dotenv_key(name: str) -> str | None:
    """Ключ из env или из ~/voice-bridge/.env (формат NAME=value)."""
    if os.environ.get(name):
        return os.environ[name]
    dotenv = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if os.path.exists(dotenv):
        for line in open(dotenv):
            line = line.strip()
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


OPENAI_API_KEY = _load_dotenv_key("OPENAI_API_KEY")

# Langfuse-трейсинг (опционально): без ключей трейсинг выключен
LANGFUSE_PUBLIC_KEY = _load_dotenv_key("LANGFUSE_PUBLIC_KEY")
LANGFUSE_SECRET_KEY = _load_dotenv_key("LANGFUSE_SECRET_KEY")
LANGFUSE_BASE_URL = _load_dotenv_key("LANGFUSE_BASE_URL")

# Имя сессии (файл истории диалога)
SESSION_NAME = os.environ.get("VB_SESSION", "voice")

# Таймаут ответа агента (локального и удалённого), секунд
AGENT_TIMEOUT_SECONDS = int(os.environ.get("VB_AGENT_TIMEOUT", "180"))

# Удалённый бэкенд: если задан VB_AGENT_URL — мост работает клиентом,
# агент и инструменты выполняются на сервере (python -m voice_bridge.server)
AGENT_URL = os.environ.get("VB_AGENT_URL") or _load_dotenv_key("VB_AGENT_URL")
AGENT_TOKEN = _load_dotenv_key("VB_AGENT_TOKEN")
SERVER_BIND = os.environ.get("VB_SERVER_BIND", "127.0.0.1")
SERVER_PORT = int(os.environ.get("VB_SERVER_PORT", "8765"))

# Браузер: путь к бинарю agent-browser (форк: npm i -g github:chessnok/agent-browser)
AGENT_BROWSER_BIN = os.environ.get("VB_AGENT_BROWSER_BIN", "agent-browser")

# Режим живого разговора (Realtime API)
REALTIME_MODEL = os.environ.get("VB_REALTIME_MODEL", "gpt-realtime-2")
REALTIME_VOICE = os.environ.get("VB_REALTIME_VOICE", "marin")
# Порог токенов сессии, после которого старые ходы сжимаются в краткое содержание
REALTIME_SUMMARY_TOKENS = int(os.environ.get("VB_RT_SUMMARY_TOKENS", "12000"))
# Насколько быстро VAD решает, что ты договорил: low|auto|high (high = быстрее ответ)
REALTIME_VAD_EAGERNESS = os.environ.get("VB_VAD_EAGERNESS", "auto")

# Мини-агент
MINI_MODEL = os.environ.get("VB_MINI_MODEL", "gpt-5.1")
MINI_WORKDIR = os.environ.get("VB_MINI_WORKDIR", "~/Ассистент")
MINI_SESSION_DIR = os.environ.get("VB_MINI_SESSION_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "sessions"))
MINI_MAX_STEPS = int(os.environ.get("VB_MINI_MAX_STEPS", "15"))
MINI_REASONING = os.environ.get("VB_MINI_REASONING", "low")
MINI_HISTORY_LIMIT = int(os.environ.get("VB_MINI_HISTORY_LIMIT", "60"))

# TTS — edge-tts, русские голоса: ru-RU-DmitryNeural, ru-RU-SvetlanaNeural
TTS_VOICE = os.environ.get("VB_TTS_VOICE", "ru-RU-DmitryNeural")
TTS_ENABLED = os.environ.get("VB_TTS", "1") != "0"

# Звуковые сигналы старта/конца записи
BEEP_ENABLED = os.environ.get("VB_BEEP", "1") != "0"
