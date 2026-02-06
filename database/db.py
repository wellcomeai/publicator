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

            -- Freemium
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
            
            -- Статус: draft / editing / published
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
        
        -- Платежи
        CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY,
            user_id INT REFERENCES users(id) ON DELETE CASCADE,
            amount_rub INT NOT NULL,

            -- subscription / tokens
            payment_type VARCHAR(30) NOT NULL,
            tokens_amount INT DEFAULT 0,
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
        
        -- Настройки пользователя
        CREATE TABLE IF NOT EXISTS user_settings (
            id SERIAL PRIMARY KEY,
            user_id INT REFERENCES users(id) ON DELETE CASCADE,
            auto_cover BOOLEAN DEFAULT FALSE,
            default_image_style VARCHAR(100) DEFAULT '',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(user_id)
        );

        -- Отложенные посты
        CREATE TABLE IF NOT EXISTS scheduled_posts (
            id SERIAL PRIMARY KEY,
            post_id INT REFERENCES posts(id) ON DELETE CASCADE,
            user_id INT REFERENCES users(id) ON DELETE CASCADE,
            channel_id BIGINT NOT NULL,
            scheduled_at TIMESTAMPTZ NOT NULL,
            status VARCHAR(20) DEFAULT 'pending',
            error_message TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            published_at TIMESTAMPTZ
        );

        -- Индексы
        CREATE INDEX IF NOT EXISTS idx_users_chat_id ON users(chat_id);
        CREATE INDEX IF NOT EXISTS idx_channels_user_id ON channels(user_id);
        CREATE INDEX IF NOT EXISTS idx_agents_user_id ON agents(user_id);
        CREATE INDEX IF NOT EXISTS idx_posts_user_id ON posts(user_id);
        CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status);
        CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments(user_id);
        CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);
        CREATE INDEX IF NOT EXISTS idx_token_usage_user_id ON token_usage(user_id);
        CREATE INDEX IF NOT EXISTS idx_user_settings_user_id ON user_settings(user_id);
        CREATE INDEX IF NOT EXISTS idx_scheduled_posts_status ON scheduled_posts(status);
        CREATE INDEX IF NOT EXISTS idx_scheduled_posts_scheduled_at ON scheduled_posts(scheduled_at);
        
        """)
        logger.info("✅ Database tables created/verified")
