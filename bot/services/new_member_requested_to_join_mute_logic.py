# services/new_member_requested_to_join_mute_logic.py
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from aiogram import Bot
from aiogram.types import ChatMemberUpdated, ChatPermissions
from aiogram.enums import ChatMemberStatus
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, insert

from bot.services.redis_conn import redis
from bot.database.models import ChatSettings
from bot.database.session import get_session
from bot.services.scammer_tracker_logic import track_captcha_failure

logger = logging.getLogger(__name__)


async def get_mute_new_members_status(chat_id: int, session: AsyncSession = None) -> bool:
    """
    Получает статус мута новых участников для группы
    Сначала проверяет Redis, затем БД
    """
    try:
        # Проверяем Redis
        mute_enabled = await redis.get(f"group:{chat_id}:mute_new_members")
        
        if mute_enabled is not None:
            return mute_enabled == "1"
        
        # Если в Redis нет данных, проверяем в БД
        if session:
            # Используем переданную сессию
            result = await session.execute(
                select(ChatSettings).where(ChatSettings.chat_id == chat_id)
            )
            settings = result.scalar_one_or_none()
            
            if settings and hasattr(settings, 'mute_new_members'):
                mute_enabled = "1" if settings.mute_new_members else "0"
                # Обновляем Redis
                await redis.set(f"group:{chat_id}:mute_new_members", mute_enabled)
                return settings.mute_new_members
            else:
                # По умолчанию выключено
                await redis.set(f"group:{chat_id}:mute_new_members", "0")
                return False
        else:
            # Создаем новую сессию
            async with get_session() as new_session:
                result = await new_session.execute(
                    select(ChatSettings).where(ChatSettings.chat_id == chat_id)
                )
                settings = result.scalar_one_or_none()
                
                if settings and hasattr(settings, 'mute_new_members'):
                    mute_enabled = "1" if settings.mute_new_members else "0"
                    # Обновляем Redis
                    await redis.set(f"group:{chat_id}:mute_new_members", mute_enabled)
                    return settings.mute_new_members
                else:
                    # По умолчанию выключено
                    await redis.set(f"group:{chat_id}:mute_new_members", "0")
                    return False
                
    except Exception as e:
        logger.error(f"Ошибка при получении статуса мута для группы {chat_id}: {e}")
        return False


async def set_mute_new_members_status(chat_id: int, enabled: bool) -> bool:
    """
    Устанавливает статус мута новых участников для группы
    Сохраняет в Redis и БД
    """
    try:
        # Сохраняем в Redis
        await redis.set(f"group:{chat_id}:mute_new_members", "1" if enabled else "0")
        
        # Сохраняем в БД
        async with get_session() as session:
            result = await session.execute(
                select(ChatSettings).where(ChatSettings.chat_id == chat_id)
            )
            settings = result.scalar_one_or_none()
            
            if settings:
                await session.execute(
                    update(ChatSettings)
                    .where(ChatSettings.chat_id == chat_id)
                    .values(mute_new_members=enabled)
                )
            else:
                await session.execute(
                    insert(ChatSettings).values(
                        chat_id=chat_id,
                        mute_new_members=enabled,
                        enable_photo_filter=False,
                        admins_bypass_photo_filter=False,
                        photo_filter_mute_minutes=60
                    )
                )
            
            await session.commit()
            logger.info(f"✅ Статус мута новых участников для группы {chat_id}: {'включен' if enabled else 'выключен'}")
            return True
            
    except Exception as e:
        logger.error(f"Ошибка при установке статуса мута для группы {chat_id}: {e}")
        return False


async def mute_unapproved_member(bot: Bot, event: ChatMemberUpdated) -> bool:
    """
    НЕ мутит участников автоматически - только логирует для отладки.
    Мут происходит только через manually_mute_on_approval когда админ вручную одобряет.
    """
    try:
        chat_id = event.chat.id
        user = event.new_chat_member.user
        
        # Проверяем, включен ли мут для этой группы
        mute_enabled = await get_mute_new_members_status(chat_id)
        
        if not mute_enabled:
            logger.debug(f"Мут для группы {chat_id} отключен, пропускаем")
            return False
        
        # Проверяем статусы для логирования
        old_status = event.old_chat_member.status
        new_status = event.new_chat_member.status
        is_approved = getattr(event.new_chat_member, 'is_approved', True)
        
        logger.info(f"🔍 Chat member update: user={user.id}, old={old_status}, new={new_status}, approved={is_approved}")
        
        # НЕ мутим автоматически - только логируем
        logger.debug(f"Пользователь {user.id} не мутится автоматически - мут только через ручное одобрение админом")
        
        return False
        
    except Exception as e:
        logger.error(f"💥 Ошибка при обработке chat member update: {str(e)}")
        return False


