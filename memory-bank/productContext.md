## Product Context

- **Target Users**: Telegram administrators managing active groups or channel discussions who need proactive, automated spam control without constant manual oversight.
- **Core Value Proposition**: Deliver immediate protection against spam and scam activity by combining:
  - **LLM-based classification** for nuanced text analysis.
  - **Deep Context Analysis**: Inspection of linked channels and **User Stories** to catch "Trojan horse" spam (benign message, toxic profile).
  - **Custom spam examples** for community-specific tuning.
  - **Automated enforcement** actions (delete, ban).
- **User Journeys**:
  - Onboard bot into a group, grant admin permissions, configure moderation mode, and observe automated clean-up.
  - Receive alerts about suspicious messages, approve or override actions, and curate trusted/blocked user lists.
  - Purchase Telegram Star packages, monitor balance consumption, and review billing history.
- **Experience Principles**:
  - Fast, transparent feedback: instant notifications with consistent HTML formatting, clear reason codes, and undo paths for mistakes.
  - High reliability: minimal false positives, safe handling of admin/service messages, graceful degradation when credits run low, and robust error recovery with admin notifications.
  - Empowered control: admins can tune moderation levels, manage exceptions, and contribute labeled examples for continuous improvement.
- **Analytics Guardrails**:
  - Mixpanel events key off the administrator’s ID (`admin_id`) and treat group context (`group_id`, etc.) as event properties rather than identifiers.
  - Financial transactions mirror into the database; all other behavioral events stay Mixpanel-only to preserve the single source of truth.
- **Success Metrics**: Reduced spam incidents, sustained admin engagement, conversion to paid plans, and positive sentiment in bot interactions.
