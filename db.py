# db.py — единая БД для чатов и инвойс-цикла
import time
from pathlib import Path
from typing import Optional, List, Tuple

import aiosqlite
from config import DB_PATH, BACKUP_DIR  # BACKUP_DIR должен быть pathlib.Path или строкой пути


# ------------------------- СХЕМА -------------------------
CREATE_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- каталожная таблица групп
CREATE TABLE IF NOT EXISTS chats (
    chat_id       INTEGER PRIMARY KEY,
    title         TEXT,
    username      TEXT,
    type          TEXT NOT NULL,
    last_seen_ts  INTEGER NOT NULL DEFAULT (strftime('%s','now'))
);

-- выбранный групповой чат для каждого менеджера (для ответов/рассылки)
CREATE TABLE IF NOT EXISTS manager_selection (
    manager_id  INTEGER PRIMARY KEY,
    chat_id     INTEGER,
    FOREIGN KEY (chat_id) REFERENCES chats(chat_id)
);

-- заявки /invoice
CREATE TABLE IF NOT EXISTS invoices (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id        INTEGER NOT NULL,     -- исходная группа
    origin_msg_id  INTEGER NOT NULL,     -- id сообщения с /invoice + файлом
    author_id      INTEGER NOT NULL,     -- кто создал
    created_ts     INTEGER NOT NULL DEFAULT (strftime('%s','now')),
    status         TEXT    NOT NULL DEFAULT 'NEW',
    FOREIGN KEY (chat_id) REFERENCES chats(chat_id)
);

-- история событий по заявке
CREATE TABLE IF NOT EXISTS invoice_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id  INTEGER NOT NULL,
    ts          INTEGER NOT NULL DEFAULT (strftime('%s','now')),
    actor_id    INTEGER,                 -- менеджер
    action      TEXT    NOT NULL,        -- CREATED|SENT_TO_ACCOUNTING|ACCOUNTING_REPLIED|SWIFT_SENT|REPORT_REQUESTED|DONE|NOTE
    note        TEXT,
    FOREIGN KEY (invoice_id) REFERENCES invoices(id)
);

-- “ожидаю файл” для конкретного менеджера по конкретной заявке
CREATE TABLE IF NOT EXISTS manager_mode (
    manager_id  INTEGER PRIMARY KEY,
    invoice_id  INTEGER NOT NULL,
    action      TEXT    NOT NULL,        -- 'POST_FILE' | 'SWIFT_FILE'
    FOREIGN KEY (invoice_id) REFERENCES invoices(id)
);

CREATE TABLE IF NOT EXISTS invoice_cards (
    manager_id  INTEGER NOT NULL,
    invoice_id  INTEGER NOT NULL,
    dm_chat_id  INTEGER NOT NULL,   -- обычно == manager_id (ЛС)
    message_id  INTEGER NOT NULL,   -- id сообщения-«карточки» с кнопками
    PRIMARY KEY(manager_id, invoice_id)
);

CREATE TABLE IF NOT EXISTS start_msg (
    manager_id  INTEGER PRIMARY KEY,
    chat_id     INTEGER,
    msg_id      INTEGER,
    FOREIGN KEY (chat_id) REFERENCES chats(chat_id)
);

CREATE INDEX IF NOT EXISTS idx_chats_seen ON chats(last_seen_ts);
CREATE INDEX IF NOT EXISTS idx_invoices_chat ON invoices(chat_id);
CREATE INDEX IF NOT EXISTS idx_events_invoice ON invoice_events(invoice_id, id);
"""


# ------------------------- ИНИЦИАЛИЗАЦИЯ -------------------------
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(CREATE_SQL)
        await db.commit()


# ------------------------- CHATS -------------------------
async def upsert_chat(chat_id: int, title: Optional[str], username: Optional[str], type_: str):
    """Добавить/обновить чат в каталоге."""
    if username and username.startswith("@"):
        username = username[1:]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO chats (chat_id, title, username, type, last_seen_ts)
            VALUES (?, ?, ?, ?, strftime('%s','now'))
            ON CONFLICT(chat_id) DO UPDATE SET
                title        = excluded.title,
                username     = excluded.username,
                type         = excluded.type,
                last_seen_ts = excluded.last_seen_ts
            """,
            (chat_id, title, username, str(type_)),
        )
        await db.commit()


async def list_chats_like(q: Optional[str] = None) -> List[Tuple[int, Optional[str], Optional[str], str]]:
    """[(chat_id, title, username, type)] — при q фильтруем по подстроке в title/username."""
    limit = 500
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT chat_id, title, username, type FROM chats ORDER BY last_seen_ts DESC LIMIT ?",
            (limit,),
        )
        rows = await cur.fetchall()

    if not q:
        return rows

    needle = q.casefold()
    def match(row):
        title = (row[1] or "").casefold()
        uname = (row[2] or "").casefold()
        return (needle in title) or (needle in uname)

    return [r for r in rows if match(r)]


