from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession
from bot.database.models import Group, GroupUsers, User
from bot.database.session import get_session


async def sync_group_and_admins(chat_id: int, title: str, bot_id: int, bot: Bot):
    session: AsyncSession = await get_session()

    # 🏠 Сохраняем информацию о группе
    group = Group(
        chat_id=chat_id,
        title=title,
        creator_user_id=None,
        bot_id=bot_id
    )
    await session.merge(group)

    # 🤖 Сохраняем бота как администратора
    bot_me = await bot.me()
    bot_user = GroupUsers(
        user_id=bot_me.id,
        chat_id=chat_id,
        username=bot_me.username,
        is_admin=True
    )
    await session.merge(bot_user)

    # 👥 Получаем и сохраняем всех админов группы
    admins = await bot.get_chat_administrators(chat_id)
    for admin in admins:
        user = admin.user

        await session.merge(User(
            user_id=user.id,
            username=user.username,
            full_name=f"{user.first_name or ''} {user.last_name or ''}".strip()
        ))

        await session.merge(GroupUsers(
            user_id=user.id,
            chat_id=chat_id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            is_admin=True
        ))

    await session.commit()


