from aiogram import Bot, Dispatcher
from .groups import setup as setup_groups
from .callbacks import setup as setup_callbacks
from .manager_dm import setup as setup_manager_dm
from .manager_media import setup as setup_manager_media
from .manager_admin import setup as setup_manager_admin

def setup_all(dp: Dispatcher, bot: Bot) -> None:
    setup_groups(dp, bot)
    setup_callbacks(dp, bot)
    setup_manager_admin(dp, bot)
    setup_manager_dm(dp, bot)
    setup_manager_media(dp, bot)
    
    # Добавляйте сюда новые setup_* функции по мере необходимости