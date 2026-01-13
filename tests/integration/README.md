# Integration Tests

This directory contains integration tests that require external services and are not run during deployment.

## Tests

- `test_channel_extraction.py`: Live test that connects to Telegram API to extract channel content
- `test_spam_classifier.py`: Live test that uses the spam classifier with real Telegram data
- `test_logfire_message_lookup.py`: Tests that Logfire message lookup can find original messages from forwarded channel content

## Running Integration Tests

To run these tests manually:

```bash
# Run channel extraction test
python3 tests/integration/test_channel_extraction.py

# Run spam classifier test
python3 tests/integration/test_spam_classifier.py

# Run logfire message lookup test
python3 tests/integration/test_logfire_message_lookup.py
```

## Note

These tests are excluded from automated test runs and deployment because they:
- Require live Telegram API connections
- May be rate-limited or fail due to network issues
- Are intended for manual testing and development verification
