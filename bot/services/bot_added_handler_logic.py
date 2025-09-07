# bot/handlers/bot_activity_handlers/bot_added_handler_logic.py
import logging
from typing import Optional

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.database.models import Group, GroupUsers, User
from bot.database.session import get_session

logger = logging.getLogger(__name__)


async def safe_send(bot: Bot, chat_id: int, text: str, **kwargs) -> Optional[Message]:
    """
    Безопасная отправка сообщения в чат: логирует исключения (403/400 и т.д.), ничего не падает.
    Возвращает Message или None.
    """
    try:
        return await bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        logger.exception(f"[SEND_MESSAGE_FAIL] chat_id={chat_id} error={e}")
        return None


async def is_user_group_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    """
    Проверка, является ли пользователь админом/создателем группы.
    """
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)
    except Exception:
        logger.exception(f"[CHECK_ADMIN_FAIL] chat_id={chat_id} user_id={user_id}")
        return False


async def build_private_chat_link(bot: Bot) -> Optional[str]:
    """
    Возвращает ссылку на приватный чат с ботом вида https://t.me/<username>.
    Если username нет (бот скрыт), вернёт None.
    """
    bot_info = await bot.me()
    if bot_info.username:
        return f"https://t.me/{bot_info.username}"
    return None


async def sync_group_and_admins(chat_id: int, title: str, bot_id: int, bot: Bot):
    """
    Синхронизация группы и админов с базой данных.
    """
    async with get_session() as session:
        try:
            # 🏠 Проверяем и сохраняем информацию о группе
            stmt = select(Group).where(Group.chat_id == chat_id)
            result = await session.execute(stmt)
            existing_group = result.scalar_one_or_none()

            if existing_group:
                # Обновляем существующую запись
                existing_group.title = title
                existing_group.bot_id = bot_id
            else:
                # Создаем новую запись
                group = Group(
                    chat_id=chat_id,
                    title=title,
                    creator_user_id=None,
                    bot_id=bot_id
                )
                session.add(group)

            # 🤖 Сохраняем бота как администратора
            bot_me = await bot.me()
            stmt = select(GroupUsers).where(
                GroupUsers.user_id == bot_me.id,
                GroupUsers.chat_id == chat_id
            )
            result = await session.execute(stmt)
            existing_bot_user = result.scalar_one_or_none()

            if existing_bot_user:
                existing_bot_user.username = bot_me.username
                existing_bot_user.is_admin = True
            else:
                bot_user = GroupUsers(
                    user_id=bot_me.id,
                    chat_id=chat_id,
                    username=bot_me.username,
                    is_admin=True
                )
                session.add(bot_user)

            # 👥 Получаем и сохраняем всех админов группы
            admins = await bot.get_chat_administrators(chat_id)
            admin_count = 0

            for admin in admins:
                user = admin.user

                # Сохраняем пользователя в таблицу User
                stmt = select(User).where(User.user_id == user.id)
                result = await session.execute(stmt)
                existing_user = result.scalar_one_or_none()

                if existing_user:
                    existing_user.username = user.username
                    existing_user.full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
                else:
                    new_user = User(
                        user_id=user.id,
                        username=user.username,
                        full_name=f"{user.first_name or ''} {user.last_name or ''}".strip()
                    )
                    session.add(new_user)

                # Сохраняем связь пользователь-группа
                is_creator = (admin.status == ChatMemberStatus.CREATOR)
                stmt = select(GroupUsers).where(
                    GroupUsers.user_id == user.id,
                    GroupUsers.chat_id == chat_id
                )
                result = await session.execute(stmt)
                existing_group_user = result.scalar_one_or_none()

                if existing_group_user:
                    existing_group_user.username = user.username
                    existing_group_user.first_name = user.first_name
                    existing_group_user.last_name = user.last_name
                    existing_group_user.is_admin = True
                    existing_group_user.is_creator = is_creator
                else:
                    group_user = GroupUsers(
                        user_id=user.id,
                        chat_id=chat_id,
                        username=user.username,
                        first_name=user.first_name,
                        last_name=user.last_name,
                        is_admin=True,
                        is_creator=is_creator
                    )
                    session.add(group_user)
                admin_count += 1

            await session.commit()
            logger.info(f"[SYNC_GROUP_ADMINS] chat_id={chat_id} title='{title}' admins_count={admin_count}")

        except Exception:
            logger.exception(f"[SYNC_GROUP_ADMINS_FAIL] chat_id={chat_id}")
            await session.rollback()
            raise


async def get_bot_username(bot: Bot) -> Optional[str]:
    """
    Получает username бота.
    """
    try:
        bot_info = await bot.me()
        return bot_info.username
    except Exception:
        logger.exception("[GET_BOT_USERNAME_FAIL]")
        return None