async def get_target_chats(query: Optional[str]) -> List[Tuple[int, Optional[str], Optional[str]]]:
    """
    [(chat_id, title, username)].
    'all'/None — до 100 последних; иначе ILIKE по title/username (через lower LIKE).
    """
    async with aiosqlite.connect(DB_PATH) as db:
        if not query or query.lower() == "all":
            cur = await db.execute(
                "SELECT chat_id, title, username FROM chats ORDER BY last_seen_ts DESC LIMIT 100"
            )
        else:
            q_like = f"%{query.lower()}%"
            cur = await db.execute(
                """
                SELECT chat_id, title, username
                FROM chats
                WHERE lower(coalesce(title,'')) LIKE ? OR lower(coalesce(username,'')) LIKE ?
                ORDER BY last_seen_ts DESC
                LIMIT 100
                """,
                (q_like, q_like),
            )
        rows = await cur.fetchall()
    return rows


# ------------------------- MANAGER SELECTION -------------------------
async def set_selection(manager_id: int, chat_id: int, db_path: str = DB_PATH) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO manager_selection (manager_id, chat_id)
            VALUES (?, ?)
            ON CONFLICT(manager_id) DO UPDATE SET chat_id = excluded.chat_id
            """,
            (manager_id, chat_id),
        )
        await db.commit()


async def get_selection(manager_id: int, db_path: str = DB_PATH) -> Optional[int]:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute("SELECT chat_id FROM manager_selection WHERE manager_id = ?", (manager_id,))
        row = await cur.fetchone()
    return row[0] if row else None


# ------------------------- INVOICES -------------------------
async def create_invoice(chat_id: int, origin_msg_id: int, author_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        # 1) вставляем ЗАЯВКУ и сразу сохраняем её id
        cur = await db.execute(
            "INSERT INTO invoices(chat_id, origin_msg_id, author_id) VALUES(?,?,?)",
            (chat_id, origin_msg_id, author_id)
        )
        invoice_id = cur.lastrowid   # ← правильный id заявки

        # 2) логируем событие CREATED с правильным invoice_id
        await db.execute(
            "INSERT INTO invoice_events(invoice_id, action, actor_id) VALUES(?,?,?)",
            (invoice_id, 'CREATED', author_id)
        )

        await db.commit()
        return invoice_id


async def get_invoice(invoice_id: int) -> Optional[Tuple[int, int, int, int, int, str]]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, chat_id, origin_msg_id, author_id, created_ts, status FROM invoices WHERE id=?",
            (invoice_id,),
        )
        return await cur.fetchone()


async def list_invoices(limit: int = 30) -> List[Tuple[int, int, int, int, int, str]]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, chat_id, origin_msg_id, author_id, created_ts, status FROM invoices ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return await cur.fetchall()


async def set_invoice_status(invoice_id: int, status: str, actor_id: Optional[int], note: Optional[str] = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE invoices SET status=? WHERE id=?", (status, invoice_id))
        await db.execute(
            "INSERT INTO invoice_events(invoice_id, action, actor_id, note) VALUES(?,?,?,?)",
            (invoice_id, status if status != 'NEW' else 'NOTE', actor_id, note),
        )
        await db.commit()


# — история по заявке (если нужно где-то показать)
async def list_invoice_events(invoice_id: int) -> List[Tuple[int, int, int, Optional[int], str, Optional[str]]]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, invoice_id, ts, actor_id, action, note FROM invoice_events WHERE invoice_id=? ORDER BY id ASC",
            (invoice_id,),
        )
        return await cur.fetchall()


# ------------------------- MANAGER MODE (ожидание файла) -------------------------
async def set_mode(manager_id: int, invoice_id: int, action: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO manager_mode(manager_id, invoice_id, action)
            VALUES(?,?,?)
            ON CONFLICT(manager_id) DO UPDATE SET invoice_id=excluded.invoice_id, action=excluded.action
            """,
            (manager_id, invoice_id, action),
        )
        await db.commit()


async def get_mode(manager_id: int) -> Optional[tuple[int, str]]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT invoice_id, action FROM manager_mode WHERE manager_id=?", (manager_id,))
        row = await cur.fetchone()
        return (row[0], row[1]) if row else None


