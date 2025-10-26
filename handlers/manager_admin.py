# handlers/manager_admin.py
import asyncio
from typing import Optional
from aiogram import Dispatcher, Bot, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, ReplyKeyboardRemove
from aiogram.enums import ChatType
from config import MANAGER_IDS
from db import get_chat_status_msg, sqlite_checkpoint, sqlite_backup_once, list_chats_like,\
      set_selection, list_open_invoices_with_state, get_selection,\
      set_chat_status_msg
from utils import edit_message, escape_html
from datetime import datetime
from kb import MANAGER_RK
from aiogram.exceptions import TelegramBadRequest

def setup(dp: Dispatcher, bot: Bot) -> None:
    dp.message.register(db_backup_now, Command("db_backup"), F.chat.type == ChatType.PRIVATE)
    dp.message.register(cmd_broadcast, Command("broadcast"), F.chat.type == ChatType.PRIVATE)
    dp.message.register(cmd_list_chats, Command("list_chats"), F.chat.type == ChatType.PRIVATE)
    dp.message.register(cmd_select_chat, Command("select_chat"), F.chat.type == ChatType.PRIVATE)
    dp.message.register(cmd_where, Command("where"), F.chat.type == ChatType.PRIVATE)
    dp.message.register(cmd_start, Command("start"), F.chat.type == ChatType.PRIVATE)
    dp.message.register(cmd_ping, Command("ping"), F.chat.type == ChatType.PRIVATE)
    dp.message.register(cmd_invoices, Command("invoices"), F.chat.type == ChatType.PRIVATE)
    dp.message.register(cmd_menu, Command("menu"), F.chat.type == ChatType.PRIVATE)
    dp.message.register(cmd_hide, Command("hide"), F.chat.type == ChatType.PRIVATE)

async def cmd_ping(message: Message):
        if message.from_user.id in MANAGER_IDS:
            await message.answer("pong")

async def db_backup_now(message: Message):
    if message.from_user.id not in MANAGER_IDS:
        return
    try:
        await sqlite_checkpoint()
        path = await sqlite_backup_once()
        await message.answer(f"✅ Бэкап создан: {escape_html(str(path))}")
    except Exception as e:
        await message.answer(f"❌ Ошибка бэкапа: {escape_html(str(e))}")

async def cmd_broadcast(message: Message, command: CommandObject):
    if message.from_user.id not in MANAGER_IDS:
        return
    raw = (command.args or "").strip()
    if not raw:
        await message.answer(
            "Использование:\n"
            "/broadcast all <текст>\n"
            "/broadcast <chat_id> <текст>\n"
            "/broadcast <часть_названия> <текст>"
        )
        return
    key, _, text = raw.partition(" ")
    text = text.strip()
    if not text:
        await message.answer("Нужно указать текст рассылки после фильтра.")
        return
    targets: list[int] = []
    if key.lower() == "all":
        rows = await list_chats_like(None)
        targets = [r[0] for r in rows]
    elif key.lstrip("-").isdigit():
        targets = [int(key)]
    else:
        rows = await list_chats_like(key)
        if not rows:
            await message.answer("По заданной подстроке чатов не найдено.")
            return
        targets = [r[0] for r in rows]

    sent = failed = 0
    errors = []
    for cid in targets:
        try:
            await message.bot.send_message(chat_id=cid, text=text)
            sent += 1
        except Exception as e:
            failed += 1
            errors.append(f"{cid}: {e}")
        await asyncio.sleep(0.05)
    msg = f"📣 Готово. Успешно: {sent}, ошибок: {failed}."
    if failed and errors:
        tail = "\n".join(errors[:5])
        msg += f"\n\nПервые ошибки:\n{tail}" + ("…ещё есть ошибки" if len(errors) > 5 else "")
    await message.answer(msg)

async def cmd_list_chats(message: Message):
    if message.from_user.id not in MANAGER_IDS:
        return
    q = (message.text or "").split(maxsplit=1)
    query = q[1] if len(q) > 1 else None
    rows = await list_chats_like(query)
    if not rows:
        await message.answer("Пока нет известных чатов. Добавьте бота в нужные группы и напишите там любое сообщение.")
        return
    lines = ["📚 Доступные чаты:"]
    for chat_id, title, username, type_ in rows:
        title_disp = title or "(без названия)"
        uname = f"@{username}" if username else ""
        lines.append(f"• {escape_html(title_disp)} {uname} (id={chat_id}, {type_})")
    await message.answer("\n".join(lines))

