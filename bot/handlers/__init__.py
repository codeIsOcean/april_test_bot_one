from aiogram import Router

# Создаем главный роутер
handlers_router = Router()

# Импортируем роутеры
from .deep_link_handlers import universal_deeplink_router
from .bot_activity_handlers import bot_activity_handlers_router
from .visual_captcha import visual_captcha_router
from .moderation_handlers import moderation_handlers_router

# Импортируем group_settings_router ТОЛЬКО один раз
from .group_settings_handler.group_settings_handler import group_settings_router

# Подключаем роутеры
handlers_router.include_router(universal_deeplink_router)
handlers_router.include_router(bot_activity_handlers_router)
handlers_router.include_router(visual_captcha_router)
handlers_router.include_router(group_settings_router)
handlers_router.include_router(moderation_handlers_router)

__all__ = ["handlers_router"]