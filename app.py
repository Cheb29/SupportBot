import asyncio
import contextlib
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from config import BOT_TOKEN, BACKUP_EVERY, log
from db import init_db, sqlite_checkpoint, sqlite_backup_once
from handlers import setup_all
from func_logger import setup_logging # Инициализация логгера



async def periodic_backup_task():
    while True:
        try:
            await sqlite_checkpoint()
            path = await sqlite_backup_once()
            log.info("[backup] %s создан", path)
        except Exception:
            log.exception("[backup] ошибка")
        await asyncio.sleep(BACKUP_EVERY)

async def main():
    await init_db()

    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()

    await bot.delete_webhook(drop_pending_updates=False)
    setup_all(dp, bot)

    backup_task = asyncio.create_task(periodic_backup_task())

    try:
        me = await bot.get_me()
        log = setup_logging()
        log.info("Bot starting as @%s (id=%s)", me.username, me.id)

        await dp.start_polling(
            bot,
            allowed_updates=["message", "chat_member", "my_chat_member", "callback_query"],
        )
    finally:
        # аккуратно гасим фоновые задачи
        backup_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await backup_task

        # закрываем HTTP-сессию бота (иначе будут Unclosed client session/connector)
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped")
