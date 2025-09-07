# handlers/captcha/visual_captcha_handler.py
import asyncio
import logging
import traceback
from typing import Dict, Optional, Any

from aiogram import Bot, Router, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, ChatJoinRequest

from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.redis_conn import redis
from bot.services.visual_captcha_logic import (
    generate_visual_captcha,
    delete_message_after_delay,
    save_join_request,
    create_deeplink_for_captcha,
    get_captcha_keyboard,
    get_group_settings_keyboard,
    get_group_join_keyboard,
    save_captcha_data,
    get_captcha_data,
    set_rate_limit,
    check_rate_limit,
    get_rate_limit_time_left,
    check_admin_rights,
    set_visual_captcha_status,
    get_visual_captcha_status,
    approve_chat_join_request,
    get_group_display_name,
    save_user_to_db,
    get_group_link_from_redis_or_create,
    schedule_captcha_reminder,
)
from bot.services.scammer_tracker_logic import track_captcha_failure
from bot.database.queries import get_group_by_name
from bot.services.bot_activity_journal.bot_activity_journal_logic import log_join_request

logger = logging.getLogger(__name__)

visual_captcha_handler_router = Router()


class CaptchaStates(StatesGroup):
    waiting_for_captcha = State()


@visual_captcha_handler_router.chat_join_request()
async def handle_join_request(join_request: ChatJoinRequest):
    """
    Обрабатывает запрос на вступление в группу:
    - Если включена визуальная капча, отправляет пользователю deep-link на прохождение капчи.
    - Не даём «битую» ссылку для приватных групп до прохождения капчи.
    """
    user = join_request.from_user
    chat = join_request.chat
    user_id = user.id
    chat_id = chat.id

    # Проверяем, активна ли визуальная капча
    captcha_enabled = await get_visual_captcha_status(chat_id)
    if not captcha_enabled:
        logger.info(f"⛔ Визуальная капча не активирована в группе {chat_id}, выходим")
        return

    # Идентификатор группы в deep-link: username или private_<id>
    group_id = chat.username or f"private_{chat.id}"

    # Сохраняем запрос на вступление (для последующего approve)
    await save_join_request(user_id, chat_id, group_id)

    # Создаём start deep-link на /start для прохождения капчи
    deep_link = await create_deeplink_for_captcha(join_request.bot, group_id)

    # Кнопка «Пройти капчу»
    keyboard = await get_captcha_keyboard(deep_link)

    try:
        # Удаляем прошлые сообщения бота пользователю (если есть)
        user_messages = await redis.get(f"user_messages:{user_id}")
        if user_messages:
            message_ids = user_messages.split(",")
            for msg_id in message_ids:
                try:
                    await join_request.bot.delete_message(chat_id=user_id, message_id=int(msg_id))
                except Exception as e:
                    if "message to delete not found" not in str(e).lower():
                        logger.error(f"Ошибка при удалении сообщения {msg_id}: {str(e)}")

        # Формируем текст (для приватной группы — без ссылки)
        group_title = (
            chat.title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            if chat.title else "группа"
        )

        if chat.username:
            group_link = f"https://t.me/{chat.username}"
            message_text = (
                f"Для вступления в группу <a href='{group_link}'>{group_title}</a> необходимо пройти проверку.\n"
                f"Нажмите на кнопку ниже:"
            )
        else:
            message_text = (
                f"Для вступления в группу <b>{group_title}</b> необходимо пройти проверку.\n"
                f"Нажмите на кнопку ниже:"
            )

        # Отправляем сообщение пользователю
        msg = await join_request.bot.send_message(
            user_id,
            message_text,
            reply_markup=keyboard,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        logger.info(f"✅ Отправлено сообщение пользователю {user_id} о прохождении капчи")

        # Логируем запрос на вступление в журнал действий
        await log_join_request(
            bot=join_request.bot,
            user=user,
            chat=chat,
            captcha_status="КАПЧА_ОТПРАВЛЕНА",
            saved_to_db=False
        )

        # Сохраняем ID сообщения на час (для последующего удаления)
        await redis.setex(f"user_messages:{user_id}", 3600, str(msg.message_id))

    except Exception as e:
        logger.error(f"❌ Ошибка при обработке запроса на вступление: {e}")
        logger.debug(traceback.format_exc())


@visual_captcha_handler_router.message(CommandStart(deep_link=True))
async def process_visual_captcha_deep_link(message: Message, bot: Bot, state: FSMContext, session: AsyncSession):
    """
    Обработка /start с deep_link вида deep_link_<group_id_or_username>.
    Генерация и показ визуальной капчи.
    """
    try:
        # Сохраняем/обновляем пользователя в БД
        user_data = {
            "user_id": message.from_user.id,
            "username": message.from_user.username,
            "first_name": message.from_user.first_name,
            "last_name": message.from_user.last_name,
            "language_code": message.from_user.language_code,
            "is_bot": message.from_user.is_bot,
            "is_premium": message.from_user.is_premium,
            "added_to_attachment_menu": message.from_user.added_to_attachment_menu,
            "can_join_groups": message.from_user.can_join_groups,
            "can_read_all_group_messages": message.from_user.can_read_all_group_messages,
            "supports_inline_queries": message.from_user.supports_inline_queries,
            "can_connect_to_business": message.from_user.can_connect_to_business,
            "has_main_web_app": message.from_user.has_main_web_app,
        }
        await save_user_to_db(session, user_data)

        # Извлекаем deep_link параметры
        deep_link_args = message.text.split()[1] if len(message.text.split()) > 1 else None
        logger.info(f"Активирован deep link с параметрами: {deep_link_args}")

        if not deep_link_args or not deep_link_args.startswith("deep_link_"):
            await message.answer("Неверная ссылка. Пожалуйста, используйте корректную ссылку для вступления в группу.")
            logger.warning(f"Неверный deep link: {deep_link_args}")
            return

        # Чистим предыдущие сообщения капчи
        stored = await state.get_data()
        prev_ids = stored.get("message_ids", [])
        for mid in prev_ids:
            try:
                await bot.delete_message(chat_id=message.chat.id, message_id=mid)
            except Exception as e:
                if "message to delete not found" not in str(e).lower():
                    logger.error(f"Ошибка удаления сообщения {mid}: {e}")

        # Также чистим, если ID были записаны в Redis
        user_messages = await redis.get(f"user_messages:{message.from_user.id}")
        if user_messages:
            try:
                for mid in user_messages.split(","):
                    try:
                        await bot.delete_message(chat_id=message.chat.id, message_id=int(mid))
                    except Exception as e:
                        if "message to delete not found" not in str(e).lower():
                            logger.error(f"Ошибка при удалении сообщения {mid}: {e}")
                await redis.delete(f"user_messages:{message.from_user.id}")
            except Exception as e:
                logger.error(f"Ошибка при удалении сообщений из Redis: {e}")

        # Имя/ID группы из deep-link
        group_name = deep_link_args.replace("deep_link_", "")
        logger.info(f"Extracted group name from deep-link: {group_name}")

        # Генерируем капчу
        captcha_answer, captcha_image = await generate_visual_captcha()
        logger.info(f"Сгенерирована капча, ответ: {captcha_answer}")

        # Пишем в FSM + Redis
        await state.update_data(captcha_answer=captcha_answer, group_name=group_name, attempts=0, message_ids=[])
        await save_captcha_data(message.from_user.id, captcha_answer, group_name, 0)

        # Отправляем изображение-капчу
        try:
            captcha_msg = await message.answer_photo(
                photo=captcha_image,
                caption=(
                    "Пожалуйста, введите символы, которые вы видите на изображении, "
                    "или решите математическое выражение, чтобы продолжить."
                ),
            )
            message_ids = [captcha_msg.message_id]
            await state.update_data(message_ids=message_ids)

            # Удалим капчу через 5 минут (чтобы дать время на напоминание)
            asyncio.create_task(delete_message_after_delay(bot, message.chat.id, captcha_msg.message_id, 300))
            
            # Планируем напоминание через 2 минуты
            asyncio.create_task(schedule_captcha_reminder(bot, message.from_user.id, group_name, 2))
            
            await state.set_state(CaptchaStates.waiting_for_captcha)

        except Exception as network_error:
            logger.error(f"❌ Ошибка сети при отправке капчи: {network_error}")
            # Фолбэк — текстовый код
            try:
                fallback_msg = await message.answer(
                    "⚠️ Не удалось отправить изображение капчи.\n\n"
                    f"🔑 Ваш код для входа в группу: **{captcha_answer}**\n"
                    "Введите этот код для подтверждения:",
                    parse_mode="Markdown",
                )
                await state.update_data(message_ids=[fallback_msg.message_id])
                await state.set_state(CaptchaStates.waiting_for_captcha)
                asyncio.create_task(delete_message_after_delay(bot, message.chat.id, fallback_msg.message_id, 300))
                
                # Планируем напоминание через 2 минуты
                asyncio.create_task(schedule_captcha_reminder(bot, message.from_user.id, group_name, 2))
            except Exception as fallback_error:
                logger.error(f"❌ Критическая ошибка при отправке fallback-сообщения: {fallback_error}")
                await message.answer("Произошла критическая ошибка. Попробуйте позже.")
                await state.clear()

    except Exception as e:
        logger.error(f"❌ Критическая ошибка в process_visual_captcha_deep_link: {e}")
        logger.debug(traceback.format_exc())
        try:
            await message.answer("Произошла ошибка при обработке запроса. Попробуйте позже.")
        except Exception:
            pass
        await state.clear()


@visual_captcha_handler_router.message(CaptchaStates.waiting_for_captcha)
async def process_captcha_answer(message: Message, state: FSMContext, session: AsyncSession):
    """
    Проверяет ответ на капчу. При успехе:
    - approve join request (если был),
    - отдаёт кнопку для открытия группы (с приоритетом tg:// ссылок),
    - показывает реальное название группы на кнопке.
    """
    user_id = message.from_user.id

    try:
        # Обновим юзера в БД (для рассылок и т.п.)
        await save_user_to_db(
            session,
            {
                "user_id": message.from_user.id,
                "username": message.from_user.username,
                "first_name": message.from_user.first_name,
                "last_name": message.from_user.last_name,
                "language_code": message.from_user.language_code,
                "is_bot": message.from_user.is_bot,
                "is_premium": message.from_user.is_premium,
            },
        )

        # Рейтлимит
        if await check_rate_limit(user_id):
            time_left = await get_rate_limit_time_left(user_id)
            limit_msg = await message.answer(f"Пожалуйста, подождите {time_left} секунд перед следующей попыткой.")
            asyncio.create_task(delete_message_after_delay(message.bot, message.chat.id, limit_msg.message_id, 5))
            return

        # Достаём данные из FSM (или Redis)
        data = await state.get_data()
        captcha_answer = data.get("captcha_answer")
        group_name = data.get("group_name")
        attempts = data.get("attempts", 0)
        message_ids = data.get("message_ids", [])

        # Добавим текущее сообщение в список на удаление
        message_ids.append(message.message_id)
        await state.update_data(message_ids=message_ids)

        if not captcha_answer or not group_name:
            captcha_data = await get_captcha_data(message.from_user.id)
            if captcha_data:
                captcha_answer = captcha_data["captcha_answer"]
                group_name = captcha_data["group_name"]
                attempts = captcha_data["attempts"]
            else:
                no_captcha_msg = await message.answer("Время сессии истекло. Пожалуйста, начните процесс заново.")
                message_ids.append(no_captcha_msg.message_id)
                await state.update_data(message_ids=message_ids)
                asyncio.create_task(delete_message_after_delay(message.bot, message.chat.id, no_captcha_msg.message_id, 5))
                await state.clear()
                return

        # Проверка количества попыток
        if attempts >= 3:
            too_many = await message.answer("Превышено количество попыток. Повторите через 60 секунд.")
            message_ids.append(too_many.message_id)
            await state.update_data(message_ids=message_ids)
            asyncio.create_task(delete_message_after_delay(message.bot, message.chat.id, too_many.message_id, 5))

            await redis.delete(f"captcha:{message.from_user.id}")
            await set_rate_limit(message.from_user.id, 60)
            time_left = await get_rate_limit_time_left(message.from_user.id)
            await message.answer(f"Пожалуйста, подождите {time_left} секунд и начните заново.")
            await state.clear()
            return

        # Сверяем ответ
        user_answer = (message.text or "").strip().upper()
        if user_answer == str(captcha_answer).upper():
            # Капча решена
            await redis.delete(f"captcha:{message.from_user.id}")

            # Удалим все сообщения через 5 секунд
            for mid in message_ids:
                asyncio.create_task(delete_message_after_delay(message.bot, message.chat.id, mid, 5))

            # Определяем chat_id для approve
            chat_id: Optional[int] = None
            if group_name.startswith("private_"):
                chat_id = int(group_name.replace("private_", ""))
            else:
                # Проверяем, является ли group_name числовым ID группы
                try:
                    # Если group_name это числовой ID группы (начинается с -)
                    if group_name.startswith("-") and group_name[1:].isdigit():
                        chat_id = int(group_name)
                        logger.info(f"Определен chat_id из числового ID: {chat_id}")
                    else:
                        # Пытаемся найти в Redis по оригинальному group_name
                        if await redis.exists(f"join_request:{message.from_user.id}:{group_name}"):
                            val = await redis.get(f"join_request:{message.from_user.id}:{group_name}")
                            chat_id = int(val)
                            logger.info(f"Найден chat_id в Redis: {chat_id}")
                except ValueError:
                    logger.error(f"Не удалось преобразовать group_name в chat_id: {group_name}")

            if chat_id:
                # Пытаемся одобрить запрос
                result = await approve_chat_join_request(message.bot, chat_id, message.from_user.id)

                if result["success"]:
                    # Устанавливаем флаг, что пользователь прошел капчу
                    await redis.setex(f"captcha_passed:{message.from_user.id}:{chat_id}", 3600, "1")
                    logger.info(f"✅ Пользователь {message.from_user.id} прошел капчу для группы {chat_id}")
                    
                    # Получаем реальное название группы
                    try:
                        chat = await message.bot.get_chat(chat_id)
                        group_display_name = chat.title
                        logger.info(f"Получено название группы: {group_display_name}")
                    except Exception as e:
                        logger.error(f"Ошибка при получении названия группы: {e}")
                        group_display_name = group_name.replace("_", " ").title()

                    keyboard = await get_group_join_keyboard(result["group_link"], group_display_name)
                    await message.answer(result["message"], reply_markup=keyboard)
                else:
                    # Ошибка approve — показываем сообщение и (если есть) ссылку
                    await message.answer(result["message"])

                    if result["group_link"]:
                        try:
                            chat = await message.bot.get_chat(chat_id)
                            group_display_name = chat.title
                            logger.info(f"Получено название группы для fallback: {group_display_name}")
                        except Exception as e:
                            logger.error(f"Ошибка при получении названия группы для fallback: {e}")
                            group_display_name = group_name.replace("_", " ").title()

                        keyboard = await get_group_join_keyboard(result["group_link"], group_display_name)
                        await message.answer("Используйте эту кнопку для присоединения:", reply_markup=keyboard)

                logger.info(f"Одобрен/обработан запрос на вступление user={message.from_user.id} group={group_name}")
            else:
                # Запрос не найден — отдаём прямую ссылку
                if group_name.startswith("private_"):
                    # Для приватной группы без активного join_request — просим переотправить заявку
                    warn = await message.answer(
                        "Ваш запрос на вступление истёк. Пожалуйста, отправьте новый запрос на вступление в группу."
                    )
                    message_ids.append(warn.message_id)
                    await state.update_data(message_ids=message_ids)
                else:
                    group_info = await get_group_by_name(session, group_name)
                    if group_info:
                        group_link = f"https://t.me/{group_name}"
                        keyboard = await get_group_join_keyboard(group_link, group_info.title)
                        await message.answer(
                            f"Капча пройдена успешно! Используйте кнопку ниже, чтобы войти в «{group_info.title}»:",
                            reply_markup=keyboard,
                        )
                    else:
                        group_link = await get_group_link_from_redis_or_create(message.bot, group_name)
                        if not group_link:
                            await message.answer(
                                "Капча пройдена, но не удалось сгенерировать ссылку на группу. "
                                "Пожалуйста, отправьте запрос на вступление повторно."
                            )
                        else:
                            # Получаем реальное название группы
                            try:
                                if group_name.startswith("private_"):
                                    chat_id_for_name = int(group_name.replace("private_", ""))
                                    chat = await message.bot.get_chat(chat_id_for_name)
                                    display_name = chat.title
                                elif group_name.startswith("-") and group_name[1:].isdigit():
                                    # Если group_name это числовой ID группы
                                    chat = await message.bot.get_chat(int(group_name))
                                    display_name = chat.title
                                else:
                                    # Для публичных групп пытаемся получить chat_id из Redis
                                    chat_id_from_redis = await redis.get(f"join_request:{message.from_user.id}:{group_name}")
                                    if chat_id_from_redis:
                                        chat = await message.bot.get_chat(int(chat_id_from_redis))
                                        display_name = chat.title
                                    else:
                                        # Fallback - используем group_name как есть
                                        display_name = group_name.replace("_", " ").title()
                                logger.info(f"Получено название группы: {display_name}")
                            except Exception as e:
                                logger.error(f"Ошибка при получении названия группы: {e}")
                                display_name = group_name.replace("_", " ").title()
                            
                            keyboard = await get_group_join_keyboard(group_link, display_name)
                            await message.answer(
                                f"Капча пройдена успешно! Используйте кнопку ниже, чтобы войти в «{display_name}»:",
                                reply_markup=keyboard,
                            )

            await state.clear()
            return

        # Неверный ответ
        attempts += 1
        await state.update_data(attempts=attempts)

        # Логируем неуспех (если есть chat_id)
        try:
            chat_id_for_log = 0
            if group_name.startswith("private_"):
                chat_id_for_log = int(group_name.replace("private_", ""))
            elif group_name.startswith("-") and group_name[1:].isdigit():
                # Если group_name это числовой ID группы
                chat_id_for_log = int(group_name)
            else:
                # Для публичных групп пытаемся получить chat_id из Redis
                chat_id_from_redis = await redis.get(f"join_request:{message.from_user.id}:{group_name}")
                if chat_id_from_redis:
                    chat_id_for_log = int(chat_id_from_redis)
            
            # Только если у нас есть валидный chat_id
            if chat_id_for_log != 0:
                await track_captcha_failure(
                    session,
                    message.from_user.id,
                    chat_id_for_log,
                    message.from_user.username,
                    message.from_user.first_name,
                    message.from_user.last_name,
                )
        except Exception as e:
            logger.error(f"Ошибка при отслеживании неудачной капчи: {e}")

        # Превышение попыток
        if attempts >= 3:
            if group_name.startswith("private_"):
                too_many_msg = await message.answer(
                    "Превышено количество попыток. Пожалуйста, начните процесс заново."
                )
            else:
                group_link = await get_group_link_from_redis_or_create(message.bot, group_name)
                if group_link:
                    # Получаем реальное название группы
                    try:
                        if group_name.startswith("private_"):
                            chat_id_for_name = int(group_name.replace("private_", ""))
                            chat = await message.bot.get_chat(chat_id_for_name)
                            group_title = chat.title
                        elif group_name.startswith("-") and group_name[1:].isdigit():
                            chat = await message.bot.get_chat(int(group_name))
                            group_title = chat.title
                        else:
                            group_title = group_name.replace("_", " ").title()
                    except Exception as e:
                        logger.error(f"Ошибка при получении названия группы для too_many: {e}")
                        group_title = group_name.replace("_", " ").title()
                    
                    too_many_msg = await message.answer(
                        "Превышено количество попыток. Пожалуйста, начните процесс заново.\n"
                        f"Отправьте запрос в группу: <a href='{group_link}'>{group_title}</a>",
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                else:
                    too_many_msg = await message.answer(
                        "Превышено количество попыток. Пожалуйста, начните процесс заново и отправьте запрос в группу."
                    )

            message_ids.append(too_many_msg.message_id)
            await state.update_data(message_ids=message_ids)

            for mid in message_ids:
                asyncio.create_task(delete_message_after_delay(message.bot, message.chat.id, mid, 90))

            await redis.delete(f"captcha:{message.from_user.id}")
            await set_rate_limit(message.from_user.id, 60)
            await state.clear()
            return

        # Генерируем новую капчу
        try:
            new_answer, new_image = await generate_visual_captcha()
            await state.update_data(captcha_answer=new_answer)
            await save_captcha_data(message.from_user.id, new_answer, group_name, attempts)

            # Удаляем предыдущие сообщения через 5 секунд
            for mid in message_ids:
                asyncio.create_task(delete_message_after_delay(message.bot, message.chat.id, mid, 5))

            wrong_msg = await message.answer(f"❌ Неверный ответ. Осталось попыток: {3 - attempts}")

            try:
                captcha_msg = await message.answer_photo(
                    photo=new_image,
                    caption="Пожалуйста, введите символы или решите выражение:"
                )
                message_ids = [wrong_msg.message_id, captcha_msg.message_id]
            except Exception as network_error:
                logger.error(f"❌ Ошибка сети при отправке новой капчи: {network_error}")
                fallback_msg = await message.answer(
                    f"⚠️ Не удалось отправить изображение капчи.\n"
                    f"🔑 Ваш код: **{new_answer}**\n"
                    f"Введите этот код:",
                    parse_mode="Markdown",
                )
                message_ids = [wrong_msg.message_id, fallback_msg.message_id]

            await state.update_data(message_ids=message_ids)

            # Удалим через 5 минут
            for mid in message_ids:
                asyncio.create_task(delete_message_after_delay(message.bot, message.chat.id, mid, 300))
            
            # Планируем напоминание через 2 минуты для новой капчи
            asyncio.create_task(schedule_captcha_reminder(message.bot, message.from_user.id, group_name, 2))

        except Exception as captcha_error:
            logger.error(f"❌ Ошибка при генерации новой капчи: {captcha_error}")
            await message.answer("Произошла ошибка при генерации новой капчи. Попробуйте позже.")
            await state.clear()

    except Exception as e:
        logger.error(f"❌ Ошибка при обработке ответа на капчу: {e}")
        logger.debug(traceback.format_exc())
        try:
            err_msg = await message.answer("Пожалуйста, введите корректный ответ, соответствующий изображению.")
            data = await state.get_data()
            mids = data.get("message_ids", [])
            mids.append(err_msg.message_id)
            await state.update_data(message_ids=mids)
        except Exception:
            pass


@visual_captcha_handler_router.message(Command("check"))
async def cmd_check(message: Message, session: AsyncSession):
    """Простой тест отправки сообщения пользователю."""
    await save_user_to_db(
        session,
        {
            "user_id": message.from_user.id,
            "username": message.from_user.username,
            "first_name": message.from_user.first_name,
            "last_name": message.from_user.last_name,
            "language_code": message.from_user.language_code,
        },
    )
    try:
        await message.bot.send_message(message.from_user.id, "Проверка связи ✅")
        await message.answer("Сообщение успешно отправлено")
    except Exception as e:
        await message.answer(f"❌ Не могу отправить сообщение: {e}")


@visual_captcha_handler_router.message(Command("checkuser"))
async def cmd_check_user(message: Message, session: AsyncSession):
    """Проверка возможности отправки сообщения указанному пользователю (ID или @username)."""
    await save_user_to_db(
        session,
        {
            "user_id": message.from_user.id,
            "username": message.from_user.username,
            "first_name": message.from_user.first_name,
            "last_name": message.from_user.last_name,
            "language_code": message.from_user.language_code,
        },
    )

    args = message.text.split()
    if len(args) < 2:
        await message.answer("Укажите ID или @username пользователя: /checkuser <id или @username>")
        return

    target = args[1]
    try:
        if target.isdigit():
            target_id = int(target)
        elif target.startswith("@"):
            username = target[1:]
            chat = await message.bot.get_chat(username)
            target_id = chat.id
        else:
            await message.answer("Неверный формат. Укажите ID (число) или @username")
            return

        await message.bot.send_message(target_id, "Проверка связи от администратора ✅")
        await message.answer(f"✅ Сообщение успешно отправлено (ID: {target_id})")
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить сообщение пользователю: {e}")


@visual_captcha_handler_router.callback_query(F.data == "visual_captcha_settings")
async def visual_captcha_settings(callback_query: CallbackQuery, state: FSMContext):
    """Отображает настройки визуальной капчи для группы."""
    user_id = callback_query.from_user.id
    group_id = await redis.hget(f"user:{user_id}", "group_id")

    if not group_id:
        await callback_query.answer("❌ Не удалось определить группу. Попробуйте снова.", show_alert=True)
        return

    try:
        is_admin = await check_admin_rights(callback_query.bot, int(group_id), user_id)
        if not is_admin:
            await callback_query.answer("У вас нет прав для изменения настроек группы", show_alert=True)
            return

        captcha_enabled = await redis.get(f"visual_captcha_enabled:{group_id}") or "0"
        keyboard = await get_group_settings_keyboard(group_id, captcha_enabled)

        await callback_query.message.edit_text(
            "Настройка визуальной капчи для новых участников.\n\n"
            "При включении этой функции новые участники должны будут пройти проверку с визуальной капчей.",
            reply_markup=keyboard,
        )
        await callback_query.answer()
    except Exception as e:
        logger.error(f"Ошибка при настройке визуальной капчи: {e}")
        await callback_query.answer("Произошла ошибка при загрузке настроек", show_alert=True)


@visual_captcha_handler_router.callback_query(F.data.startswith("set_visual_captcha:"))
async def set_visual_captcha(callback_query: CallbackQuery, state: FSMContext):
    """Устанавливает состояние визуальной капчи (вкл/выкл)."""
    parts = callback_query.data.split(":")
    if len(parts) < 3:
        await callback_query.answer("Некорректные данные", show_alert=True)
        return

    chat_id = parts[1]
    enabled = parts[2]

    try:
        user_id = callback_query.from_user.id
        is_admin = await check_admin_rights(callback_query.bot, int(chat_id), user_id)
        if not is_admin:
            await callback_query.answer("У вас нет прав для изменения настроек группы", show_alert=True)
            return

        await set_visual_captcha_status(int(chat_id), enabled == "1")
        status_message = "Визуальная капча включена" if enabled == "1" else "Визуальная капча отключена"
        await callback_query.answer(status_message, show_alert=True)

        keyboard = await get_group_settings_keyboard(chat_id, enabled)
        await callback_query.message.edit_text(
            "Настройка визуальной капчи для новых участников.\n\n"
            "При включении этой функции новые участники должны будут пройти проверку с визуальной капчей.",
            reply_markup=keyboard,
        )
    except Exception as e:
        logger.error(f"Ошибка при установке настроек визуальной капчи: {e}")
        await callback_query.answer("Произошла ошибка при сохранении настроек", show_alert=True)


@visual_captcha_handler_router.callback_query(F.data == "captcha_settings")
async def back_to_main_captcha_settings(callback: CallbackQuery, state: FSMContext):
    """Возврат к основным настройкам капчи в ЛС."""
    user_id = callback.from_user.id
    group_id = await redis.hget(f"user:{user_id}", "group_id")

    if not group_id:
        await callback.answer("❌ Не удалось определить группу", show_alert=True)
        return

    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass

    from bot.handlers.settings_inprivate_handler import show_settings_callback
    await show_settings_callback(callback)
