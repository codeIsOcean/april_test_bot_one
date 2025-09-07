# services/scammer_tracker_logic.py
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, insert
from sqlalchemy.orm import selectinload

from bot.database.models import ScammerTracker, Group
from bot.database.session import get_session

logger = logging.getLogger(__name__)


async def track_captcha_failure(session: AsyncSession, user_id: int, chat_id: int, 
                               username: str = None, first_name: str = None, 
                               last_name: str = None) -> bool:
    """
    Отслеживает неудачную попытку прохождения капчи
    """
    try:
        # Проверяем, есть ли уже запись для этого пользователя в этой группе
        result = await session.execute(
            select(ScammerTracker).where(
                ScammerTracker.user_id == user_id,
                ScammerTracker.chat_id == chat_id
            )
        )
        existing_record = result.scalar_one_or_none()
        
        if existing_record:
            # Обновляем существующую запись
            existing_record.violation_count += 1
            existing_record.last_violation_at = datetime.utcnow()
            existing_record.updated_at = datetime.utcnow()
            
            # Обновляем уровень скаммера на основе количества нарушений
            existing_record.scammer_level = min(existing_record.violation_count, 5)
            existing_record.is_scammer = existing_record.violation_count >= 3
            
            logger.info(f"Обновлена запись скаммера для пользователя {user_id} в группе {chat_id}. "
                       f"Нарушений: {existing_record.violation_count}, Уровень: {existing_record.scammer_level}")
        else:
            # Создаем новую запись
            new_record = ScammerTracker(
                user_id=user_id,
                chat_id=chat_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                violation_type="captcha_failed",
                violation_count=1,
                scammer_level=1,
                is_scammer=False,
                first_violation_at=datetime.utcnow(),
                last_violation_at=datetime.utcnow()
            )
            session.add(new_record)
            logger.info(f"Создана новая запись скаммера для пользователя {user_id} в группе {chat_id}")
        
        await session.commit()
        return True
        
    except Exception as e:
        logger.error(f"Ошибка при отслеживании неудачной капчи: {e}")
        await session.rollback()
        return False


async def track_spam_behavior(session: AsyncSession, user_id: int, chat_id: int,
                            username: str = None, first_name: str = None,
                            last_name: str = None, notes: str = None) -> bool:
    """
    Отслеживает спам-поведение пользователя
    """
    try:
        # Проверяем, есть ли уже запись для этого пользователя в этой группе
        result = await session.execute(
            select(ScammerTracker).where(
                ScammerTracker.user_id == user_id,
                ScammerTracker.chat_id == chat_id
            )
        )
        existing_record = result.scalar_one_or_none()
        
        if existing_record:
            # Обновляем существующую запись
            existing_record.violation_count += 1
            existing_record.last_violation_at = datetime.utcnow()
            existing_record.updated_at = datetime.utcnow()
            existing_record.violation_type = "spam"
            
            # Обновляем уровень скаммера
            existing_record.scammer_level = min(existing_record.violation_count, 5)
            existing_record.is_scammer = existing_record.violation_count >= 2
            
            if notes:
                existing_record.notes = notes
                
            logger.info(f"Обновлена запись спамера для пользователя {user_id} в группе {chat_id}. "
                       f"Нарушений: {existing_record.violation_count}, Уровень: {existing_record.scammer_level}")
        else:
            # Создаем новую запись
            new_record = ScammerTracker(
                user_id=user_id,
                chat_id=chat_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                violation_type="spam",
                violation_count=1,
                scammer_level=2,
                is_scammer=True,
                notes=notes,
                first_violation_at=datetime.utcnow(),
                last_violation_at=datetime.utcnow()
            )
            session.add(new_record)
            logger.info(f"Создана новая запись спамера для пользователя {user_id} в группе {chat_id}")
        
        await session.commit()
        return True
        
    except Exception as e:
        logger.error(f"Ошибка при отслеживании спама: {e}")
        await session.rollback()
        return False


async def get_user_scammer_info(session: AsyncSession, user_id: int, chat_id: int) -> Optional[Dict[str, Any]]:
    """
    Получает информацию о пользователе как о потенциальном скаммере
    """
    try:
        result = await session.execute(
            select(ScammerTracker).where(
                ScammerTracker.user_id == user_id,
                ScammerTracker.chat_id == chat_id
            )
        )
        record = result.scalar_one_or_none()
        
        if not record:
            return None
        
        return {
            "user_id": record.user_id,
            "chat_id": record.chat_id,
            "username": record.username,
            "first_name": record.first_name,
            "last_name": record.last_name,
            "violation_type": record.violation_type,
            "violation_count": record.violation_count,
            "is_scammer": record.is_scammer,
            "scammer_level": record.scammer_level,
            "first_violation_at": record.first_violation_at,
            "last_violation_at": record.last_violation_at,
            "notes": record.notes,
            "is_whitelisted": record.is_whitelisted
        }
        
    except Exception as e:
        logger.error(f"Ошибка при получении информации о скаммере: {e}")
        return None


