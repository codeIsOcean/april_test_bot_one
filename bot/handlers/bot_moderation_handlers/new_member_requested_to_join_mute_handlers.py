from aiogram import Router, F, Bot
from aiogram.types import ChatMemberUpdated, CallbackQuery
from aiogram.filters import ChatMemberUpdatedFilter
from aiogram.enums import ChatMemberStatus
from bot.services.new_member_requested_to_join_mute_logic import (
    get_mute_settings_menu,
    enable_mute_for_group,
    disable_mute_for_group,
    mute_unapproved_member_logic,
    mute_manually_approved_member_logic
)
import logging

logger = logging.getLogger(__name__)
new_member_requested_handler = Router()


@new_member_requested_handler.callback_query(F.data.startswith("new_member_requested_handler_settings"))
async def new_member_requested_handler_settings(callback: CallbackQuery):
    """Обработчик настроек мута новых участников"""
    try:
        user_id = callback.from_user.id
        logger.info(f"🔍 [MUTE_HANDLER] Вызов настроек мута для пользователя {user_id}")
        logger.info(f"🔍 [MUTE_HANDLER] Callback data: {callback.data}")
        
        # Проверяем есть ли chat_id в callback_data
        if ":" in callback.data:
            chat_id = int(callback.data.split(":")[-1])
            logger.info(f"🔍 [MUTE_HANDLER] Chat ID из callback: {chat_id}")
            # Сохраняем привязку в Redis для совместимости
            from bot.services.redis_conn import redis
            await redis.hset(f"user:{user_id}", "group_id", str(chat_id))
            await redis.expire(f"user:{user_id}", 30 * 60)
            logger.info(f"✅ [MUTE_HANDLER] Сохранена привязка user:{user_id} -> group:{chat_id}")
        
        await get_mute_settings_menu(callback)
        await callback.answer()  # Просто убираем "загрузку" с кнопки
    except Exception as e:
        logger.error(f"Ошибка в new_member_requested_handler_settings: {e}")
        try:
            await callback.answer("❌ Произошла ошибка", show_alert=True)
        except:
            pass  # Игнорируем ошибки callback.answer()


# ✅ Мут через RESTRICTED статус (когда одобрение идёт через join_request)
@new_member_requested_handler.chat_member(
    F.chat.type.in_({"group", "supergroup"}),
    ChatMemberUpdatedFilter(
        member_status_changed=(None, ChatMemberStatus.RESTRICTED)
    )
)
async def mute_handler(event: ChatMemberUpdated):
    """Мут участников, не прошедших одобрение"""
    await mute_unapproved_member(event)


# ✅ Вариант 2: Отслеживаем вручную обновление chat_member после одобрения
@new_member_requested_handler.chat_member(
    F.chat.type.in_({"group", "supergroup"})
)
async def manually_mute_on_approval(event: ChatMemberUpdated):
    """Мут вручную одобренных участников, если Telegram прислал событие"""
    try:
        await mute_manually_approved_member_logic(event)
    except Exception as e:
        logger.error(f"MUTE ERROR (variant 2 - manual chat_member): {str(e)}")


# ✅ Повторная проверка при изменении прав
@new_member_requested_handler.chat_member(
    F.chat.type.in_({"group", "supergroup"}),
    ChatMemberUpdatedFilter(
        member_status_changed=(ChatMemberStatus.RESTRICTED, ChatMemberStatus.MEMBER)
    )
)
async def recheck_approved_member(event: ChatMemberUpdated):
    """Повторно мутим, если одобренный пользователь всё ещё не подтверждён"""
    await mute_unapproved_member(event)


@new_member_requested_handler.callback_query(F.data == "mute_new_members:enable")
async def enable_mute_new_members(callback: CallbackQuery):
    """Включение мута новых участников"""
    try:
        await enable_mute_for_group(callback)
        await callback.answer("✅ Функция включена")
    except Exception as e:
        logger.error(f"Ошибка при включении мута: {e}")
        try:
            await callback.answer("❌ Произошла ошибка", show_alert=True)
        except:
            pass  # Игнорируем ошибки callback.answer()


@new_member_requested_handler.callback_query(F.data == "mute_new_members:disable")
async def disable_mute_new_members(callback: CallbackQuery):
    """Выключение мута новых участников"""
    try:
        await disable_mute_for_group(callback)
        await callback.answer("❌ Функция выключена")
    except Exception as e:
        logger.error(f"Ошибка при выключении мута: {e}")
        try:
            await callback.answer("❌ Произошла ошибка", show_alert=True)
        except:
            pass  # Игнорируем ошибки callback.answer()


async def mute_unapproved_member(event: ChatMemberUpdated):
    """Мут участников, не прошедших одобрение"""
    try:
        await mute_unapproved_member_logic(event)
    except Exception as e:
        logger.error(f"💥 MUTE ERROR: {str(e)}")