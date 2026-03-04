import asyncpg
import os
from dotenv import load_dotenv
from datetime import datetime, date

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

_pool = None

async def get_pool():
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=3,
            max_size=15,
            command_timeout=10,
            max_inactive_connection_lifetime=300,
        )
    return _pool


async def create_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id       BIGINT PRIMARY KEY,
                full_name     TEXT,
                username      TEXT,
                usage_count   INTEGER DEFAULT 1,
                is_banned     BOOLEAN DEFAULT FALSE,
                language      TEXT DEFAULT 'uz',
                joined_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS feedback (
                id            SERIAL PRIMARY KEY,
                user_id       BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                feedback_text TEXT,
                rating        INTEGER,
                sent_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS schedule_views (
                id         SERIAL PRIMARY KEY,
                user_id    BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                class_name TEXT,
                day_name   TEXT,
                viewed_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS reminders (
                user_id    BIGINT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
                class_name TEXT NOT NULL,
                enabled    BOOLEAN DEFAULT TRUE
            );

            CREATE INDEX IF NOT EXISTS idx_users_last_active ON users(last_active);
            CREATE INDEX IF NOT EXISTS idx_views_user ON schedule_views(user_id);
            CREATE INDEX IF NOT EXISTS idx_views_class ON schedule_views(class_name);
        """)


# ── USER ─────────────────────────────────────────────────────────────────────

async def register_user(user_id: int, full_name: str, username: str = None):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, full_name, username)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id) DO UPDATE
            SET usage_count = users.usage_count + 1,
                last_active = CURRENT_TIMESTAMP,
                full_name   = EXCLUDED.full_name,
                username    = COALESCE(EXCLUDED.username, users.username);
        """, user_id, full_name, username)


async def get_user(user_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)


async def is_banned(user_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT is_banned FROM users WHERE user_id=$1", user_id) or False


async def ban_user(user_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET is_banned=TRUE WHERE user_id=$1", user_id)


async def unban_user(user_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET is_banned=FALSE WHERE user_id=$1", user_id)


async def get_all_users(active_only: bool = False):
    pool = await get_pool()
    async with pool.acquire() as conn:
        if active_only:
            rows = await conn.fetch(
                "SELECT user_id FROM users WHERE is_banned=FALSE AND last_active > NOW() - INTERVAL '30 days'"
            )
        else:
            rows = await conn.fetch("SELECT user_id FROM users WHERE is_banned=FALSE")
        return [r['user_id'] for r in rows]


async def search_user(query: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch("""
            SELECT user_id, full_name, username, usage_count, last_active, is_banned
            FROM users
            WHERE full_name ILIKE $1 OR username ILIKE $1 OR user_id::TEXT = $2
            LIMIT 10
        """, f'%{query}%', query)


# ── STATISTICS ────────────────────────────────────────────────────────────────

async def get_full_stats():
    pool = await get_pool()
    async with pool.acquire() as conn:
        total, today, week, banned, top_classes = await asyncio.gather(
            conn.fetchval("SELECT COUNT(*) FROM users"),
            conn.fetchval("SELECT COUNT(*) FROM users WHERE last_active::DATE = CURRENT_DATE"),
            conn.fetchval("SELECT COUNT(*) FROM users WHERE last_active > NOW() - INTERVAL '7 days'"),
            conn.fetchval("SELECT COUNT(*) FROM users WHERE is_banned=TRUE"),
            conn.fetch("""
                SELECT class_name, COUNT(*) as cnt
                FROM schedule_views
                WHERE viewed_at > NOW() - INTERVAL '7 days'
                GROUP BY class_name ORDER BY cnt DESC LIMIT 5
            """)
        )
        return {
            'total': total, 'today': today,
            'week': week, 'banned': banned,
            'top_classes': top_classes
        }


async def get_user_stats(user_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        user, views, fav = await asyncio.gather(
            conn.fetchrow("SELECT usage_count, joined_at, last_active FROM users WHERE user_id=$1", user_id),
            conn.fetchval("SELECT COUNT(*) FROM schedule_views WHERE user_id=$1", user_id),
            conn.fetchrow("""
                SELECT class_name, COUNT(*) as cnt FROM schedule_views
                WHERE user_id=$1 GROUP BY class_name ORDER BY cnt DESC LIMIT 1
            """, user_id)
        )
        return user, views, fav


async def get_growth_chart():
    """So'nggi 7 kun bo'yicha yangi foydalanuvchilar"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT joined_at::DATE as day, COUNT(*) as cnt
            FROM users
            WHERE joined_at > NOW() - INTERVAL '7 days'
            GROUP BY day ORDER BY day
        """)
        return rows


# ── SCHEDULE VIEWS ────────────────────────────────────────────────────────────

async def log_schedule_view(user_id: int, class_name: str, day_name: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO schedule_views (user_id, class_name, day_name) VALUES ($1,$2,$3)",
            user_id, class_name, day_name
        )


# ── FEEDBACK ──────────────────────────────────────────────────────────────────

async def save_feedback(user_id: int, text: str, rating: int = None):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO feedback (user_id, feedback_text, rating) VALUES ($1,$2,$3)",
            user_id, text, rating
        )


async def get_recent_feedback(limit: int = 10):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch("""
            SELECT f.feedback_text, f.rating, f.sent_at, u.full_name, u.user_id
            FROM feedback f JOIN users u ON f.user_id=u.user_id
            ORDER BY f.sent_at DESC LIMIT $1
        """, limit)


# ── REMINDERS ─────────────────────────────────────────────────────────────────

async def set_reminder(user_id: int, class_name: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO reminders (user_id, class_name) VALUES ($1,$2)
            ON CONFLICT (user_id) DO UPDATE SET class_name=$2, enabled=TRUE
        """, user_id, class_name)


async def toggle_reminder(user_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        current = await conn.fetchval("SELECT enabled FROM reminders WHERE user_id=$1", user_id)
        if current is None:
            return False
        new_state = not current
        await conn.execute("UPDATE reminders SET enabled=$1 WHERE user_id=$2", new_state, user_id)
        return new_state


async def get_active_reminders():
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT user_id, class_name FROM reminders WHERE enabled=TRUE"
        )

import asyncio