async def clear_mode(manager_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM manager_mode WHERE manager_id=?", (manager_id,))
        await db.commit()


# ------------------------- BACKUP -------------------------
async def sqlite_checkpoint():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        await db.commit()


async def sqlite_backup_once():
    # BACKUP_DIR может быть строкой — приведём к Path
    bdir = Path(BACKUP_DIR) if not isinstance(BACKUP_DIR, Path) else BACKUP_DIR
    bdir.mkdir(parents=True, exist_ok=True)

    ts = time.strftime("%Y%m%d_%H%M%S")
    path = bdir / f"bot_{ts}.sqlite"

    backup_str = path.as_posix().replace("'", "''")
    sql = f"VACUUM INTO '{backup_str}'"

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(sql)
        await db.commit()
    return path


# === СВОДНОЕ СОСТОЯНИЕ ЗАЯВКИ ===
async def get_invoice_state(invoice_id: int):
    """
    Возвращает сводное состояние заявки + флаги «намерений»:
    {
      "status": str,
      "sent_to_accounting": bool,
      "accounting_replied": bool,
      "swift_sent": bool,
      "report_requested": bool,
      "post_file_started": bool,   # нажата кнопка "Файл в группу"
      "swift_started": bool        # нажата кнопка "SWIFT"
    }
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT status FROM invoices WHERE id=?", (invoice_id,))
        row = await cur.fetchone()
        if not row:
            return None
        status = row[0]

        cur = await db.execute(
            "SELECT action FROM invoice_events WHERE invoice_id=?",
            (invoice_id,)
        )
        actions = {r[0] for r in await cur.fetchall()}

    return {
        "status": status,
        "sent_to_accounting": "SENT_TO_ACCOUNTING" in actions,
        "accounting_replied": "ACCOUNTING_REPLIED" in actions,
        "swift_sent": "SWIFT_SENT" in actions,
        "report_requested": "REPORT_REQUESTED" in actions,
        # «намерения» скрывают кнопки сразу после нажатия
        "post_file_started": "POST_FILE_INTENT" in actions,
        "swift_started": "SWIFT_FILE_INTENT" in actions,
    }


# db.py — ЗАМЕНИ list_open_invoices_with_state
async def list_open_invoices_with_state(limit: int = 20):
    """
    Список открытых заявок (status != DONE) + чек-лист действий.
    Возвращает items: {
      id, chat_id, created_ts, status,
      done: [строки], remaining: [строки]
    }
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, chat_id, created_ts, status FROM invoices WHERE status != 'DONE' ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = await cur.fetchall()

    result = []
    for iid, chat_id, created_ts, status in rows:
        st = await get_invoice_state(iid)
        if not st:
            continue

        done = []
        if st["sent_to_accounting"]:
            done.append("✅ Отправлено в бух")
        if st["accounting_replied"]:
            done.append("📎 Файл в группе")
        if st["swift_sent"]:
            done.append("📄 SWIFT отправлен")
        if st["report_requested"]:
            done.append("📝 Отчёт запрошен")

        remaining = []
        if not st["sent_to_accounting"]:
            remaining.append("✅ Отправить в бух")
        if not st["accounting_replied"]:
            remaining.append("📎 Файл в группу")
        if not st["swift_sent"]:
            remaining.append("📄 SWIFT")
        if not st["report_requested"]:
            remaining.append("📝 Запросить отчёт")

        result.append({
            "id": iid,
            "chat_id": chat_id,
            "created_ts": created_ts,
            "status": status,
            "done": done,
            "remaining": remaining,
        })
    return result



async def add_event(invoice_id: int, action: str, actor_id: int, note: Optional[str] = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO invoice_events(invoice_id, action, actor_id, note) VALUES(?,?,?,?)",
            (invoice_id, action, actor_id, note),
        )
        await db.commit()


async def save_invoice_card(manager_id: int, invoice_id: int, dm_chat_id: int, message_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO invoice_cards(manager_id, invoice_id, dm_chat_id, message_id)
            VALUES(?,?,?,?)
            ON CONFLICT(manager_id, invoice_id) DO UPDATE SET
                dm_chat_id=excluded.dm_chat_id,
                message_id=excluded.message_id
        """, (manager_id, invoice_id, dm_chat_id, message_id))
        await db.commit()

async def get_invoice_cards(invoice_id: int) -> list[tuple[int, int, int]]:
    # (manager_id, dm_chat_id, message_id)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT manager_id, dm_chat_id, message_id FROM invoice_cards WHERE invoice_id=?",
            (invoice_id,)
        )
        return await cur.fetchall()


async def get_invoice_card_for_manager(invoice_id: int, manager_id: int) -> Optional[tuple[int, int]]:
    """
    Вернёт (dm_chat_id, message_id) карточки заявки для этого менеджера,
    либо None, если карточка ещё не отправлялась.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT dm_chat_id, message_id FROM invoice_cards WHERE invoice_id=? AND manager_id=?",
            (invoice_id, manager_id),
        )
        row = await cur.fetchone()
        return (row[0], row[1]) if row else None
    

async def set_chat_status_msg(manager_id: int, chat_id: int, msg_id: int, db_path: str = DB_PATH) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO start_msg (manager_id, chat_id, msg_id)
            VALUES (?, ?, ?)
            ON CONFLICT (manager_id) DO UPDATE
            SET chat_id = excluded.chat_id,
                msg_id = excluded.msg_id
            """,
            (manager_id, chat_id, msg_id),
        )
        await db.commit()

async def get_chat_status_msg(manager_id: int, db_path: str = DB_PATH) -> Optional[tuple[int, int]]:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute("SELECT msg_id,chat_id FROM start_msg WHERE manager_id = ?", (manager_id,))
        row = await cur.fetchone()
    return row if row else None 