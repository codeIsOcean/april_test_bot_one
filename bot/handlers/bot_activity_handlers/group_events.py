# group_events.py
import logging
from aiogram import Router, types
from aiogram.filters import ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER
from aiogram.types import ChatJoinRequest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.database.models import Group, User, GroupUsers
from bot.services.visual_captcha_logic import (
    get_visual_captcha_status,
    generate_visual_captcha,
    save_captcha_data,
    create_deeplink_for_captcha,
    get_captcha_keyboard,
    is_visual_captcha_enabled
)

logger = logging.getLogger(__name__)

group_events_router = Router()
bot_activity_handlers_router = group_events_router  # Алиас для роутера группы


@group_events_router.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=IS_NOT_MEMBER >> IS_MEMBER))
async def bot_added_to_group(event: types.ChatMemberUpdated, session: AsyncSession):
    chat = event.chat
    user = event.from_user

    logger.info(f"Бот добавлен в группу {chat.title} (ID: {chat.id}) пользователем {user.full_name} (ID: {user.id})")

    try:
        # 1. Создание или обновление пользователя
        result = await session.execute(select(User).where(User.user_id == user.id))
        db_user = result.scalar_one_or_none()
        if not db_user:
            db_user = User(user_id=user.id, username=user.username, full_name=user.full_name)
            session.add(db_user)
            await session.flush()
            logger.info(f"Создан новый пользователь: {user.full_name}")

        # 2. Проверка или создание группы
        result = await session.execute(select(Group).where(Group.chat_id == chat.id))
        group = result.scalar_one_or_none()

        if not group:
            # Получение администраторов
            creator_id = None
            admins = await event.bot.get_chat_administrators(chat.id)

            for admin in admins:
                # Создание пользователя, если не существует
                result = await session.execute(select(User).where(User.user_id == admin.user.id))
                db_admin = result.scalar_one_or_none()
                if not db_admin:
                    db_admin = User(
                        user_id=admin.user.id,
                        username=admin.user.username,
                        full_name=admin.user.full_name
                    )
                    session.add(db_admin)

            await session.flush()

            # Создание группы
            for admin in admins:
                if admin.status == "creator":
                    creator_id = admin.user.id
                    break

            group = Group(
                chat_id=chat.id,
                title=chat.title,
                creator_user_id=creator_id,
                added_by_user_id=user.id
            )
            session.add(group)
            await session.flush()
            logger.info(f"Создана новая группа: {chat.title}")

            # Добавление всех админов в GroupUsers
            for admin in admins:
                session.add(GroupUsers(
                    user_id=admin.user.id,
                    chat_id=chat.id,
                    username=admin.user.username,
                    first_name=admin.user.first_name,
                    last_name=admin.user.last_name,
                    is_admin=True
                ))
                logger.info(f"Добавлен администратор: {admin.user.full_name} (ID: {admin.user.id})")

        else:
            # Обновление названия
            group.title = chat.title
            logger.info(f"Обновлена информация о группе: {chat.title}")

        # 3. Добавление пользователя, добавившего бота, как админа
        # Сначала убеждаемся, что пользователь существует в таблице User
        result = await session.execute(select(User).where(User.user_id == user.id))
        db_user_who_added = result.scalar_one_or_none()
        if not db_user_who_added:
            db_user_who_added = User(
                user_id=user.id,
                username=user.username,
                full_name=user.full_name,
                first_name=user.first_name,
                last_name=user.last_name
            )
            session.add(db_user_who_added)
            await session.flush()
        
        # Теперь добавляем в GroupUsers
        result = await session.execute(select(GroupUsers).where(
            GroupUsers.chat_id == chat.id,
            GroupUsers.user_id == user.id
        ))
        if not result.scalar_one_or_none():
            session.add(GroupUsers(
                chat_id=chat.id,
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                is_admin=True
            ))
            logger.info(f"Добавлен пользователь, добавивший бота: {user.full_name}")

        await session.commit()
        logger.info(f"Информация о группе {chat.title} успешно сохранена")

    except Exception as e:
        logger.error(f"Ошибка при добавлении группы: {e}")
        await session.rollback()
        raise


@bot_activity_handlers_router.chat_join_request()
async def handle_join_request(chat_join_request: ChatJoinRequest, session: AsyncSession):
    """Обработчик запроса на вступление в группу"""
    chat_id = chat_join_request.chat.id
    user = chat_join_request.from_user

    logger.info(f"📨 Получен запрос на вступление от пользователя {user.id} в группу {chat_id}")

    try:
        # Проверяем активна ли визуальная капча
        if not await is_visual_captcha_enabled(session, chat_id):
            logger.info(f"⛔ Визуальная капча не активирована в группе {chat_id}, выходим из handle_join_request")
            return

        logger.info(f"✅ Визуальная капча активирована в группе {chat_id}, отправляем капчу пользователю")

        # НЕ ГЕНЕРИРУЕМ КАПЧУ СРАЗУ - только создаем кнопку
        group_name = str(chat_id)

        # Создаем deep link
        deep_link = await create_deeplink_for_captcha(chat_join_request.bot, group_name)

        # Создаем клавиатуру
        keyboard = await get_captcha_keyboard(deep_link)

        # Отправляем ТОЛЬКО текст с кнопкой (БЕЗ ФОТО)
        try:
            await chat_join_request.bot.send_message(
                chat_id=user.id,
                text="🔒 Для вступления в группу решите капчу:",
                reply_markup=keyboard
            )
            logger.info(f"📤 Капча отправлена пользователю {user.id}")
        except Exception as send_error:
            logger.warning(f"⚠️ Не удалось отправить капчу пользовател�� {user.id}: {send_error}")
            # Пользователь заблокировал бота или не начал диалог
            return
        
    except Exception as e:
        logger.error(f"Ошибка при обработке запроса на вступление: {e}")
        await session.rollback()
        raise
