from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from bot.database.models import Group, UserGroup, CaptchaSettings, ChatSettings
import logging

logger = logging.getLogger(__name__)


async def get_admin_groups(user_id: int, session: AsyncSession):
    """Получает группы где пользователь является администратором"""
    try:
        user_groups_query = select(UserGroup).where(UserGroup.user_id == user_id)
        user_groups_result = await session.execute(user_groups_query)
        user_groups = user_groups_result.scalars().all()

        logger.info(f"Найдено {len(user_groups)} записей с правами админа")

        if not user_groups:
            return []

        group_ids = [ug.group_id for ug in user_groups]
        groups_query = select(Group).where(Group.chat_id.in_(group_ids))
        groups_result = await session.execute(groups_query)
        groups = groups_result.scalars().all()

        logger.info(f"Найдено {len(groups)} групп с информацией")
        return groups

    except Exception as e:
        logger.error(f"Ошибка при получении групп пользователя {user_id}: {e}")
        return []


async def check_admin_rights(session: AsyncSession, user_id: int, chat_id: int) -> bool:
    """Проверяет права администратора пользователя в группе"""
    try:
        result = await session.execute(
            select(UserGroup).where(
                UserGroup.user_id == user_id,
                UserGroup.group_id == chat_id
            )
        )
        return result.scalar_one_or_none() is not None
    except Exception as e:
        logger.error(f"Ошибка при проверке прав администратора: {e}")
        return False


async def get_group_by_chat_id(session: AsyncSession, chat_id: int):
    """Получает группу по chat_id"""
    try:
        result = await session.execute(
            select(Group).where(Group.chat_id == chat_id)
        )
        return result.scalar_one_or_none()
    except Exception as e:
        logger.error(f"Ошибка при получении группы: {e}")
        return None


async def get_visual_captcha_status(session: AsyncSession, chat_id: int) -> bool:
    """Получает статус визуальной капчи для группы"""
    try:
        result = await session.execute(
            select(CaptchaSettings).where(CaptchaSettings.group_id == chat_id)
        )
        settings = result.scalar_one_or_none()

        is_enabled = settings.is_visual_enabled if settings else False
        logger.info(f"Статус визуальной капчи для группы {chat_id}: {'включена' if is_enabled else 'выключена'}")

        return is_enabled
    except Exception as e:
        logger.error(f"Ошибка при получении статуса капчи: {e}")
        return False


async def get_mute_new_members_status(session: AsyncSession, chat_id: int) -> bool:
    """Получает статус мута новых участников для группы"""
    try:
        from bot.services.redis_conn import redis
        
        # Проверяем Redis
        mute_enabled = await redis.get(f"group:{chat_id}:mute_new_members")
        
        if mute_enabled is not None:
            return mute_enabled == "1"
        
        # Если в Redis нет данных, проверяем в БД
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
            
    except Exception as e:
        logger.error(f"Ошибка при получении статуса мута для группы {chat_id}: {e}")
        return False


async def toggle_visual_captcha(session: AsyncSession, chat_id: int) -> bool:
    """Переключает визуальную капчу и возвращает новый статус"""
    try:
        result = await session.execute(
            select(CaptchaSettings).where(CaptchaSettings.group_id == chat_id)
        )
        settings = result.scalar_one_or_none()

        if settings:
            # Обновляем существующую запись
            new_status = not settings.is_visual_enabled
            await session.execute(
                update(CaptchaSettings)
                .where(CaptchaSettings.group_id == chat_id)
                .values(is_visual_enabled=new_status)
            )
            logger.info(f"Обновлен статус визуальной капчи для группы {chat_id}: {new_status}")
        else:
            # Создаем новую запись
            new_settings = CaptchaSettings(group_id=chat_id, is_visual_enabled=True)
            session.add(new_settings)
            new_status = True
            logger.info(f"Создана новая запись визуальной капчи для группы {chat_id}: {new_status}")

        await session.commit()
        return new_status

    except Exception as e:
        logger.error(f"Ошибка при переключении капчи: {e}")
        await session.rollback()
        return False
