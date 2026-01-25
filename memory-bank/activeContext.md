## Active Context

- **Current Focus**: Advanced Context Collection - implemented on-demand user bot subscription for comprehensive spam detection.
- **Key Decisions**:
  - **On-Demand Subscription**: User bot subscribes to monitored chats when needed for context collection, rather than proactively on bot addition.
  - **Unified Context Collection**: Single subscription check at the top level enables both linked channel and stories collection for users without usernames.
  - **Simplified MTProto Calls**: Replaced fallback call patterns with direct single calls for better performance and clarity.
  - **Code Consolidation**: Merged subscription utilities into single module with DRY helper functions.
- **Recent Implementation**:
  - **User Bot Subscription System**: ✅ **Complete** - On-demand subscription to monitored chats enables context collection for users without usernames using MTProto user_id resolution.
  - **Context Collection Enhancement**: ✅ **Complete** - Both linked channel and stories collection now work for all users, regardless of username availability.
  - **MTProto Optimization**: ✅ **Complete** - Simplified all MTProto API calls to use single identifiers instead of fallback patterns.
  - **Code Quality**: ✅ **Complete** - Merged utility modules, eliminated circular imports, and achieved clean single-responsibility architecture.
- **Immediate Next Steps**:
  - Run LLM model evaluation to establish baseline performance metrics.
  - Monitor system stability and context collection effectiveness.
  - Consider adding subscription status caching to reduce API calls.