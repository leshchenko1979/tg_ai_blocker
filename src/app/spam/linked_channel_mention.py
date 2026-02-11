"""
Extract first channel/chat mention from text (e.g. bio or message).

Used for linked channel collection from bio and message when profile has no linked channel.
"""

import re
from typing import Any, List, Optional

# Telegram username: 5-32 characters, [a-zA-Z0-9_]
USERNAME_PATTERN = re.compile(r"[a-zA-Z0-9_]{5,32}")
MENTION_REGEX = re.compile(r"@([a-zA-Z0-9_]{5,32})")
T_ME_USERNAME_REGEX = re.compile(
    r"t\.me/([a-zA-Z0-9_]{5,32})(?:\s|$|/|\))", re.IGNORECASE
)


def extract_first_channel_mention(
    text: str,
    entities: Optional[List[Any]] = None,
) -> Optional[str]:
    """
    Extract the first candidate channel/chat username from text.

    Prefers Telegram message entities (mention, text_link) when provided.
    Falls back to regex on raw text for @username and t.me/username.

    Args:
        text: Raw text (e.g. bio, message text or caption).
        entities: Optional list of Telegram MessageEntity dicts or objects
                  (with type, offset, length, and optionally url).

    Returns:
        First candidate username without @, or None if none found.
    """
    if not text or not isinstance(text, str):
        return None

    # Prefer entities for exact boundaries
    if entities:
        for entity in entities:
            if isinstance(entity, dict):
                etype = entity.get("type")
                if etype == "mention":
                    offset = entity.get("offset", 0)
                    length = entity.get("length", 0)
                    if offset is not None and length:
                        mention = text[offset : offset + length].lstrip("@")
                        if USERNAME_PATTERN.fullmatch(mention):
                            return mention
                elif etype == "text_link":
                    url = entity.get("url") or ""
                    match = re.search(
                        r"t\.me/([a-zA-Z0-9_]{5,32})(?:/|$|\?)", url, re.I
                    )
                    if match:
                        return match.group(1)
            else:
                # aiogram MessageEntity-like object
                etype = getattr(entity, "type", None)
                if etype == "mention":
                    offset = getattr(entity, "offset", 0) or 0
                    length = getattr(entity, "length", 0) or 0
                    if length:
                        mention = text[offset : offset + length].lstrip("@")
                        if USERNAME_PATTERN.fullmatch(mention):
                            return mention
                elif etype == "text_link":
                    url = getattr(entity, "url", None) or ""
                    match = re.search(
                        r"t\.me/([a-zA-Z0-9_]{5,32})(?:/|$|\?)", url, re.I
                    )
                    if match:
                        return match.group(1)

    # Fallback: regex on text
    m = MENTION_REGEX.search(text)
    if m:
        return m.group(1)
    m = T_ME_USERNAME_REGEX.search(text)
    if m:
        return m.group(1)
    return None
