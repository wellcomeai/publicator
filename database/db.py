"""Database connection pool"""

import asyncpg
import structlog
from config.settings import config

logger = structlog.get_logger()

pool: asyncpg.Pool = None


async def init_db():
    """Initialize database connection pool and create tables"""
    global pool
    pool = await asyncpg.create_pool(config.DATABASE_URL, min_size=2, max_size=10)
    logger.info("✅ Database pool created")
    await _create_tables()


async def get_pool() -> asyncpg.Pool:
    global pool
    if pool is None:
        await init_db()
    return pool


async def close_db():
    global pool
    if pool:
        await pool.close()
        pool = None
        logger.info("Database pool closed")


async def _create_tables():
    """Create all tables"""
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute("""
        
        -- Пользователи
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            chat_id BIGINT UNIQUE NOT NULL,
            username VARCHAR(255),
            first_name VARCHAR(255),
            
            -- Подписка
            is_subscribed BOOLEAN DEFAULT FALSE,
            trial_started_at TIMESTAMPTZ,
            trial_expires_at TIMESTAMPTZ,
            subscription_expires_at TIMESTAMPTZ,
            
            -- Freemium: тарифный план
            plan VARCHAR(20) DEFAULT 'free',
            posts_this_month INT DEFAULT 0,
            month_reset_at TIMESTAMPTZ,
            
            -- Токены
            tokens_balance INT DEFAULT 0,
            tokens_used_total INT DEFAULT 0,
            
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
        
        -- Каналы (один на пользователя)
        CREATE TABLE IF NOT EXISTS channels (
            id SERIAL PRIMARY KEY,
            user_id INT REFERENCES users(id) ON DELETE CASCADE,
            channel_id BIGINT NOT NULL,
            channel_title VARCHAR(255),
            channel_username VARCHAR(255),
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(user_id)
        );
        
        -- ИИ-агенты (один на пользователя)
        CREATE TABLE IF NOT EXISTS agents (
            id SERIAL PRIMARY KEY,
            user_id INT REFERENCES users(id) ON DELETE CASCADE,
            agent_name VARCHAR(255) NOT NULL,
            instructions TEXT NOT NULL,
            model VARCHAR(50) DEFAULT 'gpt-4o-mini',
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(user_id)
        );
        
        -- Посты (история генераций)
        CREATE TABLE IF NOT EXISTS posts (
            id SERIAL PRIMARY KEY,
            user_id INT REFERENCES users(id) ON DELETE CASCADE,
            channel_id BIGINT,
            
            -- Контент
            original_text TEXT,
            generated_text TEXT,
            final_text TEXT,
            
            -- Медиа (JSON массив file_id)
            media_info JSONB,
            
            -- Статус: draft / editing / scheduled / published
            status VARCHAR(20) DEFAULT 'draft',
            published_at TIMESTAMPTZ,
            
            -- Токены
            input_tokens INT DEFAULT 0,
            output_tokens INT DEFAULT 0,
            
            -- Контекст диалога (для редактирования)
            conversation_history JSONB DEFAULT '[]'::jsonb,
            
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
        
        -- Расписание публикаций
        CREATE TABLE IF NOT EXISTS scheduled_posts (
            id SERIAL PRIMARY KEY,
            post_id INT REFERENCES posts(id) ON DELETE CASCADE,
            user_id INT REFERENCES users(id) ON DELETE CASCADE,
            channel_id BIGINT NOT NULL,
            
            publish_at TIMESTAMPTZ NOT NULL,
            
            -- pending / published / failed / cancelled
            status VARCHAR(20) DEFAULT 'pending',
            error_message TEXT,
            
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
        
        -- Платежи
        CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY,
            user_id INT REFERENCES users(id) ON DELETE CASCADE,
            amount_rub INT NOT NULL,
            
            -- subscription / tokens
            payment_type VARCHAR(30) NOT NULL,
            tokens_amount INT DEFAULT 0,
            
            -- Тарифный план (starter / pro)
            plan VARCHAR(20),
            
            -- pending / success / fail
            status VARCHAR(20) DEFAULT 'pending',
            
            robokassa_inv_id INT,
            robokassa_data JSONB,
            
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
        
        -- Использование токенов (детальный лог)
        CREATE TABLE IF NOT EXISTS token_usage (
            id SERIAL PRIMARY KEY,
            user_id INT REFERENCES users(id) ON DELETE CASCADE,
            post_id INT REFERENCES posts(id) ON DELETE SET NULL,
            input_tokens INT DEFAULT 0,
            output_tokens INT DEFAULT 0,
            model VARCHAR(50),
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        
        -- Настройки авто-публикации
        CREATE TABLE IF NOT EXISTS auto_publish_settings (
            id SERIAL PRIMARY KEY,
            user_id INT REFERENCES users(id) ON DELETE CASCADE UNIQUE,
            is_active BOOLEAN DEFAULT FALSE,
            schedule JSONB DEFAULT '{}'::jsonb,
            moderation VARCHAR(20) DEFAULT 'review',
            generate_covers BOOLEAN DEFAULT TRUE,
            on_empty VARCHAR(20) DEFAULT 'pause',
            timezone VARCHAR(50) DEFAULT 'Europe/Moscow',
            is_generating BOOLEAN DEFAULT FALSE,
            last_processed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );

        -- Очередь контент-плана
        CREATE TABLE IF NOT EXISTS content_queue (
            id SERIAL PRIMARY KEY,
            user_id INT REFERENCES users(id) ON DELETE CASCADE,
            topic TEXT,
            format VARCHAR(50),
            post_id INT REFERENCES posts(id) ON DELETE SET NULL,
            position INT DEFAULT 0,
            scheduled_at TIMESTAMPTZ,
            status VARCHAR(20) DEFAULT 'pending',
            review_reminders_sent INT DEFAULT 0,
            last_reminder_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );

        -- Добавить новые колонки в auto_publish_settings если их нет
        ALTER TABLE auto_publish_settings ADD COLUMN IF NOT EXISTS is_generating BOOLEAN DEFAULT FALSE;
        ALTER TABLE auto_publish_settings ADD COLUMN IF NOT EXISTS last_processed_at TIMESTAMPTZ;

        -- Индексы
        CREATE INDEX IF NOT EXISTS idx_users_chat_id ON users(chat_id);
        CREATE INDEX IF NOT EXISTS idx_channels_user_id ON channels(user_id);
        CREATE INDEX IF NOT EXISTS idx_agents_user_id ON agents(user_id);
        CREATE INDEX IF NOT EXISTS idx_posts_user_id ON posts(user_id);
        CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status);
        CREATE INDEX IF NOT EXISTS idx_scheduled_posts_status_time ON scheduled_posts(status, publish_at);
        CREATE INDEX IF NOT EXISTS idx_scheduled_posts_user_id ON scheduled_posts(user_id);
        CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments(user_id);
        CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);
        CREATE INDEX IF NOT EXISTS idx_token_usage_user_id ON token_usage(user_id);
        CREATE INDEX IF NOT EXISTS idx_auto_publish_user_id ON auto_publish_settings(user_id);
        CREATE INDEX IF NOT EXISTS idx_content_queue_user_id ON content_queue(user_id);
        CREATE INDEX IF NOT EXISTS idx_content_queue_status ON content_queue(status);

        """)
        logger.info("✅ Database tables created/verified")
