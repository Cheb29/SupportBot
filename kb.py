# kb.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def invoice_kb(inv_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправил в бух", callback_data=f"inv:{inv_id}:MARK_SENT")],
        [
            InlineKeyboardButton(text="📎 Файл в группу", callback_data=f"inv:{inv_id}:POST_FILE"),
            InlineKeyboardButton(text="📄 SWIFT",        callback_data=f"inv:{inv_id}:SWIFT_FILE"),
        ],
        [InlineKeyboardButton(text="📝 Запросить отчёт", callback_data=f"inv:{inv_id}:REQUEST_REPORT")],
        [InlineKeyboardButton(text="✔ Закрыть",         callback_data=f"inv:{inv_id}:DONE")],
    ])


MANAGER_RK = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🧾 /invoices"), KeyboardButton(text="📚 /list_chats")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Выберите действие…",
    one_time_keyboard=False,
    selective=True,
)