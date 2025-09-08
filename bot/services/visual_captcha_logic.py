# services/visual_captcha_logic.py
import asyncio
import random
import logging
import re
from io import BytesIO
from typing import Dict, Optional, Any, Tuple

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.utils.deep_linking import create_start_link
from PIL import Image, ImageDraw, ImageFont

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.services.redis_conn import redis
from bot.database.models import CaptchaSettings, User
from datetime import datetime

logger = logging.getLogger(__name__)


async def generate_visual_captcha() -> Tuple[str, BufferedInputFile]:
    """Генерация визуальной капчи (число, текст или простая математика)."""
    width, height = 1000, 400  # Очень большой размер для крупных символов
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    d = ImageDraw.Draw(img)

    # Создаем крупный шрифт программно
    try:
        # Пробуем загрузить системные шрифты
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 
            "/System/Library/Fonts/Arial.ttf",  # macOS
            "arial.ttf",
            "Arial.ttf"
        ]
        
        fonts = []
        for path in font_paths:
            try:
                fonts = [ImageFont.truetype(path, size) for size in (100, 110, 120, 130)]  # Очень крупные шрифты
                logger.info(f"Успешно загружен шрифт: {path}")
                break
            except (IOError, OSError):
                continue
        
        # Если шрифты не найдены, создаем крупный шрифт программно
        if not fonts:
            # Создаем шрифт с большим размером программно
            fonts = []
            for size in (80, 90, 100, 110):
                try:
                    # Создаем шрифт с указанным размером
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
                    fonts.append(font)
                except:
                    try:
                        # Пробуем другой путь
                        font = ImageFont.truetype("/System/Library/Fonts/Arial.ttf", size)
                        fonts.append(font)
                    except:
                        # В крайнем случае используем default, но с масштабированием
                        font = ImageFont.load_default()
                        fonts.append(font)
            logger.warning("Создан программный шрифт - символы должны быть крупными")
            
    except Exception as e:
        logger.error(f"Ошибка создания шрифта: {e}")
        fonts = [ImageFont.load_default()]

    captcha_type = random.choice(["number", "text", "math"])

    if captcha_type == "number":
        answer = str(random.randint(1, 50))
        text_to_draw = answer
    elif captcha_type == "text":
        chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        answer = "".join(random.choice(chars) for _ in range(4))
        text_to_draw = answer
    else:  # math
        a = random.randint(1, 20)
        b = random.randint(1, 10)
        op = random.choice(["+", "-", "*"])
        if op == "+":
            answer = str(a + b)
            text_to_draw = f"{a}+{b}"
        elif op == "-":
            if a < b:
                a, b = b, a
            answer = str(a - b)
            text_to_draw = f"{a}-{b}"
        else:
            a = random.randint(1, 10)
            b = random.randint(1, 9)
            answer = str(a * b)
            text_to_draw = f"{a}×{b}"

    # Фоновые линии
    for _ in range(8):
        x1, y1 = random.randint(0, width), random.randint(0, height)
        x2, y2 = random.randint(0, width), random.randint(0, height)
        d.line([(x1, y1), (x2, y2)],
               fill=(random.randint(160, 200), random.randint(160, 200), random.randint(160, 200)),
               width=1)

    # Точечный шум
    for _ in range(500):
        d.point((random.randint(0, width), random.randint(0, height)),
                fill=(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)))

    # Посимвольный вывод с поворотами
    spacing = width // (len(text_to_draw) + 2)
    x_offset = spacing
    for ch in text_to_draw:
        angle = random.randint(-15, 15)
        font = random.choice(fonts)

        char_img = Image.new("RGBA", (200, 240), (255, 255, 255, 0))  # Очень большой размер символов
        char_draw = ImageDraw.Draw(char_img)
        color = (random.randint(0, 60), random.randint(0, 60), random.randint(0, 60))  # Очень темный цвет

        # Рисуем текст с большим отступом
        char_draw.text((20, 20), ch, font=font, fill=color)
        
        # Если шрифт мелкий, масштабируем изображение
        if font == ImageFont.load_default():
            # Масштабируем в 3 раза для читаемости
            char_img = char_img.resize((600, 720), Image.Resampling.LANCZOS)
        
        rotated = char_img.rotate(angle, expand=1, fillcolor=(255, 255, 255, 0))
        y_pos = random.randint(height // 3, height // 2)  # Лучшее позиционирование
        img.paste(rotated, (x_offset, y_pos), rotated)
        x_offset += spacing + random.randint(-10, 10)

    # Искажающие линии поверх текста (менее агрессивные)
    for _ in range(2):  # Меньше линий для лучшей читаемости
        start_y = random.randint(height // 3, 2 * height // 3)
        end_y = random.randint(height // 3, 2 * height // 3)
        d.line([(0, start_y), (width, end_y)],
               fill=(random.randint(200, 220), random.randint(200, 220), random.randint(200, 220)),  # Более светлые линии
               width=1)  # Тонкие линии

    # В байты
    img_byte_arr = BytesIO()
    img.save(img_byte_arr, format="PNG")
    img_byte_arr.seek(0)
    file = BufferedInputFile(img_byte_arr.getvalue(), filename="captcha.png")
    return answer, file


async def create_group_invite_link(bot: Bot, group_name: str) -> str:
    """Создаёт start deep-link для капчи (на саму группу это НЕ ссылка)."""
    return await create_start_link(bot, f"deep_link_{group_name}")


async def delete_message_after_delay(bot: Bot, chat_id: int, message_id: int, delay: float):
    """Удаляет сообщение через delay секунд."""
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        if "message to delete not found" in str(e).lower():
            return
        logger.error(f"Не удалось удалить сообщение {message_id}: {e}")


async def send_captcha_reminder(bot: Bot, chat_id: int, user_id: int, group_name: str):
    """Отправляет напоминание о необходимости решить капчу через 2-3 минуты."""
    try:
        # Получаем информацию о группе для красивого сообщения
        group_display_name = group_name.replace("_", " ").title()
        group_link = None
        
        if group_name.startswith("private_"):
            try:
                chat_id_for_name = int(group_name.replace("private_", ""))
                chat = await bot.get_chat(chat_id_for_name)
                group_display_name = chat.title
                # Для приватных групп создаем инвайт-ссылку
                invite = await bot.create_chat_invite_link(
                    chat_id=chat_id_for_name,
                    name=f"Reminder for user {user_id}",
                    creates_join_request=False,
                )
                group_link = invite.invite_link
            except Exception:
                pass
        elif group_name.startswith("-") and group_name[1:].isdigit():
            try:
                chat_id_for_name = int(group_name)
                chat = await bot.get_chat(chat_id_for_name)
                group_display_name = chat.title
                if chat.username:
                    group_link = f"https://t.me/{chat.username}"
                else:
                    # Для приватных групп создаем инвайт-ссылку
                    invite = await bot.create_chat_invite_link(
                        chat_id=chat_id_for_name,
                        name=f"Reminder for user {user_id}",
                        creates_join_request=False,
                    )
                    group_link = invite.invite_link
            except Exception:
                pass
        else:
            # Публичная группа по username
            group_link = f"https://t.me/{group_name}"
        
        # Формируем текст с ссылкой на группу
        if group_link:
            reminder_text = (
                f"⏰ <b>Напоминание о капче</b>\n\n"
                f"Вы не решили капчу для вступления в группу <a href='{group_link}'>{group_display_name}</a>.\n"
                f"Пожалуйста, решите капчу в течение следующих 2 минут, иначе ваш запрос будет отклонен."
            )
        else:
            reminder_text = (
                f"⏰ <b>Напоминание о капче</b>\n\n"
                f"Вы не решили капчу для вступления в группу <b>{group_display_name}</b>.\n"
                f"Пожалуйста, решите капчу в течение следующих 2 минут, иначе ваш запрос будет отклонен."
            )
        
        reminder_msg = await bot.send_message(
            chat_id=user_id,
            text=reminder_text,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        
        # Удаляем напоминание через 2 минуты
        asyncio.create_task(delete_message_after_delay(bot, user_id, reminder_msg.message_id, 120))
        
        logger.info(f"📨 Отправлено напоминание о капче пользователю {user_id}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке напоминания о капче: {e}")


async def schedule_captcha_reminder(bot: Bot, user_id: int, group_name: str, delay_minutes: int = 2):
    """Планирует отправку напоминания о капче через указанное количество минут."""
    await asyncio.sleep(delay_minutes * 60)  # Конвертируем минуты в секунды
    
    # Проверяем, что пользователь все еще не решил капчу
    captcha_data = await get_captcha_data(user_id)
    if captcha_data and captcha_data["group_name"] == group_name:
        await send_captcha_reminder(bot, user_id, user_id, group_name)


async def save_join_request(user_id: int, chat_id: int, group_id: str) -> None:
    """Сохраняет информацию о join-request на 1 час."""
    await redis.setex(f"join_request:{user_id}:{group_id}", 3600, str(chat_id))


async def create_deeplink_for_captcha(bot: Bot, group_id: str) -> str:
    """Создаёт /start deep-link для визуальной капчи."""
    deep_link = await create_start_link(bot, f"deep_link_{group_id}")
    logger.info(f"Создан deep link: {deep_link} для группы {group_id}")
    return deep_link


async def get_captcha_keyboard(deep_link: str) -> InlineKeyboardMarkup:
    """Кнопка «Пройти капчу» (открывает /start с deep link)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🧩 Пройти капчу", url=deep_link)]]
    )


async def get_group_settings_keyboard(group_id: str, captcha_enabled: str) -> InlineKeyboardMarkup:
    """Клавиатура для включения/выключения визуальной капчи в группе."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Включено" if captcha_enabled == "1" else "Включить",
                    callback_data=f"set_visual_captcha:{group_id}:1",
                ),
                InlineKeyboardButton(
                    text="✅ Выключено" if captcha_enabled == "0" else "Выключить",
                    callback_data=f"set_visual_captcha:{group_id}:0",
                ),
            ],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="redirect:captcha_settings")],
        ]
    )


