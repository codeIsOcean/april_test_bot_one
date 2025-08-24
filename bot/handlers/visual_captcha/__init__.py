# bot/handlers/visual_captcha/__init__.py
from .visual_captcha_handler import visual_captcha_handler_router

# Экспортируем роутер под понятным именем
visual_captcha_router = visual_captcha_handler_router

__all__ = ["visual_captcha_router"]