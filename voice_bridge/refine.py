"""Корректор расшифровки: LLM чинит ошибки распознавания по контексту диалога.

«Напиши ему привет» после создания документа → «Напиши в созданный документ: привет».
При любой ошибке тихо возвращает исходный текст — мост не должен падать из-за корректора.
"""
from . import config, observability

_SYSTEM_PROMPT = """\
Ты корректор голосовых команд слабовидящего писателя для компьютерного ассистента.
На входе — расшифровка речи с ошибками распознавания. Твоя задача:
1. Исправить ошибки распознавания (неверные предлоги, падежи, похоже звучащие слова).
2. Восстановить отсылки по контексту диалога: «ему», «туда», «его» — к какому файлу/документу это относится.
3. Сохранить смысл и все детали. НИЧЕГО не добавлять от себя, не выполнять команду, не отвечать на неё.
Верни ТОЛЬКО исправленный текст команды, без кавычек и пояснений."""


def refine(text: str, history: list[tuple[str, str]]) -> str:
    if not config.REWRITE_ENABLED or not text or not config.OPENAI_API_KEY:
        return text
    try:
        global _client
        if "_client" not in globals() or _client is None:
            _client = observability.make_openai_client()
        client = _client
        messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
        for user_text, agent_reply in history:
            messages.append({"role": "user", "content": f"Команда: {user_text}"})
            messages.append({"role": "assistant", "content": f"(ассистент сделал: {agent_reply})"})
        messages.append({"role": "user", "content": f"Команда: {text}"})
        extra = {"reasoning_effort": "minimal"} if config.REWRITE_MODEL.startswith("gpt-5") else {}
        response = client.chat.completions.create(
            model=config.REWRITE_MODEL,
            messages=messages,
            **extra,
        )
        refined = (response.choices[0].message.content or "").strip()
        # модель иногда повторяет служебный префикс из примеров диалога
        if refined.lower().startswith("команда:"):
            refined = refined.split(":", 1)[1].strip()
        return refined if refined else text
    except Exception as exc:  # корректор — необязательный этап, падать нельзя
        print(f"[корректор] пропущен: {exc}")
        return text
