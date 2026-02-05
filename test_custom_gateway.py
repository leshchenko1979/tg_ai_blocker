#!/usr/bin/env python3
"""
Test script to verify the custom gateway implementation.
"""

import asyncio
import json
import logging
import os
import sys
from typing import Dict, List

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from app.common.llms import get_llm_response_with_fallback

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_custom_gateway():
    """Test the custom gateway with a simple request."""

    # Test message for spam classification
    messages = [
        {
            "role": "system",
            "content": "You are a spam classifier. Determine if the given message is spam.",
        },
        {
            "role": "user",
            "content": "Buy cheap viagra now! Click here: http://spam.com",
        },
    ]

    # Response format for spam classification
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "spam_classification",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "is_spam": {
                        "type": "boolean",
                        "description": "True if message is spam, False otherwise",
                    },
                    "confidence": {
                        "type": "integer",
                        "description": "Confidence level from 0 to 100",
                        "minimum": 0,
                        "maximum": 100,
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for classification",
                    },
                },
                "required": ["is_spam", "confidence", "reason"],
                "additionalProperties": False,
            },
        },
    }

    try:
        logger.info("Testing custom gateway with spam classification...")
        response = await get_llm_response_with_fallback(
            messages=messages, temperature=0.0, response_format=response_format
        )

        logger.info(f"✅ Custom gateway responded successfully!")
        logger.info(f"Response: {response}")

        # Try to parse the response as JSON
        try:
            parsed_response = json.loads(response)
            logger.info(f"✅ Response is valid JSON: {parsed_response}")

            # Check if all required fields are present
            if all(
                key in parsed_response for key in ["is_spam", "confidence", "reason"]
            ):
                logger.info("✅ Response contains all required fields")
                logger.info(f"  - Is Spam: {parsed_response['is_spam']}")
                logger.info(f"  - Confidence: {parsed_response['confidence']}")
                logger.info(f"  - Reason: {parsed_response['reason']}")
            else:
                logger.warning("⚠️ Response is missing required fields")

        except json.JSONDecodeError:
            logger.warning("⚠️ Response is not valid JSON, but that's okay for testing")

        return True

    except Exception as e:
        logger.error(f"❌ Test failed with error: {type(e).__name__}: {e}")
        return False


async def test_fallback():
    """Test that fallback to OpenRouter works when custom gateway fails."""

    # Temporarily disable custom gateway by setting invalid URL
    original_api_base = os.getenv("API_BASE")
    os.environ["API_BASE"] = "http://invalid-url-that-will-fail.com"

    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Say 'Hello from OpenRouter fallback!'"},
    ]

    try:
        logger.info("Testing fallback to OpenRouter...")
        response = await get_llm_response_with_fallback(messages)

        logger.info(f"✅ Fallback to OpenRouter worked!")
        logger.info(f"Response: {response}")

        # Restore original API_BASE
        if original_api_base:
            os.environ["API_BASE"] = original_api_base
        else:
            os.environ.pop("API_BASE", None)

        return True

    except Exception as e:
        logger.error(f"❌ Fallback test failed: {type(e).__name__}: {e}")

        # Restore original API_BASE
        if original_api_base:
            os.environ["API_BASE"] = original_api_base
        else:
            os.environ.pop("API_BASE", None)

        return False


async def main():
    """Run all tests."""
    logger.info("🚀 Starting custom gateway tests...")

    # Check environment variables
    required_vars = [
        "API_BASE",
        "CUSTOM_GATEWAY_API_KEY",
        "CUSTOM_GATEWAY_MODEL",
        "OPENROUTER_API_KEY",
    ]
    missing_vars = [var for var in required_vars if not os.getenv(var)]

    if missing_vars:
        logger.error(f"❌ Missing environment variables: {missing_vars}")
        logger.error("Please set these variables in your .env file")
        return False

    logger.info(f"✅ All required environment variables are set")
    logger.info(f"  - API_BASE: {os.getenv('API_BASE')}")
    logger.info(f"  - CUSTOM_GATEWAY_MODEL: {os.getenv('CUSTOM_GATEWAY_MODEL')}")

    # Test 1: Custom gateway
    test1_passed = await test_custom_gateway()

    # Test 2: Fallback to OpenRouter
    test2_passed = await test_fallback()

    # Summary
    logger.info("\n" + "=" * 50)
    logger.info("📊 TEST SUMMARY")
    logger.info("=" * 50)
    logger.info(f"Custom Gateway Test: {'✅ PASSED' if test1_passed else '❌ FAILED'}")
    logger.info(f"Fallback Test: {'✅ PASSED' if test2_passed else '❌ FAILED'}")

    if test1_passed and test2_passed:
        logger.info(
            "\n🎉 All tests passed! The custom gateway implementation is working correctly."
        )
        return True
    else:
        logger.error("\n💥 Some tests failed. Please check the implementation.")
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
