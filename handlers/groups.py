# handlers/groups.py
from aiogram import Dispatcher, Bot, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.enums import ChatType
from db import save_invoice_card, upsert_chat, create_invoice
from config import MANAGER_IDS, log
from utils import SUPPORTED_MEDIA, bot_was_tagged
from .common import relay_to_manager, build_invoice_kb

def setup(dp: Dispatcher, bot: Bot) -> None:
    dp.message.register(cmd_invoice_group, Command("invoice"))
    dp.message.register(support_command,   Command("support"))
    dp.message.register(debug_rights,      Command("debug_rights"))
    dp.message.register(
        index_chats,
        F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}),
        flags={"block": False},                          # ← НЕ блокируем последующие обработчики
    )

async def cmd_invoice_group(message: Message):
    if message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return
    if message.content_type not in SUPPORTED_MEDIA:
        try:
            await message.reply("Пожалуйста, отправьте /invoice вместе с файлом (документ/фото/видео).")
        except Exception:
            pass
        return

    try:
        await upsert_chat(message.chat.id, message.chat.title, getattr(message.chat, "username", None), message.chat.type)
    except Exception:
        pass

    inv_id = await create_invoice(message.chat.id, message.message_id,
                                  message.from_user.id if message.from_user else 0)

    header = f"🧾 Новая заявка /invoice #{inv_id}\nЧат: {message.chat.title or '(без названия)'} (id={message.chat.id})"
    for uid in MANAGER_IDS:
        try:
            await message.bot.send_message(uid, header)
            await message.bot.copy_message(uid, message.chat.id, message.message_id)
            kb = await build_invoice_kb(inv_id)
            msg_card = await message.bot.send_message(uid, f"Заявка #{inv_id}", reply_markup=kb)
            try:
                await save_invoice_card(manager_id=uid, invoice_id=inv_id,
                                        dm_chat_id=msg_card.chat.id, message_id=msg_card.message_id)
            except Exception as e:
                    log.warning("save_invoice_card failed: %s", e)
        
        except Exception as e:
            log.warning("notify manager %s failed: %s", uid, e)

async def support_command(message: Message):
    if message.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}:
        target = message.reply_to_message or message
        await upsert_chat(message.chat.id, message.chat.title, getattr(message.chat, "username", None), message.chat.type)
        await relay_to_manager(target)

async def index_chats(message: Message):
    chat = message.chat
    if chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return
    await upsert_chat(chat.id, chat.title, getattr(chat, "username", None), chat.type)

    me = await message.bot.get_me()
    tagged = bot_was_tagged(message, me.username, me.id)
    is_reply_to_bot = bool(message.reply_to_message and message.reply_to_message.from_user and message.reply_to_message.from_user.id == me.id)
    is_support_cmd = bool(message.text and message.text.split()[0] == "/support")
    if tagged or is_reply_to_bot or is_support_cmd:
        await relay_to_manager(message)

async def debug_rights(message: Message):
    chat_id = message.chat.id
    me = await message.bot.get_me()
    member = await message.bot.get_chat_member(chat_id, me.id)
    chat = await message.bot.get_chat(chat_id)
    status = getattr(member, "status", "unknown")
    can_send_messages = getattr(member, "can_send_messages", None)
    default_perms = getattr(chat, "permissions", None)
    def_perm_send = getattr(default_perms, "can_send_messages", None) if default_perms else None
    msg = (
        f"👤 Статус бота: <b>{status}</b>\n"
        f"🔧 can_send_messages: {can_send_messages}\n"
        f"⚙️ default can_send_messages: {def_perm_send}"
    )
    await message.reply(msg)
