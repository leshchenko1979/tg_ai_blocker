## Active Context

- **Current Focus**: Bot behavior refinements and prompt optimization.
- **Key Decisions**:
  - **Test Classification Fixed**: Corrected classification of database tests as unit tests (not integration tests), ensuring they run during deployment.
  - **Pytest Markers**: Implemented proper test markers (`@pytest.mark.integration`) to exclude flaky integration tests from deployment.
  - **Test Organization**: Moved standalone integration test scripts to dedicated `tests/integration/` directory.
  - **Deployment Safety**: Deployment now runs only reliable unit tests (83 tests) excluding external service dependencies.
  - **Private Message Prompt Cleaned**: Removed `/start` command content from private message reply prompt to avoid redundancy and focus on core conversation context.
- **Recent Implementation**:
  - **PRD Updated**: Synchronized `PRD.md` with current codebase and memory bank (added deep context analysis details, tech stack, and commands).
  - **Unit vs Integration Separation**: Database tests using local test databases are now correctly classified as unit tests.
  - **Pytest Configuration**: Updated `pytest.ini` with markers and default exclusion of integration tests.
  - **Test Structure**: Organized integration tests (Telegram API dependent) separately from unit tests.
  - **Prompt Optimization**: Streamlined private message system prompt by removing redundant `/start` command information.
- **Immediate Next Steps**:
  - Monitor deployment reliability with improved test suite.
  - Consider adding more comprehensive integration test coverage for critical paths.

- **Testing Status**: ✅ **Testing Infrastructure Complete** - All 83 unit tests pass during deployment, integration tests properly excluded.
- **Previous Work Complete**: ✅ **Channel Content Analysis** - Successfully tested with real porn channel (@kotnikova_yana). Classifier now correctly identifies spam with 100% confidence by analyzing recent post content.
- **Prompt Optimization**: ✅ **Private Message Prompt Cleaned** - Removed redundant `/start` command content from LLM prompt for cleaner conversation context.
