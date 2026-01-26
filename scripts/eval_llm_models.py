#!/usr/bin/env python3
"""
LLM Models Evaluation Script

This script evaluates the functionality of LLM models in src/app/common/llms.py
by testing spam classification accuracy using manually labeled examples from the spam_examples database.

GROUND TRUTH:
- Uses spam_examples database with known scores (positive = spam, negative = legitimate)
- Tests all available context fields: text, name, bio, linked_channel_fragment, stories_context, reply_context, account_age_context
- Does NOT use production Logfire results as ground truth (classifier outputs aren't ground truth)

USAGE:
    # Evaluate all models with default settings (100 examples)
    python3 scripts/eval_llm_models.py

    # Evaluate specific models with 50 examples
    python3 scripts/eval_llm_models.py --models "google/gemma-3-27b-it:free" "meta-llama/llama-3.3-70b-instruct:free" --limit 50

    # Include admin-specific examples
    python3 scripts/eval_llm_models.py --admin-ids 12345 67890

REQUIREMENTS:
    - OpenRouter API key (OPENROUTER_API_KEY environment variable)
    - Database access (configured via .env)
    - Python dependencies loaded via the project's environment
    - Optional: Logfire read token (LOGFIRE_READ_TOKEN) for functionality testing

OUTPUT:
    - Console summary with accuracy metrics per model (accuracy, precision, recall, F1)
    - Confusion matrix and error analysis for top-performing model
    - Success rates and response times
    - Error breakdowns by type (rate limits, location restrictions, etc.)

METRICS:
    - Accuracy: (correct_predictions) / total_predictions
    - Precision: true_positives / (true_positives + false_positives)
    - Recall: true_positives / (true_positives + false_negatives)
    - F1 Score: 2 * (precision * recall) / (precision + recall)
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import field

from tqdm import tqdm
from collections import defaultdict

# Add project root to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.WARNING, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Reduce spam classifier logging during evaluation
spam_logger = logging.getLogger("src.app.common.spam_classifier")
spam_logger.setLevel(logging.WARNING)


@dataclass
class TestCase:
    """Represents a single test case from the database."""

    text: str
    name: Optional[str] = None
    bio: Optional[str] = None
    linked_channel_fragment: Optional[str] = None
    stories_context: Optional[str] = None
    reply_context: Optional[str] = None
    account_age_context: Optional[str] = None
    ground_truth_score: int = (
        0  # The score from database (positive = spam, negative = legitimate)
    )

    @property
    def is_spam_ground_truth(self) -> bool:
        """True if this is spam according to ground truth."""
        return self.ground_truth_score > 0


@dataclass
class TestResult:
    """Result for a single test case."""

    test_case: TestCase
    predicted_score: Optional[int] = None  # None if failed
    predicted_spam: Optional[bool] = None  # None if failed
    is_correct: Optional[bool] = None  # None if failed
    response_time: float = 0.0
    error: Optional[str] = None  # Error type if failed


@dataclass
class ModelResult:
    """Results for a single model across all test cases."""

    model_name: str
    total_cases: int = 0
    successful_responses: int = 0
    true_positives: int = 0  # Predicted spam, actually spam
    false_positives: int = 0  # Predicted spam, actually legitimate
    true_negatives: int = 0  # Predicted legitimate, actually legitimate
    false_negatives: int = 0  # Predicted legitimate, actually spam
    total_response_time: float = 0.0
    errors: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    test_results: List[TestResult] = field(
        default_factory=list
    )  # Individual test case results

    @property
    def accuracy(self) -> float:
        """Overall accuracy: correct predictions / total predictions."""
        correct = self.true_positives + self.true_negatives
        total = (
            self.true_positives
            + self.true_negatives
            + self.false_positives
            + self.false_negatives
        )
        return correct / total if total > 0 else 0.0

    @property
    def precision(self) -> float:
        """Precision: true positives / (true positives + false positives)."""
        denominator = self.true_positives + self.false_positives
        return self.true_positives / denominator if denominator > 0 else 0.0

    @property
    def recall(self) -> float:
        """Recall: true positives / (true positives + false negatives)."""
        denominator = self.true_positives + self.false_negatives
        return self.true_positives / denominator if denominator > 0 else 0.0

    @property
    def f1_score(self) -> float:
        """F1 Score: 2 * (precision * recall) / (precision + recall)."""
        precision = self.precision
        recall = self.recall
        if precision + recall == 0:
            return 0.0
        return 2 * (precision * recall) / (precision + recall)

    @property
    def success_rate(self) -> float:
        """Success rate: successful responses / total attempts."""
        return (
            self.successful_responses / self.total_cases
            if self.total_cases > 0
            else 0.0
        )

    @property
    def average_response_time(self) -> float:
        """Average response time per successful request."""
        return (
            self.total_response_time / self.successful_responses
            if self.successful_responses > 0
            else 0.0
        )


async def load_test_cases_from_db(
    limit: int = 100,
    admin_ids: Optional[List[int]] = None,
) -> List[TestCase]:
    """
    Load test cases from the spam examples database.

    Ensures balanced loading of both spam (positive scores) and legitimate (negative scores) examples.

    Args:
        limit: Maximum number of test cases to load
        admin_ids: Admin IDs to include user-specific examples for

    Returns:
        List of TestCase objects with ground truth, balanced between spam and legitimate
    """
    import random
    from src.app.database.spam_examples import get_spam_examples

    logger.info(
        f"Loading up to {limit} test cases from database (admin_ids: {admin_ids})"
    )

    # Fetch examples from database
    examples = await get_spam_examples(admin_ids)

    # Convert to TestCase objects
    all_test_cases = []
    for example in examples:
        test_case = TestCase(
            text=example["text"],
            name=example.get("name"),
            bio=example.get("bio"),
            ground_truth_score=example["score"],
            linked_channel_fragment=example.get("linked_channel_fragment"),
            stories_context=example.get("stories_context"),
            reply_context=example.get("reply_context"),
            account_age_context=example.get("account_age_context"),
        )
        all_test_cases.append(test_case)

    # Separate into spam and legitimate categories
    spam_cases = [tc for tc in all_test_cases if tc.is_spam_ground_truth]
    legitimate_cases = [tc for tc in all_test_cases if not tc.is_spam_ground_truth]

    logger.info(
        f"Found {len(spam_cases)} spam examples and {len(legitimate_cases)} legitimate examples"
    )

    # Balance the selection to ensure we get both types
    selected_cases = []
    target_per_category = limit // 2  # Half for spam, half for legitimate

    # Randomly sample from each category
    if spam_cases:
        spam_sample = random.sample(
            spam_cases, min(target_per_category, len(spam_cases))
        )
        selected_cases.extend(spam_sample)

    if legitimate_cases:
        legit_sample = random.sample(
            legitimate_cases, min(target_per_category, len(legitimate_cases))
        )
        selected_cases.extend(legit_sample)

    # If we still have room, fill with remaining examples from either category
    remaining_slots = limit - len(selected_cases)
    if remaining_slots > 0:
        remaining_cases = [tc for tc in all_test_cases if tc not in selected_cases]
        if remaining_cases:
            additional = random.sample(
                remaining_cases, min(remaining_slots, len(remaining_cases))
            )
            selected_cases.extend(additional)

    # Shuffle final selection for randomness
    random.shuffle(selected_cases)

    logger.info(
        f"Loaded {len(selected_cases)} test cases: {len([tc for tc in selected_cases if tc.is_spam_ground_truth])} spam, {len([tc for tc in selected_cases if not tc.is_spam_ground_truth])} legitimate"
    )
    return selected_cases


async def load_test_cases_from_logfire(
    limit: int = 50,
    days_back: int = 7,
) -> List[TestCase]:
    """
    Load test cases from Logfire for functionality testing only.

    NOTE: These do NOT have ground truth and cannot be used for accuracy metrics.
    They are only useful for testing if models can respond successfully to real messages.

    Args:
        limit: Maximum number of messages to fetch
        days_back: How many days back to search

    Returns:
        List of TestCase objects WITHOUT ground truth (ground_truth_score = 0)
    """
    logger.info(
        f"Loading up to {limit} messages from Logfire for functionality testing"
    )

    if not os.getenv("LOGFIRE_READ_TOKEN"):
        logger.warning(
            "LOGFIRE_READ_TOKEN not set, skipping Logfire functionality tests"
        )
        return []

    try:
        from datetime import datetime, timedelta
        import asyncio
        from src.app.common.logfire_lookup import _get_client

        client = _get_client()
        start_time = datetime.now() - timedelta(days=days_back)

        # Query for recent messages (we don't care about spam/legitimate here)
        sql = f"""
        SELECT
            attributes->'update'->'message'->>'text' as message_text,
            attributes->'update'->'message'->'from'->>'first_name' as first_name,
            attributes->'update'->'message'->'from'->>'username' as username,
            attributes->'update'->'message'->>'caption' as caption,
            start_timestamp
        FROM records
        WHERE
            attributes->'update'->'message' IS NOT NULL
            AND (attributes->'update'->'message'->>'text' IS NOT NULL
                 OR attributes->'update'->'message'->>'caption' IS NOT NULL)
            AND start_timestamp >= '{start_time.isoformat()}'
        ORDER BY start_timestamp DESC
        LIMIT {limit}
        """

        results = await asyncio.to_thread(
            client.query_json_rows,
            sql=sql,
            min_timestamp=start_time,
        )

        test_cases = []
        if results and results.get("rows"):
            for row in results["rows"]:
                text = row.get("message_text") or row.get("caption")
                if not text:
                    continue

                # Combine first_name and username for name
                name = None
                if row.get("first_name"):
                    name = row["first_name"]
                    if row.get("username"):
                        name += f" (@{row['username']})"
                elif row.get("username"):
                    name = f"@{row['username']}"

                test_case = TestCase(
                    text=text,
                    name=name,
                    ground_truth_score=0,  # No ground truth available
                )
                test_cases.append(test_case)

        logger.info(f"Loaded {len(test_cases)} messages from Logfire (no ground truth)")
        return test_cases

    except Exception as e:
        logger.warning(f"Failed to load Logfire messages: {e}")
        return []


async def test_model(
    model_name: str,
    test_cases: List[TestCase],
    delay: float = 1.0,
) -> ModelResult:
    """
    Test a single model against all test cases.

    Args:
        model_name: The model to test
        test_cases: List of test cases with ground truth
        delay: Delay between requests in seconds

    Returns:
        ModelResult with all metrics for this model
    """
    from src.app.common.llms import (
        RateLimitExceeded,
        LocationNotSupported,
        InternalServerError,
    )
    from src.app.spam.spam_classifier import is_spam
    from src.app.spam.context_types import (
        SpamClassificationContext,
        ContextResult,
        ContextStatus,
    )

    logger.info(f"Testing model: {model_name} with {len(test_cases)} cases")

    result = ModelResult(model_name=model_name, total_cases=len(test_cases))

    # Temporarily override MODELS to test only this model
    import src.app.common.llms as llms_module

    original_models = llms_module.MODELS
    llms_module.MODELS = [model_name]  # Only test this model

    def _handle_error(error_type: str, exception: Exception) -> None:
        """Helper to handle API errors consistently."""
        result.errors[error_type] += 1
        test_result.error = error_type
        logger.debug(
            f"{error_type.replace('_', ' ').title()} for {model_name}: {exception}"
        )

    try:
        for test_case in tqdm(
            test_cases,
            desc=f"Testing {model_name}",
            unit="cases",
            position=1,
            leave=False,
        ):
            test_result = TestResult(test_case=test_case)

            try:
                # Create classification context from test case data
                context = SpamClassificationContext(
                    name=test_case.name,
                    bio=test_case.bio,
                    linked_channel=ContextResult(
                        status=ContextStatus.FOUND,
                        content=test_case.linked_channel_fragment,
                    )
                    if test_case.linked_channel_fragment
                    else None,
                    stories=ContextResult(
                        status=ContextStatus.FOUND, content=test_case.stories_context
                    )
                    if test_case.stories_context
                    else None,
                    reply=test_case.reply_context,
                    account_age=ContextResult(
                        status=ContextStatus.FOUND,
                        content=test_case.account_age_context,
                    )
                    if test_case.account_age_context
                    else None,
                )

                # Call is_spam with consolidated context
                start_time = time.time()
                predicted_score, reason = await is_spam(
                    comment=test_case.text,
                    context=context,
                )
                end_time = time.time()

                # Track timing
                response_time = end_time - start_time
                test_result.response_time = response_time
                result.total_response_time += response_time
                result.successful_responses += 1

                # Determine prediction (positive = spam, negative = legitimate)
                predicted_spam = predicted_score > 0
                actual_spam = test_case.is_spam_ground_truth

                test_result.predicted_score = predicted_score
                test_result.predicted_spam = predicted_spam
                test_result.is_correct = predicted_spam == actual_spam

                # Update confusion matrix
                if predicted_spam and actual_spam:
                    result.true_positives += 1
                elif predicted_spam and not actual_spam:
                    result.false_positives += 1
                elif not predicted_spam and not actual_spam:
                    result.true_negatives += 1
                elif not predicted_spam and actual_spam:
                    result.false_negatives += 1

            except RateLimitExceeded as e:
                _handle_error("rate_limit", e)
            except LocationNotSupported as e:
                _handle_error("location_not_supported", e)
            except InternalServerError as e:
                _handle_error("internal_server_error", e)
            except Exception as e:
                _handle_error("other_error", e)

            # Store individual test result
            result.test_results.append(test_result)

            # Add delay between requests to avoid rate limits
            await asyncio.sleep(delay)

    finally:
        # Restore original MODELS
        llms_module.MODELS = original_models

    logger.info(
        f"Completed testing {model_name}: "
        f"{result.successful_responses}/{result.total_cases} successful, "
        f"accuracy={result.accuracy:.3f}, "
        f"f1={result.f1_score:.3f}"
    )

    return result


def format_results(
    model_results: List[ModelResult],
    test_cases: List[TestCase],
) -> str:
    """
    Format evaluation results for console output.

    Args:
        model_results: List of results for each tested model
        test_cases: The test cases used

    Returns:
        Formatted string for console output
    """
    if not model_results:
        return "No results to display"

    lines = []
    lines.append("\n" + "=" * 80)
    lines.append("🎯 LLM MODELS EVALUATION RESULTS")
    lines.append("=" * 80)

    # Quick summary at top
    if model_results:
        best_model = max(
            model_results,
            key=lambda r: r.f1_score if r.successful_responses > 0 else -1,
        )
        lines.append(f"\n🏆 BEST MODEL: {best_model.model_name}")
        if best_model.successful_responses > 0:
            lines.append(f"   • Accuracy: {best_model.accuracy:.1%}")
            lines.append(f"   • F1 Score: {best_model.f1_score:.1%}")
            lines.append(f"   • Success Rate: {best_model.success_rate:.1%}")

    lines.append("\n" + "-" * 80)
    lines.append("SUMMARY STATISTICS:")
    lines.append(f"  📊 Total test cases: {len(test_cases)}")
    lines.append(f"  🤖 Models tested: {len(model_results)}")

    if model_results:
        accuracies = [r.accuracy for r in model_results if r.successful_responses > 0]
        if accuracies:
            lines.append(f"  🎯 Best accuracy: {max(accuracies):.1%}")
            lines.append(
                f"  📈 Average accuracy: {sum(accuracies) / len(accuracies):.1%}"
            )

    # Sort models by F1 score for ranking
    sorted_results = sorted(
        model_results,
        key=lambda r: r.f1_score if r.successful_responses > 0 else -1,
        reverse=True,
    )

    # Per-model breakdown
    lines.append("\n" + "=" * 80)
    lines.append("📋 DETAILED MODEL COMPARISON")
    lines.append("=" * 80)

    for i, result in enumerate(sorted_results, 1):
        rank_emoji = ["🥇", "🥈", "🥉"][i - 1] if i <= 3 else f"{i}."
        lines.append(f"\n{rank_emoji} {result.model_name}")

        # Status indicator
        if result.successful_responses == 0:
            lines.append("  ❌ FAILED - No successful responses")
            continue

        lines.append("  ✅ ACTIVE")
        lines.append(
            f"     Success rate: {result.success_rate:.1%} "
            f"({result.successful_responses}/{result.total_cases})"
        )
        lines.append(f"     Accuracy:     {result.accuracy:.1%}")
        lines.append(f"     Precision:    {result.precision:.1%}")
        lines.append(f"     Recall:       {result.recall:.1%}")
        lines.append(f"     F1 Score:     {result.f1_score:.1%}")
        lines.append(f"     Avg response: {result.average_response_time:.1f}s")

        # Error breakdown
        if result.errors:
            error_lines = []
            for error_type, count in result.errors.items():
                if count > 0:
                    error_lines.append(f"{error_type}: {count}")
            if error_lines:
                lines.append(f"     ⚠️  Errors: {', '.join(error_lines)}")

    # Confusion matrix for best model
    if sorted_results and sorted_results[0].successful_responses > 0:
        best_result = sorted_results[0]
        lines.append(f"\n🎯 CONFUSION MATRIX ({best_result.model_name}):")
        lines.append("                     Predicted")
        lines.append("            Spam    |    Legitimate")
        lines.append("  Actual    ———————————————")

        def _format_matrix_row(
            label: str, predicted_pos: int, predicted_neg: int, total: int
        ) -> str:
            """Helper to format confusion matrix rows consistently."""
            return (
                f"  {label:<10}{predicted_pos:<6}  |    {predicted_neg:<6}  "
                f"← Correct: {predicted_pos}/{total}"
            )

        spam_total = best_result.true_positives + best_result.false_negatives
        legit_total = best_result.false_positives + best_result.true_negatives

        lines.append(
            _format_matrix_row(
                "Spam",
                best_result.true_positives,
                best_result.false_negatives,
                spam_total,
            )
        )
        lines.append(
            _format_matrix_row(
                "Legitimate",
                best_result.false_positives,
                best_result.true_negatives,
                legit_total,
            )
        )

    # Sample errors (if any)
    lines.append("\n❌ SAMPLE MISCLASSIFICATIONS:")

    # Find misclassified examples for the best model
    if sorted_results and sorted_results[0].test_results:
        best_model_results = sorted_results[0].test_results
        misclassifications = [
            tr
            for tr in best_model_results
            if tr.is_correct is False and tr.predicted_spam is not None
        ]

        def _get_label(is_spam: bool) -> str:
            """Helper to get consistent label for spam/legitimate."""
            return "SPAM" if is_spam else "LEGITIMATE"

        def _truncate_text(text: str, max_len: int = 100) -> str:
            """Helper to truncate text consistently."""
            return text[:max_len] + "..." if len(text) > max_len else text

        if misclassifications:
            lines.append(
                f"  Found {len(misclassifications)} misclassifications in {best_model.model_name}"
            )
            lines.append("  Showing first 3:")

            for i, tr in enumerate(misclassifications[:3], 1):
                actual_label = _get_label(tr.test_case.is_spam_ground_truth)
                predicted_label = _get_label(
                    tr.predicted_spam or False
                )  # Default to False if None

                lines.append(
                    f"\n  {i}. ❌ Predicted: {predicted_label} | Actual: {actual_label}"
                )
                lines.append(f"     Text: {_truncate_text(tr.test_case.text)!r}")
                if tr.test_case.name:
                    lines.append(f"     Name: {tr.test_case.name}")
        else:
            lines.append(
                f"  ✅ No misclassifications found in {best_model.model_name}!"
            )
    else:
        lines.append("  No detailed error tracking available")

    return "\n".join(lines)


def save_results_to_json(
    model_results: List[ModelResult],
    test_cases: List[TestCase],
    test_parameters: Dict,
) -> str:
    """
    Save evaluation results to a JSON file in eval_results/ directory.

    Args:
        model_results: List of results for each tested model
        test_cases: The test cases used
        test_parameters: Parameters used for the evaluation

    Returns:
        Path to the saved JSON file
    """
    # Create eval_results directory if it doesn't exist
    results_dir = Path("eval_results")
    results_dir.mkdir(exist_ok=True)

    # Generate timestamped filename
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"eval_{timestamp}.json"
    filepath = results_dir / filename

    # Prepare data for serialization
    data = {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "test_parameters": test_parameters,
            "total_test_cases": len(test_cases),
        },
        "model_results": [_serialize_model_result(result) for result in model_results],
        "test_cases": [_serialize_test_case(tc) for tc in test_cases],
    }

    # Save to JSON file
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    logger.info(f"Results saved to {filepath}")
    return str(filepath)


def _serialize_model_result(result: ModelResult) -> Dict:
    """Serialize ModelResult to dictionary for JSON."""
    data = asdict(result)
    # Remove the test_results field as it will be serialized separately if needed
    # For now, we'll keep it simple and just include the aggregate metrics
    data.pop("test_results", None)
    return data


def _serialize_test_case(test_case: TestCase) -> Dict:
    """Serialize TestCase to dictionary for JSON, truncating long text."""
    data = asdict(test_case)
    # Truncate very long text fields to keep JSON manageable
    if data.get("text") and len(data["text"]) > 500:
        data["text"] = data["text"][:500] + "..."
    return data


async def run_evaluation(
    models_to_test: Optional[List[str]] = None,
    limit: int = 100,
    admin_ids: Optional[List[int]] = None,
    delay: float = 1.0,
    include_logfire: bool = False,
) -> None:
    """
    Run the complete evaluation process.

    Args:
        models_to_test: List of specific models to test, or None for all
        limit: Maximum number of test cases
        admin_ids: Admin IDs for user-specific examples
        delay: Delay between requests
        include_logfire: Whether to include Logfire examples (for functionality testing)
    """
    logger.info("Starting LLM models evaluation")

    # Import models list locally to avoid module-level imports
    from src.app.common.llms import MODELS as ORIGINAL_MODELS

    # Determine which models to test
    if models_to_test:
        models = [m for m in models_to_test if m in ORIGINAL_MODELS]
        if not models:
            logger.error(
                f"None of the specified models found in MODELS: {models_to_test}"
            )
            logger.info(f"Available models: {ORIGINAL_MODELS}")
            return
    else:
        models = ORIGINAL_MODELS.copy()

    logger.info(f"Testing {len(models)} models: {models}")

    # Load test cases
    test_cases = await load_test_cases_from_db(limit=limit, admin_ids=admin_ids)
    if not test_cases:
        logger.error("No test cases loaded from database")
        return

    # Test each model
    model_results = []
    for model_name in tqdm(models, desc="Testing models", unit="models", position=0):
        result = await test_model(model_name, test_cases, delay=delay)
        model_results.append(result)

    # Format and display results
    output = format_results(model_results, test_cases)
    print(output)

    # Save results to JSON
    test_parameters = {
        "limit": limit,
        "admin_ids": admin_ids,
        "models": models,
        "delay": delay,
        "include_logfire": include_logfire,
    }
    json_file = save_results_to_json(model_results, test_cases, test_parameters)
    print(f"\n📄 Results saved to: {json_file}")

    logger.info("Evaluation completed")


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Evaluate LLM models for spam classification accuracy"
    )
    parser.add_argument(
        "--models", nargs="*", help="Specific models to test (default: all models)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of test cases to use (default: 100)",
    )
    parser.add_argument(
        "--admin-ids",
        nargs="*",
        type=int,
        help="Admin IDs to include user-specific examples for",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay between requests in seconds (default: 1.0)",
    )
    parser.add_argument(
        "--logfire",
        action="store_true",
        help="Include Logfire examples for functionality testing (no accuracy metrics)",
    )

    args = parser.parse_args()

    # Validate environment
    if not os.getenv("OPENROUTER_API_KEY"):
        logger.error("OPENROUTER_API_KEY environment variable is required")
        sys.exit(1)

    # Run evaluation
    try:
        await run_evaluation(
            models_to_test=args.models,
            limit=args.limit,
            admin_ids=args.admin_ids,
            delay=args.delay,
            include_logfire=args.logfire,
        )
    except KeyboardInterrupt:
        logger.info("Evaluation interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Evaluation failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
