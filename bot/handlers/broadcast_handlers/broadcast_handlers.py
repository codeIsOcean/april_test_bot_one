# handlers/broadcast_handlers.py
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from bot.services.broadcast_logic import (
    get_all_users_count, 
    broadcast_to_all_users, 
    is_authorized_user
)
from bot.database.session import get_session

logger = logging.getLogger(__name__)

broadcast_router = Router()

class BroadcastStates(StatesGroup):
    waiting_for_message = State()
    confirming_broadcast = State()

@broadcast_router.callback_query(F.data == "broadcast_settings")
async def broadcast_settings(callback: CallbackQuery):
    """Показывает настройки рассылок"""
    if not await is_authorized_user(callback.from_user.id):
        await callback.answer("❌ У вас нет прав для рассылок", show_alert=True)
        return
    
    async with get_session() as session:
        users_count = await get_all_users_count(session)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Отправить рассылку", callback_data="start_broadcast")],
        [InlineKeyboardButton(text="📊 Статистика пользователей", callback_data="users_stats")],
        [InlineKeyboardButton(text="« Назад", callback_data="back_to_broadcast_settings")]
    ])
    
    await callback.message.edit_text(
        f"📢 <b>Настройки рассылок</b>\n\n"
        f"👥 Всего пользователей в БД: <b>{users_count}</b>\n\n"
        f"🔒 Доступ: Только @texas_dev\n\n"
        f"Выберите действие:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

@broadcast_router.callback_query(F.data == "start_broadcast")
async def start_broadcast(callback: CallbackQuery, state: FSMContext):
    """Начинает процесс создания рассылки"""
    if not await is_authorized_user(callback.from_user.id):
        await callback.answer("❌ У вас нет прав для рассылок", show_alert=True)
        return
    
    await state.set_state(BroadcastStates.waiting_for_message)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_broadcast")]
    ])
    
    await callback.message.edit_text(
        "📝 <b>Создание рассылки</b>\n\n"
        "Отправьте сообщение, которое хотите разослать всем пользователям.\n"
        "Поддерживается HTML разметка.\n\n"
        "Пример:\n"
        "<code>Привет! Это тестовое сообщение от бота.</code>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

@broadcast_router.message(BroadcastStates.waiting_for_message)
async def process_broadcast_message(message: Message, state: FSMContext):
    """Обрабатывает сообщение для рассылки"""
    if not await is_authorized_user(message.from_user.id):
        await message.answer("❌ У вас нет прав для рассылок")
        return
    
    message_text = message.text
    if not message_text:
        await message.answer("❌ Сообщение не может быть пустым")
        return
    
    await state.update_data(broadcast_message=message_text)
    await state.set_state(BroadcastStates.confirming_broadcast)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправить рассылку", callback_data="confirm_broadcast")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_broadcast")]
    ])
    
    await message.answer(
        f"📋 <b>Предварительный просмотр рассылки</b>\n\n"
        f"<b>Сообщение:</b>\n{message_text}\n\n"
        f"Подтвердите отправку рассылки:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

@broadcast_router.callback_query(F.data == "confirm_broadcast")
async def confirm_broadcast(callback: CallbackQuery, state: FSMContext):
    """Подтверждает и отправляет рассылку"""
    if not await is_authorized_user(callback.from_user.id):
        await callback.answer("❌ У вас нет прав для рассылок", show_alert=True)
        return
    
    data = await state.get_data()
    message_text = data.get("broadcast_message")
    
    if not message_text:
        await callback.answer("❌ Сообщение не найдено", show_alert=True)
        return
    
    await callback.message.edit_text("🚀 Отправляем рассылку... Пожалуйста, подождите.")
    
    # Отправляем рассылку
    result = await broadcast_to_all_users(callback.bot, message_text, max_users=100)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Назад к рассылкам", callback_data="broadcast_settings")]
    ])
    
    if result["success"]:
        await callback.message.edit_text(
            f"✅ <b>Рассылка завершена!</b>\n\n"
            f"📊 <b>Результаты:</b>\n"
            f"👥 Всего пользователей: {result['total_users']}\n"
            f"✅ Успешно отправлено: {result['success_count']}\n"
            f"❌ Ошибок: {result['error_count']}\n\n"
            f"{result['message']}",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text(
            f"❌ <b>Ошибка рассылки</b>\n\n{result['message']}",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    
    await state.clear()
    await callback.answer()

@broadcast_router.callback_query(F.data == "users_stats")
async def users_stats(callback: CallbackQuery):
    """Показывает статистику пользователей"""
    if not await is_authorized_user(callback.from_user.id):
        await callback.answer("❌ У вас нет прав для рассылок", show_alert=True)
        return
    
    async with get_session() as session:
        users_count = await get_all_users_count(session)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Назад", callback_data="broadcast_settings")]
    ])
    
    await callback.message.edit_text(
        f"📊 <b>Статистика пользователей</b>\n\n"
        f"👥 Всего пользователей в БД: <b>{users_count}</b>\n\n"
        f"💡 Пользователи сохраняются автоматически при:\n"
        f"• Прохождении капчи\n"
        f"• Отправке запроса на вступление\n"
        f"• Взаимодействии с ботом",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

@broadcast_router.callback_query(F.data == "cancel_broadcast")
async def cancel_broadcast(callback: CallbackQuery, state: FSMContext):
    """Отменяет рассылку"""
    await state.clear()
    await callback.message.edit_text("❌ Рассылка отменена")
    await callback.answer()


@broadcast_router.callback_query(F.data == "back_to_broadcast_settings")
async def back_to_broadcast_settings(callback: CallbackQuery):
    """Возврат к настройкам рассылок"""
    if not await is_authorized_user(callback.from_user.id):
        await callback.answer("❌ У вас нет прав для рассылок", show_alert=True)
        return
    
    async with get_session() as session:
        users_count = await get_all_users_count(session)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Отправить рассылку", callback_data="start_broadcast")],
        [InlineKeyboardButton(text="📊 Статистика пользователей", callback_data="users_stats")],
        [InlineKeyboardButton(text="« Назад", callback_data="back_to_groups")]
    ])
    
    await callback.message.edit_text(
        f"📢 <b>Настройки рассылок</b>\n\n"
        f"👥 Всего пользователей в БД: <b>{users_count}</b>\n\n"
        f"🔒 Доступ: Только @texas_dev\n\n"
        f"Выберите действие:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

@broadcast_router.message(F.text == "/checkusers")
async def check_users_command(message: Message):
    """Команда для проверки количества пользователей в БД"""
    if not await is_authorized_user(message.from_user.id):
        await message.answer("❌ У вас нет прав для этой команды")
        return
    
    async with get_session() as session:
        users_count = await get_all_users_count(session)
    
    await message.answer(f"👥 Всего пользователей в БД: <b>{users_count}</b>", parse_mode="HTML")