async def get_group_join_keyboard(group_link: str, group_display_name: Optional[str] = None) -> InlineKeyboardMarkup:
    """
    Создает кнопку для присоединения к группе.
    Использует только https://t.me/ ссылки для надежности.
    """
    title = f"Присоединиться в «{group_display_name}»" if group_display_name else "Присоединиться в группу"
    
    # Используем только обычные t.me ссылки
    if group_link and group_link.startswith("https://t.me/"):
        url = group_link
    else:
        # Fallback - если ссылка некорректная
        url = "https://t.me/"
        title = "Повторите запрос на вступление в группу"
    
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=title, url=url)]
        ]
    )


async def save_captcha_data(user_id: int, captcha_answer: str, group_name: str, attempts: int = 0) -> None:
    """Сохраняет данные капчи (на 5 минут)."""
    await redis.setex(f"captcha:{user_id}", 300, f"{captcha_answer}:{group_name}:{attempts}")


async def get_captcha_data(user_id: int) -> Optional[Dict[str, Any]]:
    """Читает данные капчи из Redis."""
    raw = await redis.get(f"captcha:{user_id}")
    if not raw:
        return None
    parts = raw.split(":")
    if len(parts) < 3:
        return None
    return {"captcha_answer": parts[0], "group_name": parts[1], "attempts": int(parts[2])}


