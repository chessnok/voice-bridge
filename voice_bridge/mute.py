"""Глушение микрофона по глобальной горячей клавише (режимы talk и talk-cascade).

Ctrl+M (настраивается VB_MUTE_HOTKEY) — перестать слышать; ещё раз — снова слушать.
Состояние muted — threading.Event: аудио-колбэки режимов проверяют его и роняют кадры.
Переключение озвучивается предзаписанными mp3 из sounds/.
"""
import threading
from pathlib import Path

from . import config

_SOUNDS = Path(__file__).resolve().parent.parent / "sounds"

muted = threading.Event()


def toggle() -> None:
    from . import tts

    try:
        if muted.is_set():
            # сказать ДО включения — фраза не попадёт в распознавание
            tts.play_file(str(_SOUNDS / "mic_on.mp3"))
            muted.clear()
            print("[микрофон] снова слушаю")
        else:
            muted.set()
            tts.play_file(str(_SOUNDS / "mic_off.mp3"))
            print("[микрофон] выключен (та же клавиша — включить)")
    except Exception as exc:
        print(f"[микрофон] переключил, но звук не сыграл: {exc}")


def start_hotkey_listener() -> None:
    """Глобальный hotkey фоном; его падение не валит голосовой режим."""

    def run() -> None:
        try:
            from pynput import keyboard

            spec = config.MUTE_HOTKEY  # "ctrl+m" → "<ctrl>+m"
            combo = "+".join(f"<{p}>" if len(p) > 1 else p for p in spec.split("+"))
            with keyboard.GlobalHotKeys({combo: toggle}) as hotkeys:
                hotkeys.join()
        except Exception as exc:
            print(f"[микрофон] hotkey глушения не заработал: {exc}")

    threading.Thread(target=run, daemon=True, name="mute-hotkey").start()
    print(f"[микрофон] {config.MUTE_HOTKEY.upper()} — выключить/включить слух")
