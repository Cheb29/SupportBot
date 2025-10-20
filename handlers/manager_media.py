# handlers/manager_media.py

from aiogram import Dispatcher, Bot, F
from aiogram.types import Message
from aiogram.enums import ChatType, ContentType

from config import MANAGER_IDS, log

# ⚙️ БД-хелперы
from db import (
    get_mode,
    get_invoice,
    clear_mode,
    set_invoice_status,
    get_invoice_cards,      # ← добавлено: чтобы обновлять карточки у всех менеджеров
)

# 🧩 Общие утилиты по задачам
from .common import (
    send_media_no_caption,
    build_invoice_kb,       # ← оставляем только из .common (а НЕ из db)  [ОТКАТ дублирующего импорта]
)

# Только поддерживаемые типы — сюда не попадут команды/текст
SUPPORTED_MEDIA = {
    ContentType.DOCUMENT, ContentType.PHOTO, ContentType.VIDEO,
    ContentType.AUDIO, ContentType.VOICE, ContentType.ANIMATION, ContentType.VIDEO_NOTE
}


def setup(dp: Dispatcher, bot: Bot) -> None:
    """
    Регистрируем приём медиа в ЛС менеджера.
    ВАЖНО: manager_dm должен игнорировать SUPPORTED_MEDIA, чтобы не было дублей.  [ОТКАТ логики «два хендлера ловят медиа»]
    """
    dp.message.register(
        manager_media_flow,
        F.chat.type == ChatType.PRIVATE,
        F.content_type.in_(SUPPORTED_MEDIA),
    )


async def manager_media_flow(message: Message):
    """
    Получили от менеджера в ЛС файл для конкретной заявки:
      - публикуем файл в исходную группу (reply к /invoice) без подписи,
      - фиксируем фактический статус (ACCOUNTING_REPLIED или SWIFT_SENT),
      - пересобираем клавиатуры карточек у всех менеджеров (убираем только сделанное),
      - чистим режим ожидания файла.
    """
    # Только менеджеры
    if not message.from_user or message.from_user.id not in MANAGER_IDS:
        return

    # Ждём установленный режим из колбэка
    mode = await get_mode(message.from_user.id)
    if not mode:
        await message.answer("Нажмите кнопку в карточке заявки (например, «📎 Файл в группу»), затем пришлите файл.")
        return

    inv_id, action = mode

    # Валидация заявки
    inv = await get_invoice(inv_id)
    if not inv:
        await clear_mode(message.from_user.id)
        await message.answer("Заявка не найдена.")
        return

    chat_id, origin_msg_id = inv[1], inv[2]

    # 1) Публикуем файл в исходную группу, реплаем на /invoice (без подписи)
    await send_media_no_caption(message.bot, chat_id, message, reply_to=origin_msg_id)

    # 2) Фиксируем ФАКТ (а не намерение)  [ОТКАТ INTENT-событий]
    if action == "SWIFT_FILE":
        await set_invoice_status(inv_id, "SWIFT_SENT", message.from_user.id, None)
        await message.answer("📄 SWIFT отправлен.")
    else:
        await set_invoice_status(inv_id, "ACCOUNTING_REPLIED", message.from_user.id, None)
        await message.answer("📎 Файл отправлен в группу.")

    # 3) Обновляем клавиатуры карточек у всех менеджеров
    #    (кнопка исчезает только после факта доставки)  [ВАЖНОЕ ИЗМЕНЕНИЕ]
    try:
        kb = await build_invoice_kb(inv_id)     # станет без соответствующей кнопки
        cards = await get_invoice_cards(inv_id) # [(manager_id, dm_chat_id, message_id), ...]
        for _, dm_chat_id, msg_id in cards:
            try:
                await message.bot.edit_message_reply_markup(
                    chat_id=dm_chat_id,
                    message_id=msg_id,
                    reply_markup=kb,
                )
            except Exception as e:
                # Карточка могла быть удалена у конкретного менеджера — не критично
                log.debug("edit_message_reply_markup failed for inv=%s msg=%s: %s", inv_id, msg_id, e)
    except Exception as e:
        log.warning("update invoice cards failed for #%s: %s", inv_id, e)

    # 4) Сбрасываем режим ожидания файла для менеджера
    await clear_mode(message.from_user.id)
