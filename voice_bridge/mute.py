"""Глушение микрофона по глобальной горячей клавише (режимы talk и talk-cascade).

Ctrl+M (настраивается VB_MUTE_HOTKEY) — перестать слышать; ещё раз — снова слушать.
Состояние muted — threading.Event: аудио-колбэки режимов проверяют его и роняют кадры.
Переключение озвучивается предзаписанными mp3 из sounds/.

GlobalHotKeys здесь не годится: на Windows Ctrl+буква приходит control-символом
(Ctrl+M = "\r"), а на русской раскладке физическая M отдаёт «ь» — оба случая мимо
сравнения с латинской буквой. Ловим вручную: canonical() + виртуальный код + раскладка.
"""
import threading
from pathlib import Path

from . import config

_SOUNDS = Path(__file__).resolve().parent.parent / "sounds"
# та же физическая клавиша в русской раскладке: qwerty → йцукен
_QWERTY_TO_RU = dict(zip("qwertyuiop[]asdfghjkl;'zxcvbnm,.", "йцукенгшщзхъфывапролджэячсмитьбю"))

muted = threading.Event()
_toggling = threading.Lock()


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


def _toggle_async() -> None:
    """Из колбэка клавиатуры — отдельным потоком: low-level hook Windows нельзя
    блокировать проигрыванием mp3, иначе система снимает хук. Лок = дебаунс."""

    def run() -> None:
        if not _toggling.acquire(blocking=False):
            return  # уже переключаемся — повторное нажатие игнорируем
        try:
            toggle()
        finally:
            _toggling.release()

    threading.Thread(target=run, daemon=True).start()


def start_hotkey_listener() -> None:
    """Глобальный hotkey фоном; его падение не валит голосовой режим."""

    def run() -> None:
        try:
            from pynput import keyboard

            parts = [p.strip().lower() for p in config.MUTE_HOTKEY.split("+") if p.strip()]
            letter = parts[-1]
            need_ctrl = "ctrl" in parts[:-1]
            main_key = keyboard.KeyCode.from_char(letter)
            # запасные представления той же клавиши: control-символ (Ctrl+M="\r"),
            # русская раскладка, виртуальный код (не зависит от раскладки)
            fallback_chars = {letter, chr(ord(letter) - 96), _QWERTY_TO_RU.get(letter, letter)}
            fallback_vk = ord(letter.upper())
            ctrl_keys = {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r}
            ctrl_down = {"on": False}
            listener = None

            def is_main(key) -> bool:
                if listener is not None and listener.canonical(key) == main_key:
                    return True
                char = (getattr(key, "char", None) or "").lower()
                return char in fallback_chars or getattr(key, "vk", None) == fallback_vk

            def on_press(key) -> None:
                if key in ctrl_keys:
                    ctrl_down["on"] = True
                elif is_main(key) and (ctrl_down["on"] or not need_ctrl):
                    _toggle_async()

            def on_release(key) -> None:
                if key in ctrl_keys:
                    ctrl_down["on"] = False

            listener = keyboard.Listener(on_press=on_press, on_release=on_release)
            with listener:
                listener.join()
        except Exception as exc:
            print(f"[микрофон] hotkey глушения не заработал: {exc}")

    threading.Thread(target=run, daemon=True, name="mute-hotkey").start()
    print(f"[микрофон] {config.MUTE_HOTKEY.upper()} — выключить/включить слух")
