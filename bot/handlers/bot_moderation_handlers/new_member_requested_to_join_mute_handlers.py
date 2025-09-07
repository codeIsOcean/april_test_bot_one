# handlers/bot_moderation_handlers/new_member_requested_to_join_mute_handlers.py
import logging
from aiogram import Router, F, Bot
from aiogram.types import ChatMemberUpdated, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import ChatMemberUpdatedFilter
from aiogram.enums import ChatMemberStatus

from bot.services.redis_conn import redis
from bot.services.new_member_requested_to_join_mute_logic import (
    get_mute_new_members_status,
    set_mute_new_members_status,
    mute_unapproved_member,
    mute_manually_approved_member,
    create_mute_settings_keyboard,
    get_mute_settings_text
)

logger = logging.getLogger(__name__)
new_member_requested_handler = Router()


@new_member_requested_handler.callback_query(F.data == "new_member_requested_handler_settings")
async def new_member_requested_handler_settings(callback: CallbackQuery):
    """Обработчик настроек мута новых участников"""
    try:
        user_id = callback.from_user.id
        group_id = await redis.hget(f"user:{user_id}", "group_id")
        
        if not group_id:
            await callback.message.answer("❌ Не удалось найти привязку к группе. Сначала нажмите 'настроить' в группе.")
            await callback.answer()
            return
        
        group_id = int(group_id)
        
        # Получаем данные для клавиатуры
        keyboard_data = await create_mute_settings_keyboard(group_id)
        
        # Создаем клавиатуру
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=btn["text"], callback_data=btn["callback_data"])
                for btn in row
            ]
            for row in keyboard_data["buttons"]
        ])
        
        # Формируем текст сообщения
        message_text = await get_mute_settings_text(status=keyboard_data["status"])
        
        try:
            await callback.message.edit_text(
                message_text,
                reply_markup=keyboard
            )
        except Exception as e:
            if "message is not modified" not in str(e):
                logger.error(f"Ошибка при обновлении сообщения: {str(e)}")
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в new_member_requested_handler_settings: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@new_member_requested_handler.callback_query(F.data.startswith("mute_new_members:enable:"))
async def enable_mute_new_members(callback: CallbackQuery):
    """Включение мута новых участников"""
    try:
        chat_id = int(callback.data.split(":")[-1])
        user_id = callback.from_user.id
        
        # Проверяем права администратора
        group_id = await redis.hget(f"user:{user_id}", "group_id")
        if not group_id or int(group_id) != chat_id:
            await callback.message.answer("❌ Не удалось найти привязку к группе.")
            await callback.answer()
            return
        
        # Включаем мут
        success = await set_mute_new_members_status(chat_id, True)
        
        if success:
            await callback.answer("✅ Функция включена")
            # Обновляем интерфейс
            await new_member_requested_handler_settings(callback)
        else:
            await callback.answer("❌ Ошибка при включении функции", show_alert=True)
            
    except Exception as e:
        logger.error(f"Ошибка при включении мута: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@new_member_requested_handler.callback_query(F.data.startswith("mute_new_members:disable:"))
async def disable_mute_new_members(callback: CallbackQuery):
    """Выключение мута новых участников"""
    try:
        chat_id = int(callback.data.split(":")[-1])
        user_id = callback.from_user.id
        
        # Проверяем права администратора
        group_id = await redis.hget(f"user:{user_id}", "group_id")
        if not group_id or int(group_id) != chat_id:
            await callback.message.answer("❌ Не удалось найти привязку к группе.")
            await callback.answer()
            return
        
        # Выключаем мут
        success = await set_mute_new_members_status(chat_id, False)
        
        if success:
            await callback.answer("❌ Функция выключена")
            # Обновляем интерфейс
            await new_member_requested_handler_settings(callback)
        else:
            await callback.answer("❌ Ошибка при выключении функции", show_alert=True)
            
    except Exception as e:
        logger.error(f"Ошибка при выключении мута: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


# ✅ Мут через RESTRICTED статус (когда одобрение идёт через join_request)
@new_member_requested_handler.chat_member(
    F.chat.type.in_({"group", "supergroup"}),
    ChatMemberUpdatedFilter(
        member_status_changed=(None, ChatMemberStatus.RESTRICTED)
    )
)
async def mute_handler(event: ChatMemberUpdated):
    """Мут участников, не прошедших одобрение"""
    await mute_unapproved_member(event.bot, event)


# ✅ Вариант 2: Отслеживаем вручную обновление chat_member после одобрения
@new_member_requested_handler.chat_member(
    F.chat.type.in_({"group", "supergroup"})
)
async def manually_mute_on_approval(event: ChatMemberUpdated):
    """Мут вручную одобренных участников, если Telegram прислал событие"""
    await mute_manually_approved_member(event.bot, event)


# ✅ Повторная проверка при изменении прав
@new_member_requested_handler.chat_member(
    F.chat.type.in_({"group", "supergroup"}),
    ChatMemberUpdatedFilter(
        member_status_changed=(ChatMemberStatus.RESTRICTED, ChatMemberStatus.MEMBER)
    )
)
async def recheck_approved_member(event: ChatMemberUpdated):
    """Повторно мутим, если одобренный пользователь всё ещё не подтверждён"""
    await mute_unapproved_member(event.bot, event)
