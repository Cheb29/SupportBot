# handlers/callbacks.py
import re
from aiogram import Dispatcher, Bot, F
from aiogram.types import CallbackQuery
from config import MANAGER_IDS, log
from db import get_invoice, set_invoice_status, set_mode
from handlers.common import build_invoice_kb

ACTION_RE = re.compile(r"^inv:(-?\d+):([A-Za-z_]+)$")

def setup(dp: Dispatcher, bot: Bot) -> None:
    dp.callback_query.register(on_invoice_action, F.data.startswith("inv:"))

async def on_invoice_action(cb: CallbackQuery):
    log.info("callback: uid=%s data=%r", getattr(cb.from_user, "id", None), cb.data)
    log.info("callback from %s data=%r", cb.from_user.id if cb.from_user else None, cb.data)

    if not cb.from_user or cb.from_user.id not in MANAGER_IDS:
        await cb.answer()
        return

    m = ACTION_RE.match(cb.data or "")
    if not m:
        await cb.answer("Некорректные данные", show_alert=True)
        return

    inv_id = int(m.group(1))
    act = m.group(2).strip().upper()

    inv = await get_invoice(inv_id)
    if not inv:
        await cb.answer("Заявка не найдена", show_alert=True)
        return

    if act == "MARK_SENT":
        await set_invoice_status(inv_id, "SENT_TO_ACCOUNTING", cb.from_user.id, None)
        await cb.answer("Отмечено ✅")
    elif act == "REQUEST_REPORT":
        await set_invoice_status(inv_id, "REPORT_REQUESTED", cb.from_user.id, None)
        await cb.answer("Запрос зафиксирован 📝")
    elif act == "POST_FILE":
        await set_mode(cb.from_user.id, inv_id, "POST_FILE")
        await cb.message.answer(f"Заявка #{inv_id}: пришлите файл — опубликую его в группе (без текста).")
        await cb.answer()
    elif act == "SWIFT_FILE":
        await set_mode(cb.from_user.id, inv_id, "SWIFT_FILE")
        await cb.message.answer(f"Заявка #{inv_id}: пришлите SWIFT-файл — опубликую его в группе (без текста).")
        await cb.answer()
    elif act in ("DONE"):
        await set_invoice_status(inv_id, "DONE", cb.from_user.id, None)
        await cb.answer("Заявка закрыта ✔")
    else:
        await cb.answer(f"Неизвестное действие: {act}", show_alert=True)

# ПОСЛЕ ЛЮБОГО УСПЕШНОГО ACTION — обновляем клавиатуру (убираем выполненное)
    try:
        kb = await build_invoice_kb(inv_id)  # None -> удалить клавиатуру
        await cb.message.edit_reply_markup(reply_markup=kb)
    except Exception as e:
        log.warning("edit_reply_markup failed for inv=%s: %s", inv_id, e)