async def mute_manually_approved_member(bot: Bot, event: ChatMemberUpdated) -> bool:
    """
    Мутит вручную одобренных участников
    """
    try:
        old_status = event.old_chat_member.status
        new_status = event.new_chat_member.status
        
        logger.debug(f"Обработка chat_member: {event.from_user.id} | old={old_status} -> new={new_status}")
        
        if old_status in ("left", "kicked") and new_status == "member":
            chat_id = event.chat.id
            user = event.new_chat_member.user
            
            # Проверяем, включен ли мут для этой группы
            mute_enabled = await get_mute_new_members_status(chat_id)
            
            if not mute_enabled:
                logger.debug(f"Мут для группы {chat_id} отключен, пропускаем")
                return False
            
            # Дополнительная проверка: мутим только если это действительно ручное одобрение
            # Проверяем, что пользователь был в статусе "requested" перед одобрением
            if old_status not in ("left", "kicked"):
                logger.debug(f"Пользователь {user.id} не был в статусе left/kicked, пропускаем мут")
                return False
            
            # Проверяем, что это не автоматическое одобрение через капчу
            # Если пользователь прошел капчу, он не должен мутиться
            captcha_passed = await redis.get(f"captcha_passed:{user.id}:{chat_id}")
            if captcha_passed:
                logger.debug(f"Пользователь {user.id} прошел капчу, не мутим")
                return False
            
            logger.info(f"🔇 Мутим пользователя @{user.username or user.id} после ручного одобрения админом")
            
            # Применяем мут
            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user.id,
                permissions=ChatPermissions(
                    can_send_messages=False,
                    can_send_media_messages=False,
                    can_send_polls=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False,
                    can_change_info=False,
                    can_invite_users=False,
                    can_pin_messages=False
                ),
                until_date=datetime.now() + timedelta(days=366 * 10)
            )
            
            await asyncio.sleep(1)
            logger.info(f"🔇 Пользователь @{user.username or user.id} был замьючен после ручного одобрения (chat_member).")
            
            # Отслеживаем пользователя как скаммера
            try:
                async with get_session() as session:
                    await track_captcha_failure(
                        session,
                        user.id,
                        chat_id,
                        user.username,
                        user.first_name,
                        user.last_name,
                        violation_type="manual_mute_by_admin"
                    )
                logger.info(f"Пользователь {user.id} добавлен в список скаммеров за мут админом")
            except Exception as e:
                logger.error(f"Ошибка при отслеживании скаммера: {e}")
            
            return True
        else:
            logger.debug(f"Не обработан: статус не соответствует. old={old_status}, new={new_status}")
            return False
            
    except Exception as e:
        logger.error(f"MUTE ERROR (variant 2 - manual chat_member): {str(e)}")
        return False


async def create_mute_settings_keyboard(chat_id: int, session: AsyncSession = None) -> dict:
    """
    Создает клавиатуру для настроек мута новых участников
    """
    mute_enabled = await get_mute_new_members_status(chat_id, session)
    
    # Создаем текст кнопок с галочкой перед выбранным состоянием
    enable_text = "✓ Включить" if mute_enabled else "Включить"
    disable_text = "✓ Выключить" if not mute_enabled else "Выключить"
    
    keyboard_data = {
        "buttons": [
            [
                {"text": enable_text, "callback_data": f"mute_new_members:enable:{chat_id}"},
                {"text": disable_text, "callback_data": f"mute_new_members:disable:{chat_id}"}
            ],
            [{"text": "« Назад", "callback_data": "back_to_groups"}]
        ],
        "status": mute_enabled  # Возвращаем булево значение
    }
    
    return keyboard_data


async def get_mute_settings_text(status: bool = False) -> str:
    """
    Возвращает текст для настроек мута новых участников
    """
    status_text = "✅ Включено" if status else "❌ Выключено"
    return (
        f"⚙️ Настройки мута для новых участников при ручном добавлении:\n\n"
        f"• Новые участники автоматически получают мут\n"
        f"• Мут действует 3660 дней\n"
        f"• Текущее состояние: {status_text}\n\n"
        f"Эта функция защищает вашу группу от спамеров."
    )
