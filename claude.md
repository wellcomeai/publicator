# Публикатор ИИ

## Обзор
Telegram SaaS-бот для создания и публикации контента в каналы с помощью ИИ.
Пользователь создаёт ИИ-агента с кастомным промтом → привязывает канал → генерирует/рерайтит посты → публикует с медиа.

## Стек
- **Runtime**: Python 3.11+
- **Bot framework**: aiogram 3.x (webhook mode)
- **Web framework**: FastAPI
- **Database**: PostgreSQL + asyncpg (connection pool)
- **AI**: OpenAI GPT-4o-mini (text), GPT Image API (images), Sora (video), Whisper (voice)
- **Payments**: Robokassa
- **Deploy**: Render (Web Service + PostgreSQL)

## Архитектура

### Точка входа
`app.py` — FastAPI приложение с lifespan. Webhook endpoint принимает Telegram updates. Медиагруппы (альбомы) буферизуются на уровне webhook и обрабатываются через 2 секунды.

### Слой бота (`bot/`)
- `handlers/` — aiogram Router-хэндлеры, каждый в своём файле
- `keyboards/keyboards.py` — все клавиатуры (ReplyKeyboard + InlineKeyboard)
- `states/states.py` — FSM StatesGroup (AgentSetup, ChannelLink, ContentGeneration, RewritePost, Onboarding, SchedulePost, MediaManagement)
- `middlewares/` — AlbumMiddleware для передачи собранных медиагрупп в хэндлеры

### Слой данных (`database/`)
- `db.py` — asyncpg pool, `_create_tables()` создаёт схему при старте
- `managers/` — статические классы-менеджеры (UserManager, AgentManager, ChannelManager, PostManager, PaymentManager, ScheduleManager, UserSettingsManager)
- Все менеджеры используют `get_pool()` и возвращают `Dict[str, Any]`

### Сервисный слой (`services/`)
- `openai_service.py` — генерация, рерайт, редактирование текста
- `image_service.py` — генерация AI-картинок (GPT Image API → base64 → temp file → Telegram → file_id)
- `video_service.py` — генерация AI-видео (Sora → polling → download → Telegram → file_id)
- `channel_service.py` — проверка прав бота в канале, публикация с медиа
- `media_manager.py` — PostMediaManager: CRUD альбома поста в posts.media_info (JSONB)
- `whisper_service.py` — транскрипция голосовых через Whisper API
- `url_extractor.py` — извлечение текста из URL (httpx + BeautifulSoup)
- `scheduler_service.py` — фоновый цикл: каждые 60 сек проверяет scheduled_posts и публикует

### Утилиты (`utils/`)
- `media.py` — extract_media_info, extract_links, get_text
- `html_sanitizer.py` — sanitize_html: оставляет только Telegram-совместимые HTML-теги
- `album_buffer.py` — глобальный буфер для сбора медиагрупп
- `plan_utils.py` — проверка фич по плану

## Критические ограничения

### Telegram Bot API limits
- **Caption медиа**: максимум **1024 символа** (включая HTML-теги)
- **Текстовое сообщение**: максимум 4096 символов
- **Медиагруппа (альбом)**: максимум 10 элементов
- **Caption в альбоме**: только у первого элемента

### Текущая стратегия лимитов
GPT генерирует посты до **900 символов** (запас ~124 на HTML-теги). Системный промт и пресеты агентов содержат жёсткие инструкции по лимиту. Если caption > 1024 — fallback: медиа без подписи + текст отдельным сообщением.

## Freemium модель
- **free**: 5 постов/мес, текст + фото, водяной знак, 100K токенов при регистрации
- **starter** (100₽/мес): 15 постов/мес, без водяного знака
- **pro** (300₽/мес): безлимит, видео, расписание, аналитика

## Схема БД
Таблицы: users, channels, agents, posts, scheduled_posts, payments, token_usage, user_settings.
Все создаются в `database/db.py → _create_tables()`.

## Паттерны кода

### Хэндлеры
- Каждый handler file создаёт `router = Router()`
- Роутеры регистрируются в `app.py` через `dp.include_router()`
- Порядок регистрации важен: onboarding_handler до agent_handler, media_handler до content_handler
- FSM states используются для многошаговых сценариев

### Менеджеры БД
```python
pool = await get_pool()
async with pool.acquire() as conn:
    row = await conn.fetchrow("SELECT ...", params)
    return dict(row) if row else None
```

### Медиа
Медиа хранится как JSONB в posts.media_info. Формат альбома:
```json
{
    "type": "album",
    "items": [
        {"type": "photo", "file_id": "...", "source": "ai_generated"},
        {"type": "video", "file_id": "...", "source": "user_upload"}
    ]
}
```

## Команды

### Запуск локально
```bash
pip install -r requirements.txt
cp .env.example .env
# Заполнить .env
uvicorn app:app --host 0.0.0.0 --port 8000
```

### Деплой на Render
Build: `pip install -r requirements.txt`
Start: `uvicorn app:app --host 0.0.0.0 --port $PORT`

## Диалог контент-плана (Plan Chat)

### Архитектура
Перед генерацией постов автопубликации — интерактивный диалог пользователя с ИИ для согласования контент-плана. Используется OpenAI Function Calling.

### Ключевые файлы
- `database/managers/plan_chat_manager.py` — CRUD для таблицы `plan_chat_sessions`
- `services/plan_chat_service.py` — оркестрация диалога (OpenAI <-> DB <-> Handler)
- `bot/handlers/content_plan_handler.py` — FSM хэндлеры диалога

### Таблица БД
- `plan_chat_sessions` — хранит историю диалога (JSONB messages), статус, подтверждённый план

### FSM State
- `ContentPlan.discussing_plan` — активен пока идёт диалог с ИИ

### Флоу
1. Кнопка "Сгенерировать план" (`cplan:generate`) -> `PlanChatService.start_session()` -> FSM state
2. Каждое сообщение -> `PlanChatService.send_message()` -> OpenAI с tools
3. Перехват `tool_calls` -> если `confirm_content_plan` -> парсим topics -> вопрос про обложки -> генерация
4. Кнопка "Отменить" -> `PlanChatManager.cancel_session()` -> FSM clear

### OpenAI Function
- Tool: `confirm_content_plan` (topic, format, description для каждой темы)
- Системный промт содержит жёсткую инструкцию: вызывать ТОЛЬКО после явного подтверждения
- Перехват: проверяем `response.choices[0].message.tool_calls` на нашей стороне

### Голосовые
- Поддержка голосовых сообщений в диалоге через Whisper (как в остальном боте)

### Токены
- Списываются за каждый запрос к OpenAI в рамках диалога через `UserManager.spend_tokens()`

## Тестирование
Тестов пока нет. При добавлении использовать pytest + pytest-asyncio.
