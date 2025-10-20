from dataclasses import dataclass
from typing import Optional
from aiogram.types import Message
from aiogram.enums import ContentType
from html import escape as _html_escape

@dataclass
class AuthorInfo:
    name: str
    username: Optional[str]
    user_id: int


def format_author(author: AuthorInfo) -> str:
    name = author.name or "Unknown"
    if author.username:
        return f"{name} (@{author.username}, id={author.user_id})"
    return f"{name} (id={author.user_id})"


def bot_was_tagged(msg: Message, bot_username: Optional[str], bot_id: Optional[int]) -> bool:
    """Detect if the *bot* was mentioned/tagged in the message."""
    if not (msg.entities or msg.caption_entities):
        return False
    entities = msg.entities or msg.caption_entities or []
    text = msg.text or msg.caption or ""
    for ent in entities:
        if ent.type == "mention" and bot_username:
            mention = text[ent.offset : ent.offset + ent.length]
            if mention.lower() == f"@{bot_username.lower()}":
                return True
        if ent.type == "text_mention" and ent.user and bot_id and ent.user.id == bot_id:
            return True
    return False


SUPPORTED_MEDIA = {
    ContentType.DOCUMENT, ContentType.PHOTO, ContentType.VIDEO,
    ContentType.AUDIO, ContentType.VOICE, ContentType.ANIMATION, ContentType.VIDEO_NOTE
}



def escape_html(s: str | None) -> str:
    """Экранирует текст для parse_mode='HTML' ( &, <, > )."""
    if s is None:
        return ""
    return _html_escape(str(s), quote=False)