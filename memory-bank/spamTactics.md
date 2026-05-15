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

### 6. Knowledge Sharing Bait
*   **Method**: Offering "free" materials (books, courses, intensities, checklists) to lure users into private messages or external channels.
*   **Hook**: Phrasing that sounds altruistic or helpful (e.g., "I can share for free", "I believe in karma", "I have this saved").
*   **Weakness**: The offer is usually too good to be true or doesn't fit naturally into a technical discussion without being the primary focus.

### 7. Professional Name Authority
*   **Method**: Including professional titles or credentials directly in the Telegram display name (e.g., "Ivan | Real Estate Broker", "Dr. Alex | Crypto Advisor").
*   **Goal**: To build immediate, false authority for their comments, making bait links in bio or stories more believable.

### 8. The Proxy (Gasket) Infrastructure
*   **Method**: Spammer account -> Channel-proxy (one post/button) -> Main scam channel.
*   **Goal**: To break the direct link between the spammer and the main resource. If the spammer is banned, Telegram's automated systems won't automatically ban the main channel because it wasn't mentioned in the initial message.
*   **Indicators**: Links in bio or message leading to very young channels with only 1-2 posts and high subscriber counts or buttons leading elsewhere.

### 9. Knowledge Sharing to Pig Butchering/Extortion
*   **Trigger**: Harmless offer of "free" materials (books, courses, archives).
*   **Phase 1 (The Hook)**: "Write to my work account/assistant."
    *   **Reason**: Avoid ban on the spamming account; avoid Telegram's "first message" detection (bypassed when user writes first).
*   **Phase 2 (Relationship)**: Sending the actual promised file + small talk.
*   **Phase 3 (Investment)**: Intro to a "nephew/advisor" who helps earn on crypto. High urgency ("only 2 slots left").
*   **Phase 4 (The Drain)**: Small "earn" wins (allowed 1-2 times) -> Malicious link/transaction drains the whole wallet.
*   **Phase 5 (Extortion)**: Revealing the scam -> Demanding more money to "unlock" the wallet -> Threats about "illegal financing" (e.g., AFU) and reporting to FSB/police.

### 10. Benign-Then-Edit ("Same message_id" spam)
*   **Method**: Send a **short, harmless line** (e.g. «Привет», «Спасибо», «Интересно»), pass moderation or human glance, then **edit the same message** into a full spam payload (vacancies, phones, crypto, links).
*   **Why it works**:
    *   Many bots only handle **`message`** updates and **ignore `edited_message`**, so the spam body **never goes through classification** again.
    *   Systems that cache `(chat_id, message_id, text)` for admin workflows (e.g. forwarded spam examples, auto-delete) keep the **original** text — lookup by forwarded spam text **misses**, so cleanup targets are lost.
    *   **Forward metadata** shows the spam text and sender, but **no “new post” event** fires for the toxic revision.
*   **Weakness / detection hints**: Same `message_id` with **`edit_date`** present; abrupt jump from trivial text to ads; pattern repeatable across accounts.
*   **Confirmed case (2026-05)**: Account in a real-estate discussion supergroup — message **17037** first «Привет», minutes later edited to helper-recruitment spam with phone `+79293619175`; production traces showed initial text processed via `handle_moderated_message`, spam revision delivered only as **`edited_message`** (filtered out by `updates_filter`: `~F.edited_message`).
*   **Mitigation (2026-05)**: **Probation period** — new approvals stay on full pipeline (including `edited_message` handler) until `moderation_event_count >= probation_min_events`. Lookup cache updated on classify/edit paths. **Caveat**: members grandfathered at deploy keep trusted edit skip; tactic 10 can still affect them until trusted-user edit moderation is built.

## Mostly Used Spam Tactics

Based on current trends, the most frequent tactics are:
1.  **The "Attractive Profile" Hook**: Harmless messages combined with aggressive ads in Bio/Stories (Trojan Horse).
2.  **AI-Generated Summaries**: Using LLMs to generate a "summary" of the post to appear helpful while building "reputation" or testing filters.
3.  **Service Promotion via Bots**: Recommending a specific Telegram bot as a "helpful tool" for the problem discussed in the post.
4.  **Knowledge Sharing Bait**: Offering free PDFs or courses to start a private conversation.
5.  **Native Ad Imitation**: Starting a conversation about a specific niche (real estate, crypto) to eventually drop a "recommendation".

**Emerging (monitor)**: **Benign-then-edit** (tactic 10) — partially mitigated for new probation members; monitor grandfathered trusted users on edits.

## Confirmed Spam Examples from Database

Полный выгруз 127 подтверждённых примеров спама (score=100, confirmed=true) с контекстом — в файле **memory-bank/confirmedSpamExamples.md**.

Источник: PostgreSQL `spam_examples` (2026-03-14). Каждый пример содержит: text, name, bio, linked_channel_fragment, stories_context, reply_context, account_signals_context.

## Key Indicators for Detection
*   **Edits**: Telegram supplies **`edit_date`** on messages; a trivial first revision replaced by high-risk content is suspicious (especially combined with phones/links).
*   **Account Age**: New accounts are significantly more likely to be spam.
*   **Profile Richness**: Lack of bio, username, or stories (though some advanced bots now use these).
*   **Context Relevance**: Does the message actually address the specific points in the original post?
*   **User Stories**: Presence of links or "call to action" stickers in stories.
*   **Linked Channel Metrics**: Low subscriber count or new channel creation date.
