"""Запись с микрофона: постоянно открытый поток + кольцевой буфер.

Поток не закрывается между командами, поэтому старт записи мгновенный,
а кольцевой буфер отдаёт PREROLL_SECONDS звука ДО нажатия клавиши —
начало фразы не обрезается.
"""
import collections
import threading

import numpy as np
import sounddevice as sd

from . import config


class Recorder:
    def __init__(self) -> None:
        preroll_chunks = max(1, int(config.PREROLL_SECONDS * config.SAMPLE_RATE / 1024))
        self._preroll: collections.deque = collections.deque(maxlen=preroll_chunks)
        self._chunks: list[np.ndarray] = []
        self._recording = False
        self._lock = threading.Lock()
        self._stream = sd.InputStream(
            samplerate=config.SAMPLE_RATE,
            channels=config.CHANNELS,
            dtype="float32",
            device=config.INPUT_DEVICE,
            blocksize=1024,
            callback=self._on_audio,
        )
        self._stream.start()

    def _on_audio(self, indata, frames, time_info, status) -> None:
        chunk = indata.copy()
        with self._lock:
            if self._recording:
                max_chunks = config.MAX_RECORD_SECONDS * config.SAMPLE_RATE // 1024
                if len(self._chunks) < max_chunks:
                    self._chunks.append(chunk)
            else:
                self._preroll.append(chunk)

    def start(self) -> None:
        with self._lock:
            if self._recording:
                return
            # начинаем с хвоста кольцевого буфера — звук до нажатия клавиши
            self._chunks = list(self._preroll)
            self._preroll.clear()
            self._recording = True

    def stop(self) -> np.ndarray:
        """Останавливает запись, возвращает mono float32 PCM 16kHz."""
        with self._lock:
            self._recording = False
            chunks, self._chunks = self._chunks, []
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks)[:, 0]

    def close(self) -> None:
        self._stream.stop()
        self._stream.close()
