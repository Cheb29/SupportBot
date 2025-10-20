# handlers/common.py
from aiogram.enums import ContentType
from aiogram.types import Message
from config import MANAGER_IDS, log
from db import set_selection
from utils import AuthorInfo, format_author
from typing import Optional
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from db import get_invoice_state

async def relay_to_manager(message: Message):
    """Шлём во все MANAGER_IDS: шапку + копию; выставляем selection каждому."""
    chat = message.chat
    author = AuthorInfo(
        name=(message.from_user.full_name if message.from_user else "Unknown"),
        username=(message.from_user.username if message.from_user else None),
        user_id=(message.from_user.id if message.from_user else 0),
    )
    header = "\n".join([
        f"🔔 <b>Запрос из чата:</b> {chat.title or '(без названия)'}",
        f"👤 <b>От:</b> {format_author(author)}",
    ])
    for uid in MANAGER_IDS:
        try:
            await set_selection(uid, chat.id)
            await message.bot.send_message(uid, header)
            await message.bot.copy_message(uid, chat.id, message.message_id)
        except Exception as e:
            log.warning("notify manager %s failed: %s", uid, e)

async def send_media_no_caption(bot, chat_id: int, src: Message, reply_to: int | None):
    try:
        ct = src.content_type
        if ct == ContentType.DOCUMENT:
            await bot.send_document(chat_id, src.document.file_id, caption=None,
                                    reply_to_message_id=reply_to, allow_sending_without_reply=True)
        elif ct == ContentType.PHOTO:
            await bot.send_photo(chat_id, src.photo[-1].file_id, caption=None,
                                 reply_to_message_id=reply_to, allow_sending_without_reply=True)
        elif ct == ContentType.VIDEO:
            await bot.send_video(chat_id, src.video.file_id, caption=None,
                                 reply_to_message_id=reply_to, allow_sending_without_reply=True)
        elif ct == ContentType.AUDIO:
            await bot.send_audio(chat_id, src.audio.file_id, caption=None,
                                 reply_to_message_id=reply_to, allow_sending_without_reply=True)
        elif ct == ContentType.ANIMATION:
            await bot.send_animation(chat_id, src.animation.file_id, caption=None,
                                     reply_to_message_id=reply_to, allow_sending_without_reply=True)
        elif ct == ContentType.VOICE:
            await bot.send_voice(chat_id, src.voice.file_id, caption=None,
                                 reply_to_message_id=reply_to, allow_sending_without_reply=True)
        elif ct == ContentType.VIDEO_NOTE:
            await bot.send_video_note(chat_id, src.video_note.file_id,
                                      reply_to_message_id=reply_to, allow_sending_without_reply=True)
        else:
            await bot.copy_message(chat_id, src.chat.id, src.message_id,
                                   reply_to_message_id=reply_to, allow_sending_without_reply=True)
    except Exception as e:
        from config import log
        log.warning("send_media_no_caption failed: %s", e)
        try:
            await bot.copy_message(chat_id, src.chat.id, src.message_id,
                                   reply_to_message_id=reply_to, allow_sending_without_reply=True)
        except Exception:
            pass



async def build_invoice_kb(inv_id: int) -> Optional[InlineKeyboardMarkup]:
    """
    Собирает клавиатуру по актуальному состоянию.
    Возвращает None, если кнопок не осталось (или DONE).
    """
    st = await get_invoice_state(inv_id)
    if not st:
        return None
    if st["status"] == "DONE":
        return None

    rows = []

    if not st["sent_to_accounting"]:
        rows.append([InlineKeyboardButton(text="✅ Отправил в бух", callback_data=f"inv:{inv_id}:MARK_SENT")])

    line = []
    if not st["accounting_replied"]:
        line.append(InlineKeyboardButton(text="📎 Файл в группу", callback_data=f"inv:{inv_id}:POST_FILE"))
    if not st["swift_sent"]:
        line.append(InlineKeyboardButton(text="📄 SWIFT", callback_data=f"inv:{inv_id}:SWIFT_FILE"))
    if line:
        rows.append(line)

    if not st["report_requested"]:
        rows.append([InlineKeyboardButton(text="📝 Запросить отчёт", callback_data=f"inv:{inv_id}:REQUEST_REPORT")])

    # кнопка "Закрыть" всегда доступна, пока заявка не DONE
    rows.append([InlineKeyboardButton(text="✔ Закрыть", callback_data=f"inv:{inv_id}:DONE")])

    # if not rows:
    #     return None
    return InlineKeyboardMarkup(inline_keyboard=rows)
