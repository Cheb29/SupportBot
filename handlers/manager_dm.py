# handlers/manager_dm.py
from aiogram import Dispatcher, Bot, F
from aiogram.types import Message
from aiogram.enums import ChatType, ContentType
from config import MANAGER_IDS
from db import get_selection
from config import log
from utils import SUPPORTED_MEDIA

def setup(dp: Dispatcher, bot: Bot) -> None:
     dp.message.register(
        manager_dm,
        F.chat.type == ChatType.PRIVATE,
        ~F.content_type.in_(SUPPORTED_MEDIA),   # <-- игнорируем медиа в этом хендлере
    )


async def manager_dm(message: Message):
    # пускаем только менеджеров
    if not message.from_user or message.from_user.id not in MANAGER_IDS:
        return
    # НИКОГДА не трогаем команды — чтоб /list_chats и прочее работали
    if message.text and message.text.startswith("/"):
        return

    if message.content_type in SUPPORTED_MEDIA:
        return

    sel = await get_selection(message.from_user.id)
    if not sel:
        await message.answer("Сначала выберите чат: /select_chat &lt;имя|@username|id&gt;")
        return

    try:
        if message.content_type in {
            ContentType.PHOTO, ContentType.VIDEO, ContentType.DOCUMENT, ContentType.AUDIO,
            ContentType.VOICE, ContentType.VIDEO_NOTE, ContentType.ANIMATION,
            ContentType.STICKER, ContentType.CONTACT, ContentType.LOCATION,
        }:
            await message.bot.copy_message(chat_id=sel, from_chat_id=message.chat.id, message_id=message.message_id)
        else:
            text = message.text or message.caption
            if not text:
                await message.answer("Сообщение пустое. Пришлите текст или файл/медиа.")
                return
            await message.bot.send_message(chat_id=sel, text=text)
        await message.answer("✅ Отправлено.")
    except Exception as e:
        log.exception("Failed to relay to group")
        await message.answer(f"⚠️ Ошибка отправки: {e}")
