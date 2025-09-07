# bot/handlers/bot_activity_handlers/bot_added_handler.py
import logging
from typing import Optional

from aiogram import Router, Bot, F
from aiogram.enums import ChatMemberStatus, UpdateType, ChatType
from aiogram.filters.chat_member_updated import ChatMemberUpdatedFilter
from aiogram.types import (
    ChatMemberUpdated,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    CallbackQuery,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession 

from bot.services.bot_added_handler_logic import (
    sync_group_and_admins,
    is_user_group_admin,
    build_private_chat_link,
    safe_send
)

logger = logging.getLogger(__name__)

bot_added_router = Router(name="bot_added_router")


def _settings_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    """
    Клавиатура выбора места настройки.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🏡 Настроить здесь",
                    callback_data=f"settings_here:{chat_id}",
                ),
                InlineKeyboardButton(
                    text="💬 Настроить в личке",
                    callback_data=f"settings_pm:{chat_id}",
                ),
            ]
        ]
    )


def _go_to_pm_keyboard(bot_username: str) -> InlineKeyboardMarkup:
    """
    Клавиатура для перехода к боту в ЛС.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 Перейти ко мне в ЛС",
                    url=f"https://t.me/{bot_username}",
                )
            ]
        ]
    )


# =======================================
# ОБРАБОТКА СМЕНЫ СТАТУСА САМОГО БОТА
# =======================================
@bot_added_router.my_chat_member() 
async def on_my_status_change(
        event: ChatMemberUpdated,
        bot: Bot,
        session: AsyncSession,
):
    """
    Реагируем, когда меняется статус ИМЕННО нашего бота в группе (my_chat_member).
    """
    print("🛠 Хендлер my_chat_member сработал")
    print(f"📥 Новый статус: {event.new_chat_member.status}")

    # Проверяем, что бот получил статус member или administrator
    if event.new_chat_member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.MEMBER]:
        print("⛔️ бот не получил нужный статус")
        return

    chat = event.chat
    chat_id = chat.id
    chat_title = getattr(chat, "title", str(chat.id))
    bot_info = await bot.me()

    logger.info(f"[BOT_ADDED] chat='{chat_title}' id={chat_id} status={event.new_chat_member.status}")

    try:
        # Обработка анонимного админа
        if event.from_user is None and event.sender_chat:
            print("⚡️ Бота добавил анонимный администратор!")

        # Обработка обычного пользователя
        elif event.from_user:
            user = event.from_user
            print(f"✅ Бот добавлен пользователем {user.full_name} (ID: {user.id})")

        # Определяем текст и клавиатуру в зависимости от статуса
        if event.new_chat_member.status == ChatMemberStatus.ADMINISTRATOR:
            # Синхронизируем группу и админов через бизнес-логику
            await sync_group_and_admins(chat_id, chat_title, bot_info.id, bot)
            text = "✅ Спасибо! Я добавлен **с правами администратора**.\n\nГде настраиваем мои функции?"
            reply_markup = _settings_keyboard(chat_id)
        else:  # MEMBER
            text = ("Спасибо, что добавили меня в группу! 🎉\n\n"
                    "Чтобы все функции работали (капча, антиспам и др.), "
                    "дайте, пожалуйста, **права администратора**.")
            reply_markup = None

        await safe_send(bot, chat_id, text, reply_markup=reply_markup)

    except Exception:
        logger.exception("[BOT_ADDED_HANDLER_FAIL]")
        await session.rollback()


# =======================================
# CALLBACK: "НАСТРОИТЬ ЗДЕСЬ" / "В ЛИЧКЕ"
# =======================================
@bot_added_router.callback_query(F.data.startswith("settings_here:"))
async def on_settings_here(
    cq: CallbackQuery,
    bot: Bot,
    session: AsyncSession,
):
    """
    Обработка нажатия кнопки "Настроить здесь".
    Проверяем, что жмёт админ группы.
    """
    if not cq.message:
        await cq.answer("Сообщение не найдено.", show_alert=True)
        return

    chat_id_str = cq.data.split(":", 1)[1]
    try:
        chat_id = int(chat_id_str)
    except ValueError:
        await cq.answer("Некорректные данные.", show_alert=True)
        return

    # Убедимся, что это групповое сообщение
    if cq.message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await cq.answer("Эту кнопку нужно нажимать в группе.", show_alert=True)
        return

    user_id = cq.from_user.id
    if not await is_user_group_admin(bot, chat_id, user_id):
        await cq.answer("Доступно только администраторам.", show_alert=True)
        return

    await cq.answer()
    await safe_send(
        bot,
        chat_id,
        "⚙️ Открываю настройки здесь:\n"
        "• Капча: Вкл/Выкл\n"
        "• Фильтр ссылок: Вкл/Выкл\n"
        "• Фильтр NSFW: Вкл/Выкл\n"
        "• Мут/Бан команды: Вкл/Выкл\n\n"
        "Выбери нужный пункт в следующем меню…"
    )


@bot_added_router.callback_query(F.data.startswith("settings_pm:"))
async def on_settings_pm(
    cq: CallbackQuery,
    bot: Bot,
    session: AsyncSession,
):
    """
    Обработка нажатия "Настроить в личке":
    - Проверяем админ-права
    - Пытаемся написать в ЛС
    - В группе отвечаем, что настройки высланы в личку
    """

    
    if not cq.message:
        await cq.answer("Сообщение не найдено.", show_alert=True)
        return

    chat_id_str = cq.data.split(":", 1)[1]
    try:
        chat_id = int(chat_id_str)
    except ValueError:
        await cq.answer("Некорректные данные.", show_alert=True)
        return

    user = cq.from_user
    user_id = user.id

    if not await is_user_group_admin(bot, chat_id, user_id):
        await cq.answer("Доступно только администраторам.", show_alert=True)
        return

    await cq.answer()

    # Пытаемся отправить настройки в ЛС
    linked = await build_private_chat_link(bot)
    pm_ok = False
    try:
        await safe_send(
            bot,
            user_id,
            "👋 Привет! Открою настройки бота для этой группы здесь, в личке.\n"
            "Выбери, что хочешь изменить:\n"
            "• Капча (визуальная/математическая)\n"
            "• Фильтр ссылок/приглашений\n"
            "• Фото-модерация\n"
            "• Команды mute/ban и их шаблоны\n\n"
            "Если сообщения не приходят, сначала **напиши что-нибудь боту**.",
        )
        pm_ok = True
    except Exception:
        logger.exception(f"[PM_SEND_FAIL] user_id={user_id}")

    # Получаем username бота для кнопки
    bot_info = await bot.me()
    bot_username = bot_info.username

    # Отвечаем в группе: получилось/не получилось
    if pm_ok and bot_username:
        await safe_send(
            bot,
            chat_id,
            f"✅ Настройки высланы администратору {user.full_name} в личные сообщения.",
            reply_markup=_go_to_pm_keyboard(bot_username)
        )
    elif bot_username:
        # если нельзя написать в ЛС, даём ссылку на бота (если есть username)
        tail = f"\n\nОткрой бота: {linked}" if linked else ""
        await safe_send(
            bot,
            chat_id,
            f"⚠️ Не удалось отправить настройки в личку администратору {user.full_name}."
            f"{tail}\nНапиши боту /start и нажми кнопку ниже.",
            reply_markup=_go_to_pm_keyboard(bot_username)
        )
    else:
        # Если нет username у бота
        await safe_send(
            bot,
            chat_id,
            f"⚠️ Не удалось отправить настройки в личку администратору {user.full_name}.\n"
            f"Найди бота в поиске и напиши ему /start.",
        )

