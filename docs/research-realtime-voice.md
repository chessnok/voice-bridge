# Ресерч: как строят realtime voice системы (2026-06-11)

Сводка пяти параллельных исследований: архитектура/латентность, стеки и референсы,
учебные материалы, надёжность диалога, доступность + русский язык.

## 1. Архитектура и латентность

- **Speech-to-speech vs каскад**: каскад (STT→LLM→TTS) выигрывает в контроле и отладке (текст в середине = логи, модерация, замена компонентов), S2S — в просодии и скорости. Большинство продакшенов всё ещё каскадные. Стримящий каскад достигает <1 с, так что латентность сама по себе не аргумент за S2S.
  - https://deepgram.com/learn/speech-to-speech-vs-cascade-voice-agent-architecture
  - https://hamming.ai/blog/are-speech-to-speech-models-ready-to-replace-cascade-models
- **Гибрид — наш случай**: S2S-фронт (Realtime API) + текстовый агент-исполнитель для инструментов. Канонический референс — **openai/openai-realtime-agents** (паттерн Chat-Supervisor), ~6.9k★: https://github.com/openai/openai-realtime-agents
- **Бюджет латентности**: цель ~800 мс voice-to-voice, >1500 мс ощущается сломанным. Раскладка Pipecat (~993 мс): endpointing ~300, LLM TTFB ~350, TTS TTFB ~120, транспорт ~200. Главный скрытый пожиратель — endpointing (наивные таймауты тишины 1–1.5 с съедают полбюджета).
  - https://voiceaiandvoiceagents.com/ (канонический гайд)
  - https://sayna.ai/blog/sub-second-voice-agent-latency-practical-architecture-guide
- **Turn-taking**: VAD ≠ детекция конца реплики; semantic VAD/EOU-модели учитывают смысл. OpenAI: server_vad (threshold, silence_duration_ms) vs semantic_vad (eagerness). Альтернативы: LiveKit EOU (есть русский!), Pipecat Smart Turn, Deepgram Flux.
  - https://livekit.com/blog/turn-detection-voice-agents-vad-endpointing-model-based-detection
  - https://developers.openai.com/api/docs/guides/realtime-vad
- **Барж-ин правильно**: не только flush аудиобуфера — надо ещё `conversation.item.truncate`, чтобы контекст модели обрезался до реально услышанного пользователем.
- **Долгие инструменты**: не блокировать разговор — placeholder сразу + результат позже; filler-фразы («сейчас проверю»); 5–10 инструментов максимум.
  - https://www.daily.co/blog/advice-on-building-voice-ai-in-june-2025/
  - https://livekit.com/blog/react-pattern-voice-agents

## 2. Стеки и референс-реализации

| Проект | Что взять | Ссылка |
|---|---|---|
| Pipecat (~12.8k★, Python) | Frame-пайплайн, interruption-семантика, Smart Turn, Mem0-память | github.com/pipecat-ai/pipecat |
| LiveKit Agents (~10.9k★) | AgentSession API, worker-модель масштабирования, EOU-модель с русским | github.com/livekit/agents |
| openai-realtime-agents (~6.9k★) | **Chat-Supervisor** — наш паттерн, эталон | github.com/openai/openai-realtime-agents |
| TEN Framework (~10.7k★) | Граф расширений, full-duplex аватары | github.com/TEN-framework/ten-framework |
| HF speech-to-speech (~4.9k★) | Полностью локальный S2S-пайплайн | github.com/huggingface/speech-to-speech |
| kyutai unmute (~1.3k★) | Обернуть любой LLM стриминговыми STT/TTS | github.com/kyutai-labs/unmute |
| KoljaB/RealtimeSTT (~9.9k★) | Низколатентный локальный STT/VAD | github.com/KoljaB/RealtimeSTT |

Vocode — устарел (стоит с 2024), только как референс стриминговых абстракций.

## 3. Лекции, курсы, гайды