async def set_rate_limit(user_id: int, seconds: int = 180) -> None:
    """Ставит рейтлимит на повторы капчи."""
    await redis.setex(f"rate_limit:{user_id}", seconds, str(seconds))


async def check_rate_limit(user_id: int) -> bool:
    """True, если есть активный рейтлимит."""
    return bool(await redis.exists(f"rate_limit:{user_id}"))


async def get_rate_limit_time_left(user_id: int) -> int:
    """Сколько секунд осталось у рейтлимита (0, если нет)."""
    ttl = await redis.ttl(f"rate_limit:{user_id}")
    return max(0, ttl)


async def check_admin_rights(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Проверка прав администратора в группе."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except Exception as e:
        logger.error(f"Ошибка при проверке прав администратора: {e}")
        return False


async def set_visual_captcha_status(chat_id: int, enabled: bool) -> None:
    """Включает/выключает визуальную капчу (флаг в Redis)."""
    await redis.set(f"visual_captcha_enabled:{chat_id}", "1" if enabled else "0")


async def get_visual_captcha_status(chat_id: int) -> bool:
    """Статус визуальной капчи из Redis."""
    return (await redis.get(f"visual_captcha_enabled:{chat_id}")) == "1"


async def approve_chat_join_request(bot: Bot, chat_id: int, user_id: int) -> Dict[str, Any]:
    """
    Одобряет запрос на вступление. Возвращает:
    {
      "success": bool,
      "message": str,
      "group_link": Optional[str]  # ссылка, по которой можно войти без повторного apply
    }
    Для приватных чатов создаём инвайт с creates_join_request=False.
    Для публичных с username — используем https://t.me/<username>.
    """
    result: Dict[str, Any] = {"success": False, "message": "", "group_link": None}

    try:
        logger.info(f"Пытаемся одобрить запрос на вступление: chat_id={chat_id}, user_id={user_id}")
        
        # Увеличиваем задержку для избежания rate limit
        await asyncio.sleep(5.0)  # Увеличиваем до 5 секунд
        
        # Сначала получаем информацию о группе
        chat = await bot.get_chat(chat_id)
        logger.info(f"Информация о группе: title={chat.title}, username={chat.username}, type={chat.type}")
        
        # Пытаемся одобрить запрос с повторными попытками
        max_retries = 3
        for attempt in range(max_retries):
            try:
                await bot.approve_chat_join_request(chat_id=chat_id, user_id=user_id)
                result["success"] = True
                result["message"] = "Капча пройдена успешно! Ваш запрос на вступление в группу одобрен."
                logger.info(f"✅ Запрос на вступление успешно одобрен для пользователя {user_id}")
                break
            except Exception as e:
                if "429" in str(e) and attempt < max_retries - 1:
                    # Используем retry_after из ошибки, если есть, иначе увеличиваем задержку
                    if "retry_after" in str(e):
                        import re
                        match = re.search(r'"retry_after":(\d+)', str(e))
                        if match:
                            retry_after = int(match.group(1)) + 5  # Добавляем 5 секунд к указанному времени
                        else:
                            retry_after = 20 + attempt * 10  # 20с, 30с, 40с
                    else:
                        retry_after = 20 + attempt * 10  # 20с, 30с, 40с
                    
                    logger.warning(f"Rate limit при одобрении запроса, попытка {attempt + 1}/{max_retries}, ждем {retry_after}с")
                    await asyncio.sleep(retry_after)
                    continue
                else:
                    raise e

        # Создаем ссылку на группу
        if result["success"]:
            if chat.username:
                # Публичная группа — можно зайти по username
                result["group_link"] = f"https://t.me/{chat.username}"
                logger.info(f"Ссылка на публичную группу: {result['group_link']}")
            else:
                # Приватная — делаем инвайт, который НЕ создаёт join request повторно
                # Добавляем задержку перед созданием инвайта
                await asyncio.sleep(5.0)
                invite = await bot.create_chat_invite_link(
                    chat_id=chat_id,
                    name=f"Invite for user {user_id}",
                    creates_join_request=False,
                )
                result["group_link"] = invite.invite_link
                logger.info(f"Ссылка-инвайт для приватной группы: {result['group_link']}")

    except Exception as e:
        logger.error(f"Ошибка approve_chat_join_request: {e}")
        result["message"] = f"Капча пройдена, но не удалось автоматически добавить в группу: {e}"

        # Даже при ошибке попробуем отдать ссылку
        try:
            await asyncio.sleep(0.5)  # Задержка перед повторной попыткой
            chat = await bot.get_chat(chat_id)
            if chat.username:
                result["group_link"] = f"https://t.me/{chat.username}"
            else:
                invite = await bot.create_chat_invite_link(
                    chat_id=chat_id,
                    name=f"Invite for user {user_id}",
                    creates_join_request=False,
                )
                result["group_link"] = invite.invite_link
        except Exception as e2:
            logger.error(f"Ошибка резервного создания ссылки: {e2}")

    return result


async def get_group_display_name(group_name: str) -> str:
    """Красивое отображаемое имя группы (из Redis или формат из имени)."""
    cached = await redis.get(f"group_display_name:{group_name}")
    if cached:
        return str(cached)
    return group_name.replace("_", " ").title()


async def save_user_to_db(session: AsyncSession, user_data: dict) -> None:
    """Сохраняет/обновляет пользователя в БД (для рассылок и аналитики)."""
    try:
        result = await session.execute(select(User).where(User.user_id == user_data["user_id"]))
        existing = result.scalar_one_or_none()

        if not existing:
            new_user = User(
                user_id=user_data["user_id"],
                username=user_data.get("username"),
                first_name=user_data.get("first_name"),
                last_name=user_data.get("last_name"),
                language_code=user_data.get("language_code", "ru"),
                is_bot=user_data.get("is_bot", False),
                is_premium=user_data.get("is_premium", False),
                added_to_attachment_menu=user_data.get("added_to_attachment_menu", False),
                can_join_groups=user_data.get("can_join_groups", True),
                can_read_all_group_messages=user_data.get("can_read_all_group_messages", False),
                supports_inline_queries=user_data.get("supports_inline_queries", False),
                can_connect_to_business=user_data.get("can_connect_to_business", False),
                has_main_web_app=user_data.get("has_main_web_app", False),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            session.add(new_user)
            await session.commit()
            logger.info(f"✅ Пользователь {user_data['user_id']} сохранён в БД")
        else:
            existing.username = user_data.get("username")
            existing.first_name = user_data.get("first_name")
            existing.last_name = user_data.get("last_name")
            existing.updated_at = datetime.utcnow()
            await session.commit()
            logger.info(f"♻️ Пользователь {user_data['user_id']} обновлён в БД")
    except Exception as e:
        logger.error(f"❌ Ошибка при сохранении пользователя: {e}")
        await session.rollback()


async def get_group_link_from_redis_or_create(bot: Bot, group_name: str) -> Optional[str]:
    """
    Возвращает рабочую ссылку на группу:
    - из кэша Redis,
    - для приватных — создаёт инвайт с creates_join_request=False,
    - для публичных — https://t.me/<username>.
    Возвращает None, если создать ссылку не удалось.
    """
    try:
        cached = await redis.get(f"group_link:{group_name}")
        if cached:
            logger.info(f"🔗 Используем кэшированную ссылку для {group_name}: {cached}")
            return cached

        logger.info(f"🔗 Создаем новую ссылку для группы: {group_name}")
        group_link: Optional[str] = None

        # Определяем chat_id для всех типов групп
        chat_id = None
        if group_name.startswith("private_"):
            chat_id = int(group_name.replace("private_", ""))
        elif group_name.startswith("-") and group_name[1:].isdigit():
            chat_id = int(group_name)
        else:
            # Публичная группа по username
            group_link = f"https://t.me/{group_name}"
            await redis.setex(f"group_link:{group_name}", 3600, group_link)
            return group_link

        # Для приватных групп и числовых ID
        if chat_id:
            try:
                chat = await bot.get_chat(chat_id)
                if chat.username:
                    group_link = f"https://t.me/{chat.username}"
                else:
                    # Добавляем задержку перед созданием инвайта
                    await asyncio.sleep(5.0)
                    invite = await bot.create_chat_invite_link(
                        chat_id=chat_id,
                        name=f"Invite for {group_name}",
                        creates_join_request=False,
                    )
                    group_link = invite.invite_link
            except Exception as e:
                logger.error(f"Ошибка при получении ссылки для группы {chat_id}: {e}")
                # Повторная попытка: ещё раз создать инвайт
                try:
                    await asyncio.sleep(10.0)  # Увеличиваем задержку до 10 секунд
                    invite = await bot.create_chat_invite_link(
                        chat_id=chat_id,
                        name=f"Invite for {group_name}",
                        creates_join_request=False,
                    )
                    group_link = invite.invite_link
                except Exception as e2:
                    logger.error(f"Повторная ошибка создания инвайта: {e2}")
                    group_link = None

        if group_link:
            await redis.setex(f"group_link:{group_name}", 3600, group_link)
            logger.info(f"🔗 Сохранена ссылка для {group_name}: {group_link}")
        else:
            logger.error(f"❌ Не удалось создать ссылку для группы {group_name}")

        return group_link
    except Exception as e:
        logger.error(f"Ошибка при получении ссылки на группу {group_name}: {e}")
        return None


async def is_visual_captcha_enabled(session: AsyncSession, chat_id: int) -> bool:
    """Статус визуальной капчи из БД (на случай, если используете таблицу CaptchaSettings)."""
    try:
        result = await session.execute(select(CaptchaSettings).where(CaptchaSettings.group_id == chat_id))
        settings = result.scalar_one_or_none()
        is_enabled = settings.is_visual_enabled if settings else False
        logger.info(
            f"visual_captcha_logic: Проверка визуальной капчи для группы {chat_id}: "
            f"{'включена' if is_enabled else 'выключена'}"
        )
        return is_enabled
    except Exception as e:
        logger.error(f"Ошибка при проверке статуса визуальной капчи: {e}")
        return False
