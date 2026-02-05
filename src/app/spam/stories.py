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
    media: Optional[Dict[str, Any]] = None
    media_areas: Optional[List[Dict[str, Any]]] = None

    @staticmethod
    def _media_has_links_static(
        media: Optional[Dict[str, Any]],
        media_areas: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """Check if media or media_areas contain any links that should be included in context."""
        # Check media_areas first (these can be attached to any media type)
        if media_areas:
            for area in media_areas:
                if area.get("_") == "MediaAreaUrl" and area.get("url"):
                    return True

        if not media:
            return False

        media_type = media.get("_")
        if media_type == "messageMediaWebPage":
            webpage = media.get("webpage", {})
            return bool(webpage.get("url"))
        # Add other media types as needed

        return False

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

        # Extract links from media (e.g., webpage URLs, document links)
        if self.media:
            media_links = []
            media_type = self.media.get("_")

            if media_type == "messageMediaWebPage":
                webpage = self.media.get("webpage", {})
                if webpage.get("url"):
                    media_links.append(f"Link: {webpage['url']}")
            elif media_type == "messageMediaDocument":
                # Check for media areas with URLs
                media_areas = self.media.get("media_areas", [])
                for area in media_areas:
                    if area.get("_") == "MediaAreaUrl" and area.get("url"):
                        media_links.append(f"Link: {area['url']}")
                # Could also check document attributes for links, but focus on media areas for now
            # Add other media types as needed

            if media_links:
                parts.append(f"Links: {', '.join(media_links)}")

        # Extract links from media areas (clickable areas on media)
        if self.media_areas:
            area_links = []
            for area in self.media_areas:
                if area.get("_") == "MediaAreaUrl" and area.get("url"):
                    area_links.append(f"Link: {area['url']}")

            if area_links:
                parts.append(f"Links: {', '.join(area_links)}")

        return " | ".join(parts) if parts else "Media story"


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
                media = story.get("media")

                # Check if story has any content worth including
                media_areas = story.get("media_areas")
                has_content = bool(
                    caption
                    or entities
                    or StorySummary._media_has_links_static(media, media_areas)
                )

                # If there's no text content and no media links, skip
                if not has_content:
                    continue

                summary = StorySummary(
                    id=story.get("id"),
                    date=story.get("date"),
                    caption=caption,
                    entities=entities,
                    media=media,
                    media_areas=story.get("media_areas"),
                )
                summaries.append(summary.to_string())

            if not summaries:
                return ContextResult(status=ContextStatus.EMPTY)

            return ContextResult(
                status=ContextStatus.FOUND, content="\n".join(summaries)
            )

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
