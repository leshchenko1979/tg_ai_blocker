# Spam Tactics

This document tracks known spam tactics and examples used to improve the classification performance of the TG AI Blocker.

## Overview of Spam Philosophy
The project defines spam not just as unsolicited advertising, but as **any content that does not add value or expand upon the topic of discussion**. In community moderation, the goal is to maximize the ratio of value to comment volume.

## Common Spam Tactics

### 1. The Multi-Step Social Engineering Attack
*   **Method**: A bot leaves a seemingly harmless or slightly relevant comment (e.g., "Interesting post!", "Tell me more").
*   **Hook**: The bot's profile has an attractive or professional photo to entice users to click.
*   **Payload**:
    *   **User Stories**: Links to malicious sites or "offers" are hidden in the user's stories (often using stickers or captions).
    *   **Linked Channels**: The user profile points to a "proxy" channel containing a single post with a link to the main scam channel.
*   **Why it works**: It avoids automated text-based filters in the initial comment.

### 2. Contextual Imitation (The "Crypto Escrow" Play)
*   **Method**: A coordinated group of clean-looking accounts (no bio/name ads) simulates a realistic discussion relevant to the community.
*   **Example**: In a real estate group, discussing "how to pay for an apartment with crypto" and then introducing a "trusted escrow service."
*   **Weakness**: Often uses inconsistent profile data (e.g., male photos with female names) and overly positive sentiment towards a specific service.

### 3. Interactive/Rich Media Spam
*   **Buttons**: Messages containing inline buttons leading to external sites (casinos, news).
*   **Forwarded Content**: Using the "Forward" feature to bypass simple message filters.
*   **Links in Text**: Long, sensationalist stories (e.g., fake news) with links "for more info" embedded in the text.

### 4. Low-Effort/Generic Noise
*   **Generic Praise**: "Great video!", "Nice post!", "Love it! ❤️"
*   **Single Commands**: Messages containing only bot commands like `/help`, `/give`, etc.

### 5. Direct Spamming Tactics
*   **Raw Link Injection**: Posting direct links to Telegram channels, bots, or external sites without any context.
*   **"Easy Money" Offers**: "Earn 2500 rub/hour", "Work from home for teens", etc.
*   **Technical Help Bait**: Asking for technical help (e.g., "How to attach Excel to CRM") to lure people into a discussion that leads to a paid service or malicious site.

## Mostly Used Spam Tactics

Based on current trends, the most frequent tactics are:
1.  **The "Attractive Profile" Hook**: Harmless messages combined with aggressive ads in Bio/Stories (Trojan Horse).
2.  **AI-Generated Summaries**: Using LLMs to generate a "summary" of the post to appear helpful while building "reputation" or testing filters.
3.  **Service Promotion via Bots**: Recommending a specific Telegram bot as a "helpful tool" for the problem discussed in the post.
4.  **Native Ad Imitation**: Starting a conversation about a specific niche (real estate, crypto) to eventually drop a "recommendation".

## Recent Examples from Database

| Date | Name | Score | Tactics |
| :--- | :--- | :--- | :--- |
| 2026-02-05 | 𝚗𝚎𝚐𝚎𝚜𝚎 | -100 | Ad for @Marypsyupbot bot, new account (0mo) |
| 2026-01-29 | Кирилл | -100 | Technical help request (potential hook), no channel/stories |
| 2026-01-24 | Vladimir U | -100 | General investment "help" offer, responding vaguely to post |
| 2026-01-22 | Алена | -100 | Turkey business/real estate investment request, new-ish photo (2mo) |
| 2026-01-22 | (: | -100 | Single command `/give` |
| 2025-01-15 | Liliya Vlasova | -100 | Irrelevant generic compliment, unknown account age |

## Key Indicators for Detection
*   **Account Age**: New accounts are significantly more likely to be spam.
*   **Profile Richness**: Lack of bio, username, or stories (though some advanced bots now use these).
*   **Context Relevance**: Does the message actually address the specific points in the original post?
*   **User Stories**: Presence of links or "call to action" stickers in stories.
*   **Linked Channel Metrics**: Low subscriber count or new channel creation date.
