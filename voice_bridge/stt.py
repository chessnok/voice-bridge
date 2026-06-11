"""Распознавание речи: OpenAI Whisper API (по умолчанию) или локальный faster-whisper."""
import io
import wave

import numpy as np

from . import config

_local_model = None


class SttError(Exception):
    pass


def _normalize(audio: np.ndarray) -> np.ndarray:
    """Пиковая нормализация: тихий микрофон → нормальный уровень."""
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak < 1e-4:  # тишина — нечего усиливать
        return audio
    return audio * (0.9 / peak)


def _audio_to_wav_bytes(audio: np.ndarray) -> bytes:
    """float32 PCM → wav-байты (int16)."""
    pcm16 = (np.clip(_normalize(audio), -1.0, 1.0) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(config.SAMPLE_RATE)
        wav.writeframes(pcm16.tobytes())
    return buf.getvalue()


def _transcribe_api(wav_bytes: bytes) -> str:
    if not config.OPENAI_API_KEY:
        raise SttError(
            "Нет OPENAI_API_KEY: добавь строку OPENAI_API_KEY=sk-... в ~/voice-bridge/.env "
            "или экспортируй переменную, либо запусти с VB_STT=local"
        )
    from openai import OpenAI

    client = OpenAI(api_key=config.OPENAI_API_KEY)
    result = client.audio.transcriptions.create(
        model=config.WHISPER_API_MODEL,
        file=("speech.wav", wav_bytes, "audio/wav"),
        language=config.WHISPER_LANGUAGE,
        temperature=config.STT_TEMPERATURE,
    )
    return result.text.strip()


def _get_local_model():
    global _local_model
    if _local_model is None:
        from faster_whisper import WhisperModel

        _local_model = WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8")
    return _local_model


def _transcribe_local(audio: np.ndarray) -> str:
    segments, _info = _get_local_model().transcribe(
        audio, language=config.WHISPER_LANGUAGE, vad_filter=True, beam_size=1
    )
    return " ".join(s.text.strip() for s in segments).strip()


def transcribe(audio: np.ndarray) -> str:
    """PCM float32 16kHz mono → текст. Слишком короткий звук → пустая строка."""
    min_samples = int(config.SAMPLE_RATE * config.MIN_UTTERANCE_SECONDS)
    if audio.size < min_samples:  # короткий тап по клавише, не команда
        return ""
    if config.STT_BACKEND == "api":
        return _transcribe_api(_audio_to_wav_bytes(audio))
    return _transcribe_local(audio)


def transcribe_wav(path: str) -> str:
    """Тестовый вход: аудиофайл вместо микрофона."""
    if config.STT_BACKEND == "api":
        if not config.OPENAI_API_KEY:
            raise SttError("Нет OPENAI_API_KEY (см. ~/voice-bridge/.env)")
        from openai import OpenAI

        client = OpenAI(api_key=config.OPENAI_API_KEY)
        result = client.audio.transcriptions.create(
            model=config.WHISPER_API_MODEL,
            file=open(path, "rb"),
            language=config.WHISPER_LANGUAGE,
            temperature=config.STT_TEMPERATURE,
        )
        return result.text.strip()
    segments, _info = _get_local_model().transcribe(
        path, language=config.WHISPER_LANGUAGE, vad_filter=True, beam_size=1
    )
    return " ".join(s.text.strip() for s in segments).strip()
