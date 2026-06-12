"""Каскадный живой разговор: VAD → STT → текстовый агент → озвучка.

Мозг разговора — обычный текстовый LLM (mini_agent со всеми инструментами и
памятью), поэтому понимание заметно лучше speech-to-speech. Латентность выше
(~3-5 с на ход). Пока ассистент говорит, микрофон на паузе — эха нет by design.
"""
import collections
import queue
import threading
from pathlib import Path

import numpy as np
import sounddevice as sd

from . import agent, config, mute, stt, tts

_FRAME = 480  # 30мс @ 16kHz
_PREROLL_FRAMES = 10          # 0.3с до начала речи
_START_FRAMES = 3             # речь: 3 громких кадра из 8
_MIN_SPEECH_SECONDS = 0.3
_MAX_UTTERANCE_SECONDS = 30

_CASCADE_RULES = """
РЕЖИМ ЖИВОГО РАЗГОВОРА: ты говоришь с пользователем голосом напрямую.
- Запись и правка строк стихов — только через подтверждение: повтори услышанное
  («Правильно понял: нужно добавить строку „...“, да?») и выполняй после согласия
  в следующей реплике. Чтение и вопросы — сразу.
- Расшифровка речи может содержать ошибки — бессмыслицу переспрашивай, не выполняй.
"""


class EnergyVad:
    """Детектор реплик по энергии с адаптивным порогом и прероллом."""

    def __init__(self, noise_floor: float) -> None:
        self._threshold = max(noise_floor * config.VAD_SENSITIVITY, 0.004)
        self._end_silence_frames = int(config.VAD_END_SILENCE_SECONDS * config.SAMPLE_RATE / _FRAME)
        self._preroll: collections.deque = collections.deque(maxlen=_PREROLL_FRAMES)
        self._recent: collections.deque = collections.deque(maxlen=8)
        self._recording = False
        self._frames: list = []
        self._silence_run = 0

    def feed(self, frame: np.ndarray):
        """Кадр 30мс → готовая реплика (np.ndarray) или None."""
        rms = float(np.sqrt(np.mean(frame ** 2)))
        loud = rms > self._threshold
        self._recent.append(loud)

        if not self._recording:
            self._preroll.append(frame)
            if sum(self._recent) >= _START_FRAMES:
                self._recording = True
                self._frames = list(self._preroll)
                self._silence_run = 0
            return None

        self._frames.append(frame)
        self._silence_run = 0 if loud else self._silence_run + 1
        too_long = len(self._frames) * _FRAME / config.SAMPLE_RATE > _MAX_UTTERANCE_SECONDS
        if self._silence_run >= self._end_silence_frames or too_long:
            utterance = np.concatenate(self._frames)
            self._reset()
            speech_seconds = len(utterance) / config.SAMPLE_RATE - config.VAD_END_SILENCE_SECONDS
            if speech_seconds >= _MIN_SPEECH_SECONDS:
                return utterance
        return None

    def _reset(self) -> None:
        self._recording = False
        self._frames = []
        self._preroll.clear()
        self._recent.clear()
        self._silence_run = 0


def _calibrate(frames_queue: "queue.Queue", seconds: float = 1.5) -> float:
    """Медианный уровень шума комнаты в начале сессии."""
    levels = []
    needed = int(seconds * config.SAMPLE_RATE / _FRAME)
    for _ in range(needed):
        frame = frames_queue.get()
        levels.append(float(np.sqrt(np.mean(frame ** 2))))
    return float(np.median(levels))


def _handle_utterance(audio: np.ndarray) -> None:
    tts.beep(880)  # «услышал, обрабатываю»
    text = stt.transcribe(audio)
    if not text:
        return
    print(f"[вы] {text}")
    result: dict = {}

    def work() -> None:
        try:
            result["reply"] = agent.ask_agent(text, extra_system=_CASCADE_RULES)
        except agent.AgentError as exc:
            result["reply"] = f"Ошибка: {exc}"

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(timeout=config.TASK_ANNOUNCE_SECONDS)
    announced = worker.is_alive()
    if announced:
        # задача затянулась — предупреждаем голосом и ждём дальше;
        # speak блокирует, так что фраза договаривается до конца в любом случае
        tts.speak(f"Ушёл делать: {text[:80]}. Скажу, как закончу.")
        worker.join()
    reply = result.get("reply", "Что-то пошло не так, ответа нет.")
    if announced:
        reply = f"Готово. {reply}"
    print(f"[голос] {reply}")
    tts.speak(reply)  # блокирует до конца озвучки — микрофон в это время на паузе


def run_cascade_mode() -> None:
    if not config.OPENAI_API_KEY:
        raise SystemExit("Нет OPENAI_API_KEY")
    frames: "queue.Queue" = queue.Queue(maxsize=200)
    busy = threading.Event()

    def cb(indata, frame_count, time_info, status) -> None:
        if busy.is_set() or mute.muted.is_set():
            return  # говорим сами или микрофон заглушен hotkey'ем
        try:
            frames.put_nowait(indata[:, 0].copy())
        except queue.Full:
            pass

    mute.start_hotkey_listener()

    stream = sd.InputStream(
        samplerate=config.SAMPLE_RATE, channels=1, dtype="float32",
        blocksize=_FRAME, device=config.INPUT_DEVICE, callback=cb,
    )
    sounds = Path(__file__).resolve().parent.parent / "sounds"
    with stream:
        print("[разговор] калибрую шум комнаты, помолчи секунду...")
        busy.set()  # голосовая заставка не должна попасть в замер шума
        tts.play_file(str(sounds / "calibrating.mp3"))
        with frames.mutex:
            frames.queue.clear()
        busy.clear()
        vad = EnergyVad(_calibrate(frames))
        print("[разговор] слушаю — просто говори (Ctrl+C — выход)")
        busy.set()  # и заставка «слушаю» не должна сама стриггерить VAD
        tts.play_file(str(sounds / "ready.mp3"))
        with frames.mutex:
            frames.queue.clear()
        busy.clear()
        while True:
            frame = frames.get()
            utterance = vad.feed(frame)
            if utterance is None:
                continue
            busy.set()
            try:
                _handle_utterance(utterance)
            finally:
                with frames.mutex:  # сбрасываем накопившееся за время ответа
                    frames.queue.clear()
                busy.clear()
