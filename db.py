import aiosqlite
from typing import Optional

CREATE_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS users (
  telegram_user_id INTEGER PRIMARY KEY,
  name TEXT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tickets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  user_display_name TEXT NULL,
  category TEXT NOT NULL,
  question_text TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'new',
  operator_user_id INTEGER NULL,
  group_chat_id INTEGER NOT NULL,
  group_message_id INTEGER NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

class DB:
    def __init__(self, path: str):
        self.path = path
        self.conn: Optional[aiosqlite.Connection] = None

    async def connect(self):
        self.conn = await aiosqlite.connect(self.path)
        await self.conn.executescript(CREATE_SQL)
        await self.conn.commit()

    async def close(self):
        if self.conn:
            await self.conn.close()

    async def upsert_user(self, telegram_user_id: int, name: Optional[str]):
        if name is None:
            await self.conn.execute(
                "INSERT OR IGNORE INTO users (telegram_user_id) VALUES (?)",
                (telegram_user_id,),
            )
        else:
            await self.conn.execute(
                """
                INSERT INTO users (telegram_user_id, name)
                VALUES (?, ?)
                ON CONFLICT(telegram_user_id) DO UPDATE SET name=excluded.name
                """,
                (telegram_user_id, name),
            )
        await self.conn.commit()

    async def create_ticket(self, user_id, user_display_name, category, question_text, group_chat_id):
        cur = await self.conn.execute(
            """
            INSERT INTO tickets (user_id, user_display_name, category, question_text, group_chat_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, user_display_name, category, question_text, group_chat_id),
        )
        await self.conn.commit()
        return cur.lastrowid

    async def set_ticket_group_message(self, ticket_id, group_message_id):
        await self.conn.execute(
            """
            UPDATE tickets SET group_message_id=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (group_message_id, ticket_id),
        )
        await self.conn.commit()

    async def find_ticket_by_group_message(self, group_chat_id, group_message_id):
        cur = await self.conn.execute(
            """
            SELECT id, user_id FROM tickets
            WHERE group_chat_id=? AND group_message_id=?
            """,
            (group_chat_id, group_message_id),
        )
        return await cur.fetchone()
  
    async def find_ticket_by_id(self, ticket_id: int):
        cur = await self.conn.execute(
            "SELECT user_id, group_chat_id, group_message_id FROM tickets WHERE id=?",
            (ticket_id,)
        )
        return await cur.fetchone()

    async def mark_ticket_answered(self, ticket_id, operator_user_id):
        await self.conn.execute(
            """
            UPDATE tickets
            SET status='answered', operator_user_id=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (operator_user_id, ticket_id),
        )
        await self.conn.commit()
