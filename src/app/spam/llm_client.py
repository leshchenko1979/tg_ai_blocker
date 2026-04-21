"""LLM client for spam classification — metrics only."""

import logfire

# Metrics (retained from original implementation)
classification_confidence_gauge = logfire.metric_gauge("spam_score")
attempts_histogram = logfire.metric_histogram("attempts")
