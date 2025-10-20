import os
import logging
from dotenv import load_dotenv
from pathlib import Path


load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
# MANAGER_ID = int(os.getenv("MANAGER_ID", "0"))
MANAGER_IDS = {218837831, 7892801404}


DB_PATH = os.getenv("DB_PATH", "bot.db")
BACKUP_DIR = Path(os.getenv("BACKUP_PATH", "db_backups"))
BACKUP_EVERY = 4 * 60 * 60  # in seconds, default is 4 hours

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("support-bot")