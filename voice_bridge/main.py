"""Голосовой мост: зажми хоткей → говори → отпусти → агент сделает и ответит голосом.

Режимы:
  python -m voice_bridge.main              # боевой: глобальный хоткей (X11)
  python -m voice_bridge.main --text "..."  # тест: текст вместо микрофона
  python -m voice_bridge.main --wav f.wav   # тест: аудиофайл вместо микрофона
"""
import sys

# Windows: консоль/редиректы по умолчанию cp1251 — кириллица и «→» в print роняют процесс
for stream in (sys.stdout, sys.stderr):
    if stream and hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


import argparse
import collections
import os
import subprocess
import sys
import threading

from . import agent, config, refine, stt, tts

# история (команда, ответ) для корректора расшифровки
_history: collections.deque = collections.deque(maxlen=config.HISTORY_TURNS)


def _save_debug_recording(audio) -> None:
    """Последняя запись — в recordings/last.wav, чтобы можно было послушать, что слышит модель."""
    try:
        os.makedirs(os.path.dirname(config.LAST_RECORDING), exist_ok=True)
        with open(config.LAST_RECORDING, "wb") as f:
            f.write(stt._audio_to_wav_bytes(audio))
        import numpy as np

        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        print(f"[звук] {audio.size / config.SAMPLE_RATE:.1f}с, пик {peak:.2f} → recordings/last.wav")
    except Exception as exc:
        print(f"[звук] не сохранил отладочную запись: {exc}")


def _beep(freq: int) -> None:
    if not config.BEEP_ENABLED:
        return
    subprocess.Popen(
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet",
         "-f", "lavfi", "-i", f"sine=frequency={freq}:duration=0.12"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def handle_text(text: str) -> str:
    """Текст команды → корректор → агент → озвучка. Возвращает ответ для лога."""
    import time

    if not text:
        print("[мост] пустая расшифровка, пропускаю")
        return ""
    print(f"[вы] {text}")
    t0 = time.monotonic()
    refined = refine.refine(text, list(_history))
    t_refine = time.monotonic() - t0
    if refined != text:
        print(f"[корректор] {refined}")
    t0 = time.monotonic()
    try:
        reply = agent.ask_agent(refined)
    except agent.AgentError as exc:
        reply = f"Ошибка агента: {exc}"
    t_agent = time.monotonic() - t0
    print(f"[агент] {reply}")
    print(f"[время] корректор {t_refine:.1f}с · агент {t_agent:.1f}с")
    _history.append((refined, reply))
    tts.speak(reply)
    return reply


_MODIFIER_KEYS = {
    "ctrl": ("ctrl", "ctrl_l", "ctrl_r"),
    "alt": ("alt", "alt_l", "alt_r", "alt_gr"),
    "shift": ("shift", "shift_l", "shift_r"),
}


def _parse_hotkey(spec: str, keyboard):
    """'ctrl+k' → (нужные модификаторы, основная клавиша)."""
    parts = [p.strip().lower() for p in spec.split("+") if p.strip()]
    mods = frozenset(p for p in parts[:-1] if p in _MODIFIER_KEYS)
    main = parts[-1]
    if len(main) == 1:
        return mods, keyboard.KeyCode.from_char(main)
    named = getattr(keyboard.Key, main, None)
    if named is None:
        sys.exit(f"Неизвестный хоткей: {spec}")
    return mods, named


def run_hotkey_loop() -> None:
    import time

    from pynput import keyboard

    from .recorder import Recorder

    recorder = Recorder()
    busy = threading.Event()
    pressed_at = [0.0]
    need_mods, main_key = _parse_hotkey(config.HOTKEY, keyboard)
    mods_down: set = set()
    listener = None

    def mod_name(key) -> str | None:
        for name, aliases in _MODIFIER_KEYS.items():
            if any(key == getattr(keyboard.Key, a, None) for a in aliases):
                return name
        return None

    def is_main(key) -> bool:
        # canonical() снимает эффект модификаторов (с Ctrl буква приходит control-символом)
        return listener.canonical(key) == main_key or key == main_key

    def process(audio) -> None:
        try:
            _save_debug_recording(audio)
            handle_text(stt.transcribe(audio))
        finally:
            busy.clear()

    def beep_if_still_held() -> None:
        if pressed_at[0] and not busy.is_set():
            _beep(880)

    def finish_recording() -> None:
        held = time.monotonic() - pressed_at[0]
        pressed_at[0] = 0.0
        audio = recorder.stop()
        if held < config.MIN_UTTERANCE_SECONDS:
            return  # случайный тап — игнор
        _beep(440)
        busy.set()
        threading.Thread(target=process, args=(audio,), daemon=True).start()

    def on_press(key) -> None:
        mod = mod_name(key)
        if mod:
            mods_down.add(mod)
            return
        if is_main(key) and need_mods <= mods_down and not busy.is_set() and not pressed_at[0]:
            pressed_at[0] = time.monotonic()
            recorder.start()
            threading.Timer(config.MIN_UTTERANCE_SECONDS, beep_if_still_held).start()

    def on_release(key) -> None:
        mod = mod_name(key)
        if mod:
            mods_down.discard(mod)
            # отпустил модификатор раньше буквы — тоже конец записи
            if mod in need_mods and pressed_at[0] and not busy.is_set():
                finish_recording()
            return
        if is_main(key) and pressed_at[0] and not busy.is_set():
            finish_recording()

    import sounddevice as sd

    mic_name = sd.query_devices(kind="input")["name"]
    print(f"[мост] микрофон: {mic_name}")
    print(f"[мост] готов: зажми {config.HOTKEY.upper()}, говори, отпусти. Ctrl+C — выход.")
    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    with listener:
        listener.join()


def main() -> None:
    from . import vblog

    vblog.setup_tee("client.log")  # консоль + logs/client.log (виден и после автостарта)
    parser = argparse.ArgumentParser(description="Голосовой ассистент")
    parser.add_argument("--talk", action="store_true",
                        help="живой разговор: Realtime API (быстро, перебивания)")
    parser.add_argument("--talk-cascade", action="store_true",
                        help="живой разговор: каскад STT→LLM→TTS (медленнее, понимает лучше)")
    parser.add_argument("--text", help="тест: команда текстом, без микрофона")
    parser.add_argument("--wav", help="тест: аудиофайл вместо микрофона")
    args = parser.parse_args()

    if args.talk:
        from . import talk

        talk.run_talk_mode()
    elif args.talk_cascade:
        from . import talk_cascade

        talk_cascade.run_cascade_mode()
    elif args.text:
        handle_text(args.text)
    elif args.wav:
        handle_text(stt.transcribe_wav(args.wav))
    else:
        run_hotkey_loop()


if __name__ == "__main__":
    main()
