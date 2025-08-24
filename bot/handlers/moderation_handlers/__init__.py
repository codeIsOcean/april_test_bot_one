# bot/handlers/moderation_handlers/__init__.py
from .moderation_handler import moderation_router

# Экспортируем роутер модерации
moderation_handlers_router = moderation_router

__all__ = ["moderation_handlers_router"]