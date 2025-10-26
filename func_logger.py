# НЕ называйте файл просто "logging.py", чтобы не путать со стандартным модулем logging!
import logging

def setup_logging(level=logging.INFO):
    # не плодим дубликаты хендлеров при повторных импортах/рестартах
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )

    # ваш именованный логгер (если нужен)
    app_log = logging.getLogger("support-bot")

    # подробности от aiogram/aiohttp
    logging.getLogger("aiogram").setLevel(logging.DEBUG)
    logging.getLogger("aiogram.client.telegram").setLevel(logging.DEBUG)
    logging.getLogger("aiogram.client.session.aiohttp").setLevel(logging.DEBUG)
    logging.getLogger("aiohttp.client").setLevel(logging.DEBUG)

    return app_log
