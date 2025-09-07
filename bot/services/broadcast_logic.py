# services/broadcast_logic.py
import asyncio
import logging
from typing import List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from aiogram import Bot
from aiogram.types import Message
from bot.database.models import User
from bot.database.session import get_session

logger = logging.getLogger(__name__)

async def get_all_users_count(session: AsyncSession) -> int:
    """Получает общее количество пользователей в БД"""
    try:
        result = await session.execute(select(func.count(User.user_id)))
        count = result.scalar()
        return count or 0
    except Exception as e:
        logger.error(f"Ошибка при получении количества пользователей: {e}")
        return 0

async def get_users_for_broadcast(session: AsyncSession, limit: int = 1000) -> List[Dict[str, Any]]:
    """Получает список пользователей для рассылки"""
    try:
        result = await session.execute(
            select(User.user_id, User.username, User.first_name, User.last_name)
            .where(User.user_id.isnot(None))
            .limit(limit)
        )
        users = []
        for row in result:
            users.append({
                "user_id": row.user_id,
                "username": row.username,
                "first_name": row.first_name,
                "last_name": row.last_name
            })
        return users
    except Exception as e:
        logger.error(f"Ошибка при получении пользователей для рассылки: {e}")
        return []

async def send_broadcast_message(bot: Bot, user_id: int, message_text: str, username: str = None) -> Dict[str, Any]:
    """Отправляет сообщение пользователю и возвращает результат"""
    try:
        await bot.send_message(chat_id=user_id, text=message_text)
        logger.info(f"✅ Сообщение отправлено пользователю {user_id} (@{username or 'без username'})")
        return {"success": True, "user_id": user_id, "username": username}
    except Exception as e:
        logger.error(f"❌ Ошибка отправки сообщения пользователю {user_id} (@{username or 'без username'}): {e}")
        return {"success": False, "user_id": user_id, "username": username, "error": str(e)}

async def broadcast_to_all_users(bot: Bot, message_text: str, max_users: int = 100) -> Dict[str, Any]:
    """Отправляет рассылку всем пользователям"""
    try:
        async with get_session() as session:
            users = await get_users_for_broadcast(session, max_users)
            
            if not users:
                return {"success": False, "message": "Нет пользователей для рассылки"}
            
            logger.info(f"🚀 Начинаем рассылку для {len(users)} пользователей")
            
            success_count = 0
            error_count = 0
            
            for user in users:
                result = await send_broadcast_message(
                    bot, 
                    user["user_id"], 
                    message_text, 
                    user["username"]
                )
                
                if result["success"]:
                    success_count += 1
                else:
                    error_count += 1
                
                # Добавляем задержку между отправками для избежания rate limit
                await asyncio.sleep(0.1)
            
            logger.info(f"📊 Рассылка завершена: успешно {success_count}, ошибок {error_count}")
            
            return {
                "success": True,
                "total_users": len(users),
                "success_count": success_count,
                "error_count": error_count,
                "message": f"Рассылка завершена: {success_count}/{len(users)} сообщений отправлено"
            }
            
    except Exception as e:
        logger.error(f"Ошибка при рассылке: {e}")
        return {"success": False, "message": f"Ошибка рассылки: {e}"}

async def is_authorized_user(user_id: int) -> bool:
    """Проверяет, авторизован ли пользователь для рассылок"""
    # Разрешаем только @texas_dev
    authorized_users = [619924982]  # ID пользователя @texas_dev
    
    return user_id in authorized_users

