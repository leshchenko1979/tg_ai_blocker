"""
Spam classification prompt building utilities.

This module handles the construction of LLM prompts for spam classification,
including system instructions, context guidance, response formats, and examples.

The module provides:
- SpamPromptBuilder: A fluent builder for constructing prompts with various guidance sections
- build_system_prompt(): Async function to build complete prompts with examples from database
- format_spam_request(): Formats message and context data for LLM input
- _format_context_section(): Internal helper for consistent context section formatting

Prompt Structure:
1. Base instructions (what spam classification is)
2. Context-specific guidance sections (linked channels, stories, account age, replies)
3. Response format specification
4. Spam classification examples from database
"""

import logging
from typing import List, Optional

from ..database.spam_examples import get_spam_examples
from ..types import ContextResult, ContextStatus, SpamClassificationContext

logger = logging.getLogger(__name__)


class SpamPromptBuilder:
    """Builder for spam classification prompts."""

    def __init__(self):
        self.prompt_parts = []

    def build_base_instructions(self) -> "SpamPromptBuilder":
        """Add the core spam classification instructions."""
        self.prompt_parts.append("""You are a spam message classifier for Telegram groups.

Your task: Analyze user messages and determine if they are spam or legitimate.
The message to classify is enclosed in >>> BEGIN MESSAGE markers.
You will also receive context information (User Bio, Linked Channel, User Stories, Account Age, Reply Context).

IMPORTANT: Do not classify the context information as spam. Only classify the message inside the markers.

## CLASSIFICATION PHILOSOPHY
Spam is not just unsolicited advertising. It is ANY content that does not add unique value to the discussion.
A comment is likely spam if it's generic, purely reactive without insight, or serves only to lure users to a profile.
Real human interaction is characterized by unique perspective, specific references, and genuine engagement.

Return a spam score from -100 to +100, where:
- Positive scores = spam (0 to 100)
- Negative scores = legitimate (-100 to 0)
- Zero = uncertain

Also provide a confidence percentage (0-100) and a brief explanation.""")
        return self

    def add_user_info_guidance(self) -> "SpamPromptBuilder":
        """Add guidance for analyzing user profile information (name, bio)."""
        self.prompt_parts.append("""
## USER INFORMATION ANALYSIS
Examine the user's name and bio for professional labels or hidden promotions.

HIGH SPAM INDICATORS:
- NAME: Professional titles ("Psychologist", "Coach", "Investor", "Realtor") or links directly in the user's display name.
- BIO: Links to Telegram bots, external sites, or "consultation" offers.
- "GHOST" PROFILES: No bio and no username combined with generic messages.

Spammers often use a "clean" name with a professional bio to build false legitimacy before posting bait comments.""")
        return self

    def add_linked_channel_guidance(self) -> "SpamPromptBuilder":
        """Add guidance for analyzing linked channel context."""
        self.prompt_parts.append("""
## LINKED CHANNEL ANALYSIS
This section contains information about a channel linked to the user's profile.

Key metrics to evaluate:
- subscribers: Number of channel subscribers
- total_posts: Total posts ever published
- age_delta: Channel age in months (format: "11mo")
- recent_posts: Content from recent channel posts (if available)

Consider the user HIGH RISK if these are true:
- subscribers < 200
- total_posts < 10
- age_delta < 5mo

CONTENT ANALYSIS: Examine recent_posts for spam indicators like:
- Pornographic content
- Advertising or promotions
- Scams or fraudulent offers
- Spam patterns

If recent_posts contain suspicious content, this is a STRONG spam indicator,
even if the current message appears innocent. Porn channels often use innocent comments
to drive traffic to their profiles.""")
        return self

    def add_stories_guidance(self) -> "SpamPromptBuilder":
        """Add guidance for analyzing user stories context."""
        self.prompt_parts.append("""
## USER STORIES ANALYSIS
This section contains content from the user's active profile stories.

Spammers frequently use stories to hide promotional content, links, or scam offers
while posting "clean" comments to lure people into viewing their profile.

Flag as HIGH SPAM if stories contain:
- Advertising links or promotions
- Calls to join channels or follow profiles
- Money-making offers, crypto, or investment schemes
- Links to other channels or external sites

This is a strong spam indicator even if the message itself appears legitimate.""")
        return self

    def add_account_age_guidance(self) -> "SpamPromptBuilder":
        """Add guidance for analyzing account age context."""
        self.prompt_parts.append("""
## ACCOUNT AGE ANALYSIS
This section shows the age of the user's profile photo.

Account age is a powerful spam indicator because spammers create new accounts
and immediately start posting spam.

Risk assessment:
- photo_age=unknown OR no photo: HIGH spam risk for new messages
- photo_age=0mo (less than 1 month): HIGH spam risk - likely brand new account
- photo_age=1mo to 3mo: MEDIUM spam risk
- photo_age > 12mo: LOW spam risk - established account with old photo""")
        return self

    def add_reply_context_guidance(self) -> "SpamPromptBuilder":
        """Add guidance for analyzing reply context."""
        self.prompt_parts.append("""
## DISCUSSION CONTEXT ANALYSIS
The user message may be a reply to another post. The content of that original post is provided in the "REPLY CONTEXT" section.

CRITICAL INSTRUCTION:
1. The "REPLY CONTEXT" is NOT the message you are classifying.
2. It often contains the spam message that the user is replying to (e.g. asking a question about a spam offer).
3. DO NOT classify the user's message as spam just because the "REPLY CONTEXT" is spam.
4. ONLY use this context to check if the user's reply is RELEVANT to the conversation.

HIGH SPAM INDICATOR: User replies that are completely unrelated to the discussion topic.
This is a common scam tactic: post irrelevant comments to "befriend" users,
then send investment/crypto offers via private messages.

Signs of irrelevant replies:
- Reply ignores the main topic of the original post
- Shifts to personal topics (books, movies, hobbies) with no connection
- Generic phrases like "interesting" or "I agree" without specific reference
- Self-promotion disguised as "helpful advice" on unrelated topics""")
        return self

    def add_knowledge_sharing_guidance(self) -> "SpamPromptBuilder":
        """Add guidance for detecting bait based on sharing materials or knowledge."""
        self.prompt_parts.append("""
## KNOWLEDGE SHARING & BAIT DETECTION
A frequent spam tactic is offering "free" materials to lure users into private messages or external channels.

HIGH SPAM INDICATORS:
- BAIT OFFERS: "I have a free book/course/intensity", "I can share my material", "Write to me and I'll send you the link".
- VAGUE "HELP": Offering help or sharing experience in a way that requires leaving the current discussion.
- "KARMA" BAIT: Using phrases like "giving away for free", "believing in karma", or "just want to help" to appear altruistic while posting advertisements.

Genuine human sharing is usually direct or occurs naturally within the conversation flow without being the primary purpose of the message.""")
        return self

    def add_ai_generated_content_guidance(self) -> "SpamPromptBuilder":
        """Add guidance for detecting AI-generated content and unusual emoji usage."""
        self.prompt_parts.append("""
## AI-GENERATED CONTENT & EMOJI DETECTION
A major spam indicator is the use of AI to generate comments that appear "clean" but add no value. This is often combined with unusual emoji patterns.

HIGH SPAM INDICATORS:
1. ROBOTIC TONE:
   - Message is a generic rephrasing or summary of the "REPLY CONTEXT".
   - Phrasing is overly polite, hollow, or reads like an automated summary (e.g., "This post discusses...", "Basically, the writer says...").
   - Zero unique contribution, personal opinion, or genuine human insight.

2. UNUSUAL EMOJI USAGE:
   - Excessive use of emojis (more than 3-4 in a short comment).
   - Unusual placement (e.g., emojis between words where they don't make sense).
   - Using emojis as "visual noise" to grab attention or bypass filters.
   - Real humans use emojis sparingly to express emotion, while spammers use them to clutter the view.

These AI signatures are strong indicators of spam REGARDLESS of whether the profile has promotional links in stories or linked channels. The goal of such posts is to clutter the discussion and lure users to a bot-controlled profile.""")
        return self

    def add_response_format(self) -> "SpamPromptBuilder":
        """Add the required response format specification."""
        self.prompt_parts.append("""
## RESPONSE FORMAT
Always respond with valid JSON in this exact format:
{
    "is_spam": true/false,
    "confidence": 0-100,
    "reason": "Причина такой классификации и на основании каких элементов входящих данных сделан такой вывод. Пиши по-русски."
}

## SPAM CLASSIFICATION EXAMPLES""")
        return self

    async def add_spam_examples(
        self, admin_ids: Optional[List[int]] = None
    ) -> "SpamPromptBuilder":
        """Add spam examples from the database."""
        try:
            examples = await get_spam_examples(admin_ids)

            for example in examples:
                # Create context from example data
                example_context = SpamClassificationContext(
                    name=example.get("name"),
                    bio=example.get("bio"),
                    linked_channel=ContextResult(
                        status=ContextStatus.FOUND,
                        content=example.get("linked_channel_fragment"),
                    )
                    if example.get("linked_channel_fragment")
                    else None,
                    stories=ContextResult(
                        status=ContextStatus.FOUND,
                        content=example.get("stories_context"),
                    )
                    if example.get("stories_context")
                    else None,
                    reply=example.get("reply_context"),
                    account_age=ContextResult(
                        status=ContextStatus.FOUND,
                        content=example.get("account_age_context"),
                    )
                    if example.get("account_age_context")
                    else None,
                )

                example_request = format_spam_request(
                    text=example["text"],
                    context=example_context,
                )

                is_spam_ex = example["score"] > 0
                confidence_ex = abs(example["score"])

                self.prompt_parts.append(f"""
{example_request}
<ответ>
{{
    "is_spam": {"true" if is_spam_ex else "false"},
    "confidence": {confidence_ex}
}}
</ответ>""")
        except Exception as e:
            logger.warning(f"Failed to load spam examples for prompt: {e}")

        return self

    def build(self) -> str:
        """Build the complete prompt."""
        return "\n".join(self.prompt_parts)


