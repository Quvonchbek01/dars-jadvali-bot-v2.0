from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject
from typing import Callable, Dict, Any, Awaitable
from collections import defaultdict
import time
import asyncio


class ThrottleMiddleware(BaseMiddleware):
    """Anti-spam: 1 soniyada 1 ta so'rov"""

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
                    await event.answer("⏳ Iltimos, biroz kuting...", show_alert=False)
                return  # So'rovni o'tkazib yuborish
            self._user_timestamps[user.id] = now

        return await handler(event, data)


class BanMiddleware(BaseMiddleware):
    """Banned foydalanuvchilarni bloklash"""

    def __init__(self):
        from db import is_banned
        self._is_banned = is_banned

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
            banned = await self._is_banned(user.id)
            if banned:
                if isinstance(event, Message):
                    await event.answer("🚫 Siz botdan foydalana olmaysiz.")
                elif isinstance(event, CallbackQuery):
                    await event.answer("🚫 Siz bloklangansiz.", show_alert=True)
                return

        return await handler(event, data)