async def get_group_scammers(session: AsyncSession, chat_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Получает список скаммеров для группы
    """
    try:
        result = await session.execute(
            select(ScammerTracker)
            .where(ScammerTracker.chat_id == chat_id)
            .where(ScammerTracker.is_scammer == True)
            .order_by(ScammerTracker.scammer_level.desc(), ScammerTracker.violation_count.desc())
            .limit(limit)
        )
        records = result.scalars().all()
        
        scammers = []
        for record in records:
            scammers.append({
                "user_id": record.user_id,
                "username": record.username,
                "first_name": record.first_name,
                "last_name": record.last_name,
                "violation_type": record.violation_type,
                "violation_count": record.violation_count,
                "scammer_level": record.scammer_level,
                "first_violation_at": record.first_violation_at,
                "last_violation_at": record.last_violation_at,
                "notes": record.notes,
                "is_whitelisted": record.is_whitelisted
            })
        
        return scammers
        
    except Exception as e:
        logger.error(f"Ошибка при получении списка скаммеров: {e}")
        return []


async def whitelist_user(session: AsyncSession, user_id: int, chat_id: int, notes: str = None) -> bool:
    """
    Добавляет пользователя в белый список
    """
    try:
        result = await session.execute(
            select(ScammerTracker).where(
                ScammerTracker.user_id == user_id,
                ScammerTracker.chat_id == chat_id
            )
        )
        record = result.scalar_one_or_none()
        
        if record:
            record.is_whitelisted = True
            record.updated_at = datetime.utcnow()
            if notes:
                record.notes = notes
        else:
            # Создаем новую запись для белого списка
            new_record = ScammerTracker(
                user_id=user_id,
                chat_id=chat_id,
                violation_type="whitelisted",
                violation_count=0,
                scammer_level=0,
                is_scammer=False,
                is_whitelisted=True,
                notes=notes,
                first_violation_at=datetime.utcnow(),
                last_violation_at=datetime.utcnow()
            )
            session.add(new_record)
        
        await session.commit()
        logger.info(f"Пользователь {user_id} добавлен в белый список для группы {chat_id}")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка при добавлении в белый список: {e}")
        await session.rollback()
        return False


async def remove_from_whitelist(session: AsyncSession, user_id: int, chat_id: int) -> bool:
    """
    Удаляет пользователя из белого списка
    """
    try:
        result = await session.execute(
            select(ScammerTracker).where(
                ScammerTracker.user_id == user_id,
                ScammerTracker.chat_id == chat_id
            )
        )
        record = result.scalar_one_or_none()
        
        if record:
            record.is_whitelisted = False
            record.updated_at = datetime.utcnow()
            await session.commit()
            logger.info(f"Пользователь {user_id} удален из белого списка для группы {chat_id}")
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"Ошибка при удалении из белого списка: {e}")
        await session.rollback()
        return False


async def get_scammer_level_description(level: int) -> str:
    """
    Возвращает описание уровня скаммера
    """
    descriptions = {
        0: "Обычный пользователь",
        1: "Подозрительный (1 нарушение)",
        2: "Потенциальный спамер (2 нарушения)",
        3: "Спамер (3 нарушения)",
        4: "Активный спамер (4 нарушения)",
        5: "Опасный спамер (5+ нарушений)"
    }
    return descriptions.get(level, "Неизвестный уровень")


async def cleanup_old_records(session: AsyncSession, days_old: int = 30) -> int:
    """
    Удаляет старые записи скаммеров (старше указанного количества дней)
    """
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        
        result = await session.execute(
            select(ScammerTracker).where(
                ScammerTracker.last_violation_at < cutoff_date,
                ScammerTracker.is_whitelisted == False
            )
        )
        old_records = result.scalars().all()
        
        count = len(old_records)
        for record in old_records:
            await session.delete(record)
        
        await session.commit()
        logger.info(f"Удалено {count} старых записей скаммеров")
        return count
        
    except Exception as e:
        logger.error(f"Ошибка при очистке старых записей: {e}")
        await session.rollback()
        return 0
