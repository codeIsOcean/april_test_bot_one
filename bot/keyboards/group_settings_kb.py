from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_groups_kb(groups):
    buttons = [InlineKeyboardButton(text=group.title, callback_data=f"settings_group_{group.id}") for group in groups]
    return InlineKeyboardMarkup(inline_keyboard=[[btn] for btn in buttons])


def get_toggle_kb(group_id: int, is_enabled: bool):
    text = "🔴 Выключить капчу" if is_enabled else "🟢 Включить капчу"
    value = "off" if is_enabled else "on"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data=f"toggle_visual_{value}_{group_id}")]
    ])