async def cmd_select_chat(message: Message, command: CommandObject):
    if message.from_user.id not in MANAGER_IDS:
        return
    arg = (command.args or "").strip()
    if not arg:
        await message.answer("Укажите часть названия, @username или id: /select_chat <имя|@username|id>")
        return
    chosen: Optional[int] = None
    if arg.lstrip("-").isdigit():
        chosen = int(arg)
    else:
        rows = await list_chats_like(arg.lstrip("@"))
        if len(rows) == 1:
            chosen = rows[0][0]
        elif len(rows) > 1:
            for chat_id, title, username, _ in rows:
                if (title and title.lower() == arg.lower()) or (username and f"@{username.lower()}" == arg.lower().lstrip()):
                    chosen = chat_id
                    break
            if not chosen:
                preview = "\n".join(
                    f"• {(t or '(без названия)')} @{u if u else ''} (id={cid})" for cid, t, u, _ in rows[:10]
                )
                await message.answer("Найдено несколько чатов, уточните запрос.\n\n" + preview)
                return
        else:
            await message.answer("Чат не найден.")
            return
    await set_selection(message.from_user.id, chosen)

    row = await get_chat_status_msg(message.from_user.id)
    message_id = row[0]
    chat_id = row[1]
    try:
        await edit_message(message.bot, chat_id, message_id, text = f'Текущий чат id={chosen}.Это сообщение будет обновляться.')
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return
        
    await message.answer(f"✔ Выбран чат id={chosen}. /where — проверить.")

async def cmd_where(message: Message):
    if message.from_user.id not in MANAGER_IDS:
        return
    sel = await get_selection(message.from_user.id)
    if not sel:
        await message.answer("Целевой чат не выбран. Используйте /select_chat.")
        return
    try:
        ch = await message.bot.get_chat(sel)
        await message.answer(f"🎯 Текущий чат: {ch.title or '(без названия)'} (id={sel})")
    except Exception as e:
        await message.answer(f"Не удалось получить чат id={sel}: {e}")

async def cmd_start(message: Message):
    if message.from_user.id not in MANAGER_IDS:
        if message.chat.type == ChatType.PRIVATE:
            await message.answer("👋 Это бот поддержки. В группе используйте /support или тег бота.")
        return
    

    text = (
        "👋 Бот поддержки запущен.\n"
        "Команды:\n"
        "• /invoices — открытые заявки\n"
        "• /list_chats — список чатов\n"
        "• /select_chat &lt;имя|@username|id&gt; — выбрать чат\n"
        "• /where — текущий чат\n"
        "• /broadcast … — рассылка\n"
        "• /menu — показать кнопки, /hide — скрыть\n"
    )
    await message.answer(text, reply_markup=MANAGER_RK)

    sel = await get_selection(message.from_user.id)
    if not sel:
        sent = await message.answer('Текущий чат не выбран. Используйте /select_chat.')
    ch = await message.bot.get_chat(sel)
    sent = await message.answer(f'Текущий чат {ch.title}. Это сообщение будет обновляться.')
    await set_chat_status_msg(message.from_user.id, message.chat.id, sent.message_id)
    
    

def _fmt_ts(ts: int) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts)

async def cmd_invoices(message: Message):
    if message.from_user.id not in MANAGER_IDS:
        return
    items = await list_open_invoices_with_state(limit=30)
    if not items:
        await message.answer("✅ Открытых задач нет.")
        return

    lines = ["🧾 <b>Открытые заявки</b>:"]
    for it in items:
        done = " · ".join(it["done"]) if it["done"] else "—"
        left = " · ".join(it["remaining"]) if it["remaining"] else "—"
        lines.append(
            f"• #{it['id']} — статус: <code>{it['status']}</code>\n"
            f"  чат: <code>{it['chat_id']}</code>, создано: { _fmt_ts(it['created_ts']) }\n"
            f"  сделано: {done}\n"
            f"  осталось: {left}"
        )
    await message.answer("\n".join(lines))


async def cmd_menu(message: Message):
    # показываем клавиатуру только менеджерам
    if not message.from_user or message.from_user.id not in MANAGER_IDS:
        return
    await message.answer("Меню открыто.", reply_markup=MANAGER_RK)

async def cmd_hide(message: Message):
    if not message.from_user or message.from_user.id not in MANAGER_IDS:
        return
    await message.answer("Меню скрыто.", reply_markup=ReplyKeyboardRemove())
