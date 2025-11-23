import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import logfire

from .mtproto_client import MtprotoHttpError, get_mtproto_client

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
async def collect_user_stories(user_id: int) -> Optional[str]:
    """
    Collects stories for a user and formats them into a summary string.
    Returns None if no stories found or error occurs.
    """
    client = get_mtproto_client()

    with logfire.span("Collecting user stories", user_id=user_id):
        try:
            # stories.getPeerStories requires a peer input.
            # For a user, we can try using the user ID directly if we have an access hash,
            # but usually we just provide the ID and hope the bridge/client resolves it.
            # The bridge's 'resolve=True' should handle basic ID->InputPeer resolution
            # if the user is known to the session.

            # Only try to get pinned stories as spam relies on them
            # stories.getPeerStories often returns nothing for non-contacts
            stories_data = []

            try:
                pinned_response = await client.call(
                    "stories.getPinnedStories",
                    params={"peer": user_id, "offset_id": 0, "limit": 5},
                    resolve=True,
                )
                stories_data = pinned_response.get("stories", [])
            except Exception as e:
                # Fallback to regular stories if pinned fails, or just log
                logger.debug(f"Failed to fetch pinned stories for {user_id}: {e}")
                # Optional: try regular stories if pinned fails?
                # For now let's rely on pinned as requested, but maybe keep regular as fallback?
                # User said "all spam relies on the pinned stories... so we need to get only them"
                # But regular getPeerStories might return active 24h stories which could also be spam.
                # Let's prioritize pinned but maybe keep regular as a backup if pinned is empty?
                # Re-reading: "so we need to get only them".
                # Okay, strict interpretation: ONLY pinned stories.

            if not stories_data:
                return None

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
                return None

            return "\n".join(summaries)

        except MtprotoHttpError as e:
            logger.info(
                "Failed to fetch user stories",
                extra={"user_id": user_id, "error": str(e)},
            )
            return None
        except Exception as e:
            logger.error(
                "Unexpected error fetching user stories",
                extra={"user_id": user_id, "error": str(e)},
                exc_info=True,
            )
            return None
