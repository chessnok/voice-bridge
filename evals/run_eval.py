"""Offline-оценка агента по Langfuse-методике: датасет → эксперимент → оценки.

Запуск:  cd ~/voice-bridge && .venv/bin/python evals/run_eval.py [имя-прогона]

Две оценки на каждую команду:
  executed     — детерминированная проверка файловой системы (сделал ли реально);
  answer-quality — LLM-судья ТОЛЬКО по тексту ответа (краткость, озвучиваемость,
                   соответствие заявленного действия команде) — без требований
                   «доказать запись», которых из текста не видно.

Айтемы независимы: чтение/экспорт работают с фикстурой, сидируемой до прогона.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("VB_SESSION", f"eval-{int(time.time())}")  # чистая сессия на прогон

from voice_bridge import config, mini_agent, observability  # noqa: E402

DATASET = "voice-commands"
WORKDIR = Path(config.MINI_WORKDIR).expanduser()

_FIXTURE_POEM = "Рассвет встаёт над тихою рекой.\nТуман плывёт молочной пеленой.\n"

# check: (вид, аргументы) — детерминированная проверка результата в файловой системе
ITEMS = [
    {"input": "Создай пустой файл проба.txt",
     "expected": "Короткое подтверждение создания файла проба.txt, без уточняющих вопросов",
     "check": ("exists", "проба.txt")},
    {"input": "Запиши стих про ветер: Ветер гонит листья по мостовой. Город засыпает под луной.",
     "expected": "Короткое подтверждение, что стих сохранён в папке Стихи",
     "check": ("contains", "Стихи", "Ветер гонит листья")},
    {"input": "Прочитай стих про рассвет",
     "expected": "В ответе сам текст стиха про рассвет (рассвет над рекой, туман)",
     "check": ("answer_contains", "туман")},
    {"input": "Сколько файлов в папке Стихи?",
     "expected": "Названо конкретное число",
     "check": ("answer_regex", r"\d+|один|два|три|четыре|пять|шесть|семь|восемь|девять|десять")},
    {"input": "Экспортируй стих про рассвет в docx",
     "expected": "Короткое подтверждение создания docx",
     "check": ("exists_glob", "Стихи/*ассвет*.docx")},
    {"input": "Сделай заметку в дневник: проверка оффлайн оценки",
     "expected": "Короткое подтверждение записи заметки",
     "check": ("contains", "memory", "проверка оффлайн оценки")},
]

_JUDGE_PROMPT = """Ты оцениваешь ТЕКСТ ответа голосового ассистента слабовидящего писателя.
Факт выполнения проверяется отдельно автоматикой — НЕ требуй доказательств записи.

Команда: {input}
Ожидание по тексту ответа: {expected}
Ответ ассистента: {output}

Критерии (только текст!):
- Ответ короткий (1-2 предложения), пригоден для озвучки: без markdown, эмодзи, списков.
- Заявленное действие соответствует команде, нет лишних уточняющих вопросов.
Верни строго JSON: {{"score": 0.0-1.0, "comment": "коротко почему"}}"""


def seed_fixtures() -> None:
    """Фикстура для чтения/экспорта + зачистка артефактов прошлых прогонов."""
    poems = WORKDIR / "Стихи"
    poems.mkdir(parents=True, exist_ok=True)
    (poems / "Рассвет.md").write_text(_FIXTURE_POEM, encoding="utf-8")
    for junk in ["проба.txt", "Стихи/Ветер.md"]:
        path = WORKDIR / junk
        if path.exists():
            path.unlink()
    for docx in poems.glob("*ассвет*.docx"):
        docx.unlink()


def run_check(check: tuple, answer: str) -> float:
    kind, *args = check
    try:
        if kind == "exists":
            return 1.0 if (WORKDIR / args[0]).exists() else 0.0
        if kind == "exists_glob":
            return 1.0 if list(WORKDIR.glob(args[0])) else 0.0
        if kind == "contains":
            folder = WORKDIR / args[0]
            needle = args[1].lower()
            return 1.0 if any(
                needle in p.read_text(encoding="utf-8", errors="ignore").lower()
                for p in folder.rglob("*") if p.is_file() and p.suffix in (".md", ".txt")
            ) else 0.0
        if kind == "answer_contains":
            return 1.0 if args[0].lower() in answer.lower() else 0.0
        if kind == "answer_regex":
            import re

            return 1.0 if re.search(args[0], answer.lower()) else 0.0
    except OSError:
        pass
    return 0.0


def judge(user_input: str, expected: str, output: str) -> dict:
    client = observability.make_openai_client()
    resp = client.chat.completions.create(
        model=config.REWRITE_MODEL,
        reasoning_effort="minimal",
        messages=[{"role": "user", "content": _JUDGE_PROMPT.format(
            input=user_input, expected=expected, output=output)}],
    )
    text = (resp.choices[0].message.content or "{}").strip()
    text = text[text.find("{"):text.rfind("}") + 1]
    try:
        verdict = json.loads(text)
        return {"score": float(verdict.get("score", 0)), "comment": str(verdict.get("comment", ""))[:400]}
    except (json.JSONDecodeError, ValueError):
        return {"score": 0.0, "comment": f"судья вернул не-JSON: {text[:100]}"}


def sync_dataset(lf) -> None:
    """Датасет = ровно текущие ITEMS: новые добавить, устаревшие удалить."""
    try:
        lf.create_dataset(name=DATASET)
    except Exception:
        pass
    wanted = {json.dumps(i["input"], ensure_ascii=False, sort_keys=True) for i in ITEMS}
    current = lf.get_dataset(DATASET).items
    for item in current:
        if json.dumps(item.input, ensure_ascii=False, sort_keys=True) not in wanted:
            lf.api.dataset_items.delete(item.id)
    have = {json.dumps(i.input, ensure_ascii=False, sort_keys=True) for i in current}
    for item in ITEMS:
        if json.dumps(item["input"], ensure_ascii=False, sort_keys=True) not in have:
            lf.create_dataset_item(
                dataset_name=DATASET, input=item["input"], expected_output=item["expected"],
            )


def run() -> None:
    if not observability.LANGFUSE_ENABLED:
        raise SystemExit("Нет ключей Langfuse в .env — offline-оценке некуда писать")
    run_name = sys.argv[1] if len(sys.argv) > 1 else f"run-{time.strftime('%Y%m%d-%H%M')}"

    from langfuse import Evaluation, get_client

    lf = get_client()
    seed_fixtures()
    sync_dataset(lf)
    dataset = lf.get_dataset(DATASET)
    checks = {i["input"]: i["check"] for i in ITEMS}

    def task(*, item, **kwargs):
        return mini_agent.ask(item.input)

    def executed(*, input, output, expected_output, **kwargs):
        score = run_check(checks[str(input)], str(output))
        return Evaluation(name="executed", value=score,
                          comment="файловая проверка" if score else "результата в ФС нет")

    def answer_quality(*, input, output, expected_output, **kwargs):
        verdict = judge(str(input), str(expected_output), str(output))
        print(f"  [{verdict['score']:.1f}] {str(input)[:48]} → {str(output)[:55]}")
        return Evaluation(name="answer-quality", value=verdict["score"], comment=verdict["comment"])

    result = dataset.run_experiment(
        name="voice-agent-eval",
        run_name=run_name,
        task=task,
        evaluators=[executed, answer_quality],
        max_concurrency=1,
    )
    lf.flush()
    print(f"[итог] прогон {run_name}: {len(result.item_results)} команд — "
          f"Datasets → {DATASET} → Runs в Langfuse")


if __name__ == "__main__":
    run()
