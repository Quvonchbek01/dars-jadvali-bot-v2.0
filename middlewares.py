from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject
from typing import Callable, Dict, Any, Awaitable
from collections import defaultdict
import time


class ThrottleMiddleware(BaseMiddleware):
    """Anti-spam: rate limit per user"""

    def __init__(self, rate_limit: float = 1.0):
        self.rate_limit = rate_limit
        self._user_timestamps: Dict[int, float] = defaultdict(float)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = None
        if isinstance(event, (Message, CallbackQuery)):
            user = event.from_user

        if user:
            now = time.monotonic()
            last = self._user_timestamps[user.id]
            if now - last < self.rate_limit:
                if isinstance(event, CallbackQuery):
                    await event.answer("⏳ Biroz kuting...", show_alert=False)
                return
            self._user_timestamps[user.id] = now

        return await handler(event, data)


class BanMiddleware(BaseMiddleware):
    """
    Banned foydalanuvchilarni bloklash.
    TTL cache: har 60 soniyada bir marta DB ga sorrov - sekinlikni oldini oladi.
    """

    CACHE_TTL = 60  # soniya

    def __init__(self):
        from db import is_banned
        self._is_banned = is_banned
        # {user_id: (is_banned: bool, timestamp: float)}
        self._cache: Dict[int, tuple] = {}

    async def _check_banned(self, user_id: int) -> bool:
        now = time.monotonic()
        cached = self._cache.get(user_id)
        if cached and (now - cached[1]) < self.CACHE_TTL:
            return cached[0]
        result = await self._is_banned(user_id)
        self._cache[user_id] = (result, now)
        return result

    def invalidate(self, user_id: int):
        """Ban/unban bolganda cacheni tozalash"""
        self._cache.pop(user_id, None)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = None
        if isinstance(event, (Message, CallbackQuery)):
            user = event.from_user

        if user:
            banned = await self._check_banned(user.id)
            if banned:
                if isinstance(event, Message):
                    await event.answer("Siz botdan foydalana olmaysiz.")
                elif isinstance(event, CallbackQuery):
                    await event.answer("Siz bloklangansiz.", show_alert=True)
                return

        return await handler(event, data)
