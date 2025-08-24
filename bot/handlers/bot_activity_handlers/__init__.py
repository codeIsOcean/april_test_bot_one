# bot/handlers/bot_activity_handlers/__init__.py
from .bot_added_handler import bot_added_router
from .group_events import group_events_router
from aiogram import Router

# Создаем общий роутер для активности бота
bot_activity_handlers_router = Router()
bot_activity_handlers_router.include_router(bot_added_router)
bot_activity_handlers_router.include_router(group_events_router)

__all__ = ["bot_activity_handlers_router"]