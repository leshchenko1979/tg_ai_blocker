import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import logfire

from .context_types import ContextResult, ContextStatus
from ..common.mtproto_client import MtprotoHttpError, get_mtproto_client

logger = logging.getLogger(__name__)


@dataclass
class StorySummary:
    id: int
    date: int
    caption: Optional[str] = None
    entities: Optional[List[Dict[str, Any]]] = None

    def to_string(self) -> str:
        parts = []
        if self.caption:
            parts.append(f"Caption: {self.caption}")
        if self.entities:
            links = []
            for entity in self.entities:
                if entity.get("_") == "messageEntityTextUrl":
                    links.append(f"Link: {entity.get('url')}")
                elif entity.get("_") == "messageEntityUrl":
                    # URL is likely in the text/caption itself, but good to note
                    pass
            if links:
                parts.append(f"Links: {', '.join(links)}")
        return " | ".join(parts) if parts else "Media story"


@logfire.instrument()
async def collect_user_stories(
    user_id: int, username: Optional[str] = None, chat_id: Optional[int] = None
) -> ContextResult[str]:
    """
    Collects stories for a user and formats them into a summary string.
    Returns ContextResult with appropriate status.
    """
    client = get_mtproto_client()

    with logfire.span(
        "Collecting user stories", user_id=user_id, username=username, chat_id=chat_id
    ):
        try:
            # Set up identifier: prefer username, but use user_id if no username
            # (subscription check is handled at higher level)
            peer_identifier = username if username else user_id

            try:
                peer_response = await client.call(
                    "stories.getPeerStories",
                    params={"peer": peer_identifier},
                    resolve=True,
                )
                stories_data = peer_response.get("stories", {}).get("stories", [])
            except MtprotoHttpError as e:
                logger.debug(
                    f"Failed to fetch pinned stories for identifier {peer_identifier}: {e}"
                )
                return ContextResult(status=ContextStatus.FAILED, error=str(e))

            if not stories_data:
                return ContextResult(status=ContextStatus.EMPTY)

            summaries = []
            for story in stories_data:
                # Skip deleted stories
                if story.get("_") == "storyItemDeleted":
                    continue

                caption = story.get("caption")
                entities = story.get("entities")

                # If there's no text content, we might skip or just note it's media
                if not caption and not entities:
                    continue

                summary = StorySummary(
                    id=story.get("id"),
                    date=story.get("date"),
                    caption=caption,
                    entities=entities,
                )
                summaries.append(summary.to_string())

            if not summaries:
                return ContextResult(status=ContextStatus.EMPTY)

            return ContextResult(status=ContextStatus.FOUND, content="\n".join(summaries))

        except MtprotoHttpError as e:
            logger.info(
                "Failed to fetch user stories",
                extra={"user_id": user_id, "error": str(e)},
            )
            return ContextResult(status=ContextStatus.FAILED, error=str(e))
        except Exception as e:
            logger.error(
                "Unexpected error fetching user stories",
                extra={"user_id": user_id, "error": str(e)},
                exc_info=True,
            )
            return ContextResult(status=ContextStatus.FAILED, error=str(e))
