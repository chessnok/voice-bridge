"""Langfuse-трейсинг (опционально): есть ключи в .env — трейсим, нет — чистый no-op.

Ключи: LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_BASE_URL (cloud.langfuse.com / us.cloud...).
"""
import os

from . import config

LANGFUSE_ENABLED = bool(config.LANGFUSE_PUBLIC_KEY and config.LANGFUSE_SECRET_KEY)

if LANGFUSE_ENABLED:
    # SDK читает креды из env — выставляем ДО первого импорта langfuse
    os.environ.setdefault("LANGFUSE_PUBLIC_KEY", config.LANGFUSE_PUBLIC_KEY)
    os.environ.setdefault("LANGFUSE_SECRET_KEY", config.LANGFUSE_SECRET_KEY)
    if config.LANGFUSE_BASE_URL:
        os.environ.setdefault("LANGFUSE_BASE_URL", config.LANGFUSE_BASE_URL)


def make_openai_client():
    """OpenAI-клиент: обёрнутый Langfuse (авто-трейс всех вызовов) или обычный."""
    if LANGFUSE_ENABLED:
        from langfuse.openai import OpenAI
    else:
        from openai import OpenAI
    return OpenAI(
        api_key=config.OPENAI_API_KEY,
        timeout=config.OPENAI_TIMEOUT,
        max_retries=config.OPENAI_RETRIES,
    )


def observe_or_noop(**kwargs):
    """Декоратор @observe при включённом Langfuse, иначе прозрачный."""
    if LANGFUSE_ENABLED:
        from langfuse import observe

        return observe(**kwargs)

    def passthrough(fn):
        return fn

    return passthrough


def trace_attrs(name: str, user_input: str):
    """Контекст: имя трейса, session_id, читабельный input (SDK v4: propagate_attributes)."""
    from contextlib import nullcontext

    if not LANGFUSE_ENABLED:
        return nullcontext()
    try:
        from langfuse import propagate_attributes

        # input не трогаем — @observe сам захватывает аргументы читабельно
        return propagate_attributes(
            trace_name=name, session_id=config.SESSION_NAME,
        )
    except Exception:
        return nullcontext()


def flush() -> None:
    if not LANGFUSE_ENABLED:
        return
    try:
        from langfuse import get_client

        get_client().flush()
    except Exception:
        pass


def log_voice_turn(
    user_text: str,
    assistant_text: str,
    interrupted: bool,
    tools_used: list,
    first_audio_ms: int | None,
) -> None:
    """Online-наблюдение talk-режима: трейс на каждый голосовой ход + scores.

    interrupted — неявный негативный сигнал (перебили = ответ слишком длинный/не тот);
    first_audio_ms — латентность от конца речи пользователя до первого звука ответа.
    """
    if not LANGFUSE_ENABLED:
        return
    try:
        from langfuse import get_client, observe, propagate_attributes

        lf = get_client()

        @observe(name="voice-turn")
        def record() -> str:
            from langfuse import get_client as _gc

            client = _gc()
            client.update_current_span(
                input=user_text,
                output=assistant_text,
                metadata={
                    "interrupted": interrupted,
                    "tools_used": tools_used,
                    "first_audio_ms": first_audio_ms,
                    "mode": "talk",
                },
            )
            client.score_current_trace(
                name="user-interrupted", value=1.0 if interrupted else 0.0
            )
            if first_audio_ms is not None:
                client.score_current_trace(
                    name="first-audio-ms", value=float(first_audio_ms)
                )
            return assistant_text

        with propagate_attributes(session_id=f"{config.SESSION_NAME}-talk"):
            record()
        lf.flush()
    except Exception as exc:
        print(f"[langfuse] ход не записан: {exc}")
