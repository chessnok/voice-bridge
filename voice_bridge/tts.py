"""Озвучка ответов: edge-tts (бесплатный, русские нейроголоса) + ffplay."""
import asyncio
import os
import re
import subprocess
import tempfile

from . import config

_MARKUP_RE = re.compile(r"[*_`#>|~\[\]()]+")
_EMOJI_RE = re.compile(
    "[\U0001f000-\U0001fbff☀-➿⬀-⯿️‍]+"
)


def sanitize_for_speech(text: str) -> str:
    """Убирает markdown и эмодзи — иначе синтезатор читает мусор."""
    text = _EMOJI_RE.sub(" ", text)
    text = _MARKUP_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def synthesize_to_file(text: str, out_path: str) -> None:
    """Текст → mp3-файл."""
    import edge_tts

    async def run() -> None:
        communicate = edge_tts.Communicate(text, config.TTS_VOICE)
        await communicate.save(out_path)

    asyncio.run(run())


def play_file(path: str) -> None:
    subprocess.run(
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path],
        check=False,
    )


def _speak_streaming(text: str) -> None:
    """Стрим: чанки синтеза сразу в ffplay — звук начинается до конца синтеза."""
    import edge_tts

    player = subprocess.Popen(
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-i", "pipe:0"],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    async def run() -> None:
        communicate = edge_tts.Communicate(text, config.TTS_VOICE)
        async for chunk in communicate.stream():
            if chunk["type"] == "audio" and player.stdin:
                player.stdin.write(chunk["data"])
    try:
        asyncio.run(run())
    finally:
        if player.stdin:
            player.stdin.close()
        player.wait()


def speak(text: str) -> None:
    """Озвучивает текст; стримом, с фолбэком на файл."""
    text = sanitize_for_speech(text)
    if not config.TTS_ENABLED or not text:
        return
    try:
        _speak_streaming(text)
        return
    except Exception as exc:
        print(f"[озвучка] стрим не удался ({exc}), играю файлом")
    fd, path = tempfile.mkstemp(suffix=".mp3", prefix="voice-bridge-")
    os.close(fd)
    try:
        synthesize_to_file(text, path)
        play_file(path)
    finally:
        if os.path.exists(path):
            os.unlink(path)
