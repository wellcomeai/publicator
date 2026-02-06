# Публикатор ИИ 🤖

Telegram SaaS-бот для создания и публикации контента в каналы с помощью ИИ.

## Возможности

- 🤖 Создание персонального ИИ-агента с настраиваемым промтом
- 📢 Привязка Telegram-канала
- ✍️ Генерация постов по запросу
- 🔄 Рерайт существующих постов (с сохранением медиа)
- ✏️ Итеративное редактирование с контекстом
- 📷 Поддержка фото, видео, GIF, медиаальбомов
- 💳 Подписка и пакеты токенов (Robokassa)
- 🎁 3-дневный пробный период

## Стек

- Python 3.11+, aiogram 3.x, FastAPI
- PostgreSQL + asyncpg
- OpenAI GPT-4o-mini
- Robokassa (платежи)
- Render (деплой)

## Установка

```bash
pip install -r requirements.txt
cp .env.example .env
# Заполнить .env
```

## Запуск

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

## Деплой на Render

1. Создать Web Service → подключить репозиторий
2. Build Command: `pip install -r requirements.txt`
3. Start Command: `uvicorn app:app --host 0.0.0.0 --port $PORT`
4. Добавить Environment Variables из `.env.example`
5. Добавить PostgreSQL (Render Database)

## Robokassa URLs

- Result URL: `https://your-app.onrender.com/robokassa/result`
- Success URL: `https://your-app.onrender.com/robokassa/success`
- Fail URL: `https://your-app.onrender.com/robokassa/fail`