async def build_system_prompt(
    admin_ids: Optional[List[int]] = None,
    context: Optional[SpamClassificationContext] = None,
) -> str:
    """
    Build a complete spam classification system prompt.

    Args:
        admin_ids: Optional list of admin IDs for personalized examples
        context: Optional spam classification context for prompt guidance flags

    Returns:
        Complete system prompt string
    """
    builder = SpamPromptBuilder().build_base_instructions()

    # Always include user info guidance as it's fundamental
    builder.add_user_info_guidance()

    if context is None:
        context = SpamClassificationContext()

    if context.include_linked_channel_guidance:
        builder.add_linked_channel_guidance()
    if context.include_stories_guidance:
        builder.add_stories_guidance()
    if context.include_account_age_guidance:
        builder.add_account_age_guidance()
    if context.include_reply_guidance:
        builder.add_reply_context_guidance()
    if context.include_ai_detection_guidance:
        builder.add_ai_generated_content_guidance()
        # Knowledge sharing is often linked with AI content or generic bait
        builder.add_knowledge_sharing_guidance()

    builder.add_response_format()

    # Add examples (async operation)
    await builder.add_spam_examples(admin_ids)
    return builder.build()


def _format_context_section(
    section_name: str, context_result: Optional[ContextResult]
) -> str:
    """
    Format a context section based on its result status.

    Args:
        section_name: Name of the context section (e.g., "LINKED CHANNEL INFO")
        context_result: ContextResult object containing status and content

    Returns:
        Formatted section string, or empty string if section should be skipped
    """
    if not context_result:
        return ""

    status = context_result.status.name

    if status == "SKIPPED":
        return ""  # Skip section entirely for missing prerequisites

    if status == "EMPTY":
        # Use user-friendly messages for empty results
        empty_messages = {
            "LINKED CHANNEL INFO": "no channel linked",
            "USER STORIES CONTENT": "no stories posted",
            "ACCOUNT AGE INFO": "no photo on the account",
        }
        message = empty_messages.get(section_name, "no data available")
        return f"{section_name}:\n{message}\n\n"

    if status == "FAILED":
        return f"{section_name}:\nverification failed: {context_result.error}\n\n"

    if status == "FOUND":
        # Handle objects with custom prompt formatting
        if hasattr(context_result.content, "to_prompt_fragment"):
            content = context_result.content.to_prompt_fragment()
        else:
            content = str(context_result.content) if context_result.content else ""
        return f"{section_name}:\n{content}\n\n"

    return ""