- **Гайд №1**: Voice AI & Voice Agents: An Illustrated Primer (Kwindla Kramer) — https://voiceaiandvoiceagents.com/
- AI Engineer World's Fair, Voice Track (плейлист докладов): https://www.youtube.com/playlist?list=PLcfpQ4tk2k0VdE7NSMKkNqc2qUH_lhm8K
- OpenAI DevDay «Multimodal apps with the Realtime API»: https://www.youtube.com/watch?v=mM8KhTxwPgs
- Курс DeepLearning.AI + LiveKit «Building AI Voice Agents for Production»: https://www.deeplearning.ai/courses/building-ai-voice-agents-for-production
- Maven-курс Kramer & swyx «Voice AI: Technical Deep Dive»: https://maven.com/pipecat/voice-ai-and-voice-agents-a-technical-deep-dive
- Pipecat Voice AI Meetups (ежемесячно): https://www.pipecat.ai/events
- a16z «AI Voice Agents: 2025 Update»: https://a16z.com/ai-voice-agents-2025-update/
- Подкаст Latent Space (регулярные voice-эпизоды): https://www.latent.space/podcast
- Академическая база: Stanford CS224S Spoken Language Processing: https://web.stanford.edu/class/cs224s/

## 4. Надёжность диалога

- **Подтверждения по ставкам**: необратимое/дорогое — явное подтверждение («отправляю письмо Ивану, верно?»); обратимое — неявное эхо. Третья неудача подряд — выход/эскалация, не повтор.
- **Кривой ASR чинится промптами**: убрать омофонные ответы из вопросов, инструктировать LLM «странный ответ → переспроси», дизамбигуация в описаниях tool-схем. https://shekhargulati.com/2026/01/06/stt-disambiguation-in-voice-agents-it-is-now-not-no/
- **Биасинг**: Deepgram keyterm — до 100 терминов, обновляемых посреди стрима. https://developers.deepgram.com/docs/keyterm
- **Контекст Realtime**: 32k, но деградирует раньше; каждый ответ пересылает всю историю → растущая цена. Рычаги: `token_limits`, `truncation` c retention ratio, **summarization-паттерн из OpenAI Cookbook** (старые ходы → одно summary-сообщение): https://developers.openai.com/cookbook/examples/context_summarization_with_realtime_api
- **Долгосрочная память**: извлечение фактов асинхронно после хода (нулевая латентность), вектор/граф на пользователя, инжект при старте сессии. Zep×LiveKit P95 <250 мс: https://blog.getzep.com/zep-livekit/
- Таксономия отказов ASR в проде: https://hamming.ai/blog/7-voice-agent-asr-failure-modes-in-production

## 5. Доступность (незрячие) + русский

- Незрячие — power users: хотят БЫСТРУЮ плотную речь и контроль (скорость/подробность как настройки). https://arxiv.org/pdf/2203.05848
- Earcons работают для состояний (слушаю/думаю/готово/ошибка), но осмысленные звуки лучше абстрактных тонов; статусные фразы — короткие.
- Ошибки: признать явно + конкретный следующий шаг; discoverability — короткие контекстные подсказки команд.
- RNIB хвалит Echo именно за отсутствие экранов/меню — голос как главный интерфейс работает: https://www.rnib.org.uk/living-with-sight-loss/assistive-aids-and-technology/technology-in-the-home/amazon-echo/
- Русский TTS: Silero — открытый стандарт (~0.5 RTF на CPU), Yandex SpeechKit — эмоциональные голоса; оценка: https://alphacephei.com/nsh/2024/07/12/russian-tts.html
- Русский ASR: сравнение распознавалок: https://github.com/Mike-Kuznetsov/SpeechRecognitionComparisonRussian
- Яндекс Алиса — программа инклюзии и отзывы незрячих: https://alice.yandex.ru/inclusion, https://specialviewportal.ru/articles/articles925

## Что применить у нас (приоритезировано)

1. **Барж-ин дочинить**: добавить `conversation.item.truncate` после flush — иначе модель считает, что её дослушали.
2. **Summarization контекста** по Cookbook-паттерну — сессия у писателя будет длинной, цена растёт каждый ход.
3. **Подтверждение перед необратимым** (отправка письма) — уже частично в промпте, формализовать.
4. **Настройки голоса для пользователя**: скорость речи/подробность как голосовые команды («говори быстрее»).
5. **Изучить Chat-Supervisor** в openai-realtime-agents — сверить наш do_task с эталоном.
6. **Звуковые статусы**: earcon «задача пошла» во время do_task (сейчас тишина).
7. Посмотреть Maven-курс Kramer/swyx и Voice Track плейлист — самая высокая плотность практики.
