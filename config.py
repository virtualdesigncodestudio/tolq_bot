import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

def _parse_int_list(value: str) -> list[int]:
    if not value:
        return []
    return [int(x.strip()) for x in value.split(",") if x.strip()]

@dataclass
class Config:
    bot_token: str
    group_chat_id: int
    admin_ids: list[int]
    operator_ids: list[int]
    db_path: str

def load_config() -> Config:
    bot_token = os.getenv("BOT_TOKEN", "").strip()
    if not bot_token:
        raise RuntimeError("BOT_TOKEN is empty")

    group_chat_id = int(os.getenv("GROUP_CHAT_ID", "0"))
    if group_chat_id == 0:
        raise RuntimeError("GROUP_CHAT_ID is empty")

    admin_ids = _parse_int_list(os.getenv("ADMIN_IDS", ""))
    operator_ids = _parse_int_list(os.getenv("OPERATOR_IDS", ""))

    db_path = os.getenv("DB_PATH", "bot.sqlite3")

    return Config(
        bot_token=bot_token,
        group_chat_id=group_chat_id,
        admin_ids=admin_ids,
        operator_ids=operator_ids,
        db_path=db_path,
    )
