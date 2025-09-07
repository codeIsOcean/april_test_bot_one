import logging
from typing import Dict, Optional
import asyncio

# Кэш для хранения состояний групп
_captcha_status_cache: Dict[int, bool] = {}
_cache_lock = asyncio.Lock()

async def get_visual_captcha_status(chat_id: int) -> bool:
    """Получить статус визуальной капчи для группы"""
    async with _cache_lock:
        if chat_id in _captcha_status_cache:
            return _captcha_status_cache[chat_id]

    # Здесь должен быть запрос к базе данных
    # status = await db.get_visual_captcha_status(chat_id)
    status = False  # Заглушка

    async with _cache_lock:
        _captcha_status_cache[chat_id] = status

    return status

async def update_visual_captcha_status(chat_id: int, status: bool):
    """Обновить статус визуальной капчи для группы"""
    # Обновляем в базе данных
    # await db.update_visual_captcha_status(chat_id, status)

    # Обновляем кэш
    async with _cache_lock:
        _captcha_status_cache[chat_id] = status

async def get_admin_records(user_id: int):
    """Получить записи с правами админа для пользователя"""
    # Здесь должна быть ваша логика получения записей администратора
    # Например, запрос к базе данных
    return []

async def chat_exists(chat_id: int) -> bool:
    """Проверить существование чата"""
    try:
        # Здесь должна быть проверка через bot.get_chat(chat_id)
        return True
    except Exception:
        return False
