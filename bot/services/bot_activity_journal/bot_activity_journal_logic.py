# services/bot_activity_journal/bot_activity_journal_logic.py
import logging
from typing import Dict, Any, Optional
from aiogram import Bot
from aiogram.types import User, Chat
from bot.handlers.bot_activity_journal.bot_activity_journal import send_activity_log

logger = logging.getLogger(__name__)


async def log_join_request(
    bot: Bot,
    user: User,
    chat: Chat,
    captcha_status: str = "КАПЧА_НЕ_УДАЛАСЬ",
    saved_to_db: bool = False
):
    """Логирует запрос на вступление в группу"""
    try:
        user_data = {
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
        }
        
        group_data = {
            "chat_id": chat.id,
            "title": chat.title,
            "username": chat.username,
        }
        
        additional_info = {
            "captcha_status": captcha_status,
            "saved_to_db": saved_to_db,
        }
        
        await send_activity_log(
            bot=bot,
            event_type="ЗАПРОС_НА_ВСТУПЛЕНИЕ",
            user_data=user_data,
            group_data=group_data,
            additional_info=additional_info,
            status="failed" if captcha_status == "КАПЧА_НЕ_УДАЛАСЬ" else "success"
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка при логировании запроса на вступление: {e}")


async def log_new_member(
    bot: Bot,
    user: User,
    chat: Chat
):
    """Логирует нового участника группы"""
    try:
        user_data = {
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
        }
        
        group_data = {
            "chat_id": chat.id,
            "title": chat.title,
            "username": chat.username,
        }
        
        await send_activity_log(
            bot=bot,
            event_type="НовыйПользователь",
            user_data=user_data,
            group_data=group_data,
            status="success"
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка при логировании нового участника: {e}")


async def log_user_left(
    bot: Bot,
    user: User,
    chat: Chat
):
    """Логирует выход пользователя из группы"""
    try:
        user_data = {
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
        }
        
        group_data = {
            "chat_id": chat.id,
            "title": chat.title,
            "username": chat.username,
        }
        
        await send_activity_log(
            bot=bot,
            event_type="пользовательвышел",
            user_data=user_data,
            group_data=group_data,
            status="success"
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка при логировании выхода пользователя: {e}")


async def log_user_kicked(
    bot: Bot,
    user: User,
    chat: Chat,
    initiator: Optional[User] = None
):
    """Логирует удаление пользователя из группы"""
    try:
        user_data = {
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
        }
        
        group_data = {
            "chat_id": chat.id,
            "title": chat.title,
            "username": chat.username,
        }
        
        additional_info = {}
        if initiator:
            additional_info["initiator"] = {
                "user_id": initiator.id,
                "username": initiator.username,
                "first_name": initiator.first_name,
                "last_name": initiator.last_name,
            }
        
        await send_activity_log(
            bot=bot,
            event_type="пользовательудален",
            user_data=user_data,
            group_data=group_data,
            additional_info=additional_info,
            status="success"
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка при логировании удаления пользователя: {e}")


async def log_visual_captcha_toggle(
    bot: Bot,
    user: User,
    chat: Chat,
    enabled: bool
):
    """Логирует включение/выключение визуальной капчи"""
    try:
        user_data = {
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
        }
        
        group_data = {
            "chat_id": chat.id,
            "title": chat.title,
            "username": chat.username,
        }
        
        event_type = "Визуальная капча включена" if enabled else "Визуальная капча выключена"
        
        await send_activity_log(
            bot=bot,
            event_type=event_type,
            user_data=user_data,
            group_data=group_data,
            status="success"
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка при логировании переключения визуальной капчи: {e}")


async def log_mute_settings_toggle(
    bot: Bot,
    user: User,
    chat: Chat,
    enabled: bool
):
    """Логирует включение/выключение настроек мута новых пользователей"""
    try:
        user_data = {
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
        }
        
        group_data = {
            "chat_id": chat.id,
            "title": chat.title,
            "username": chat.username,
        }
        
        event_type = "Настройка мута новых пользователей включена" if enabled else "Настройка мута новых пользователей выключена"
        
        await send_activity_log(
            bot=bot,
            event_type=event_type,
            user_data=user_data,
            group_data=group_data,
            status="success"
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка при логировании переключения настроек мута: {e}")


async def log_bot_added_to_group(
    bot: Bot,
    chat: Chat,
    added_by: Optional[User] = None
):
    """Логирует добавление бота в группу"""
    try:
        # Получаем информацию о боте
        bot_info = await bot.me()
        
        # Используем данные бота как пользователя для логирования
        user_data = {
            "user_id": bot_info.id,
            "username": bot_info.username,
            "first_name": bot_info.first_name,
            "last_name": "",
        }
        
        group_data = {
            "chat_id": chat.id,
            "title": chat.title,
            "username": chat.username,
        }
        
        additional_info = {}
        if added_by:
            additional_info["added_by"] = {
                "user_id": added_by.id,
                "username": added_by.username,
                "first_name": added_by.first_name,
                "last_name": added_by.last_name,
            }
        
        await send_activity_log(
            bot=bot,
            event_type="БОТ_ДОБАВЛЕН_В_ГРУППУ",
            user_data=user_data,
            group_data=group_data,
            additional_info=additional_info,
            status="success"
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка при логировании добавления бота в группу: {e}")
