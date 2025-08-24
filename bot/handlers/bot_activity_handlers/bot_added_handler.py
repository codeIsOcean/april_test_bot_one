# bot_added_handler.py
import logging
from aiogram import Router, Bot
from aiogram.filters.chat_member_updated import ChatMemberUpdatedFilter
from aiogram.types import ChatMemberUpdated
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from bot.database.models import Group, GroupUsers

logger = logging.getLogger(__name__)
bot_added_router = Router()


@bot_added_router.chat_member(ChatMemberUpdatedFilter(member_status_changed=True))
async def handle_bot_added(event: ChatMemberUpdated, bot: Bot, session: AsyncSession):
    try:
        bot_id = (await bot.me()).id
        chat_id = event.chat.id
        chat_title = event.chat.title
        from_user = event.from_user

        logger.info(f"Обработка входа бота в группу {chat_title}")

        if event.new_chat_member.user.id == bot_id:
            query = select(Group).where(Group.chat_id == chat_id)
            result = await session.execute(query)
            group = result.scalar_one_or_none()

            if group:
                group.title = chat_title
            else:
                group = Group(chat_id=chat_id, title=chat_title, bot_id=bot_id)
                session.add(group)
                await session.flush()

            admins = await bot.get_chat_administrators(chat_id)
            creator_id = from_user.id
            admin_ids = []

            for admin in admins:
                user_id = admin.user.id
                admin_ids.append(user_id)

                query = select(GroupUsers).where(
                    GroupUsers.chat_id == chat_id,
                    GroupUsers.user_id == user_id
                )
                result = await session.execute(query)
                record = result.scalar_one_or_none()

                if record:
                    record.is_admin = True
                else:
                    session.add(GroupUsers(
                        chat_id=chat_id,
                        user_id=user_id,
                        is_admin=True,
                        is_creator=(admin.status == 'creator')
                    ))

            if creator_id not in admin_ids:
                query = select(GroupUsers).where(
                    GroupUsers.chat_id == chat_id,
                    GroupUsers.user_id == creator_id
                )
                result = await session.execute(query)
                record = result.scalar_one_or_none()

                if record:
                    record.is_admin = True
                else:
                    session.add(GroupUsers(
                        chat_id=chat_id,
                        user_id=creator_id,
                        is_admin=True
                    ))

            await session.commit()
            logger.info(f"Группа и администраторы успешно синхронизированы: {chat_title}")

            await bot.send_message(
                chat_id,
                "✅ Бот добавлен и готов к работе. Используйте /settings для настройки."
            )

    except Exception as e:
        logger.error(f"Ошибка при добавлении бота в группу: {e}", exc_info=True)
        await session.rollback()