def format_spam_request(
    text: str,
    context: Optional[SpamClassificationContext] = None,
) -> str:
    """
    Format a spam classification request for the LLM.

    Args:
        text: Message text to classify
        context: Spam classification context with all optional context data

    Returns:
        str: Formatted request with clear section headers
    """
    # Use empty context if none provided
    if context is None:
        context = SpamClassificationContext()

    request_parts = [
        "MESSAGE TO CLASSIFY (Analyze this content):",
        f">>> BEGIN MESSAGE\n{text}\n<<< END MESSAGE",
        "",
    ]

    # Add basic user information
    if context.name:
        request_parts.extend([f"USER NAME:\n{context.name}", ""])

    if context.bio:
        request_parts.extend([f"USER BIO:\n{context.bio}", ""])

    # Add context sections using the helper function
    request_parts.append(
        _format_context_section("LINKED CHANNEL INFO", context.linked_channel)
    )
    request_parts.append(
        _format_context_section("USER STORIES CONTENT", context.stories)
    )
    request_parts.append(
        _format_context_section("ACCOUNT AGE INFO", context.account_age)
    )

    # Handle reply context (special case due to different formatting)
    if context.reply is not None:
        if context.reply == "[EMPTY]":
            request_parts.append(
                "REPLY CONTEXT (Original post being replied to):\n[checked, none found]\n\n"
            )
        else:
            request_parts.append(f"""REPLY CONTEXT (The post the user is replying to - DO NOT CLASSIFY THIS):
>>> BEGIN CONTEXT
{context.reply}
<<< END CONTEXT

""")

    return "\n".join(request_parts)
