#!/usr/bin/env python3
"""
Integration test for Logfire message lookup functionality.

Tests that the logfire_lookup.find_original_message function can successfully
find messages from real traces, specifically the case from trace 019b5e2c87ecf0c47aeb7591b9c35dcb.

This test demonstrates that forwarded messages from channels can be found
in Logfire even when user_id extraction from forward metadata fails.
"""

import asyncio
import os
import sys
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables first
load_dotenv()

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from app.common.logfire_lookup import find_original_message


async def test_logfire_message_lookup():
    """
    Test that logfire message lookup can find the original message from trace 019b5e2c87ecf0c47aeb7591b9c35dcb.

    This trace contains a channel message "Пусть будет больше света ☀️" from @kotnikova_yana
    that was posted to chat -1001660382870 as message 14225.
    """
    print("Testing Logfire Message Lookup")
    print("=" * 60)

    # Parameters from the real trace 019b5e2c87ecf0c47aeb7591b9c35dcb
    message_text = "Пусть будет больше света ☀️"
    forward_date = datetime.fromisoformat(
        "2025-12-27T09:05:16.955510+00:00"
    )  # When message was forwarded
    user_id = 136817688  # Channel Bot ID (effective user for channel messages)

    # Admin's managed groups (from the trace, this admin manages group -1001660382870)
    admin_chat_ids = [-1001660382870]

    print("🔍 Searching for original message...")
    print(f"   Text: '{message_text}'")
    print(f"   User ID: {user_id}")
    print(f"   Forward date: {forward_date}")
    print(f"   Candidate chats: {admin_chat_ids}")
    print()

    try:
        # Call the logfire lookup function
        result = await find_original_message(
            user_id=user_id,
            message_text=message_text,
            forward_date=forward_date,
            admin_chat_ids=admin_chat_ids,
            search_days_back=3,  # Search 3 days back from forward date
        )

        print("📊 Lookup Results:")
        if result:
            print("   ✅ SUCCESS - Message found!")
            print(f"   📍 Chat ID: {result['chat_id']}")
            print(f"   💬 Message ID: {result['message_id']}")
            print(f"   👤 User ID: {result.get('user_id', 'N/A')}")

            # Verify expected values from trace 019b5e2c87ecf0c47aeb7591b9c35dcb
            expected_chat_id = -1001660382870
            expected_message_id = 14225

            if (
                result["chat_id"] == expected_chat_id
                and result["message_id"] == expected_message_id
            ):
                print("   ✅ VERIFICATION PASSED - Found exact message from trace!")
                print(
                    "   🎯 This proves the logfire lookup can recover forwarded channel messages"
                )
                return True
            else:
                print(
                    "   ⚠️  PARTIAL SUCCESS - Found a message but not the expected one"
                )
                print(
                    f"      Expected: chat={expected_chat_id}, message={expected_message_id}"
                )
                print(
                    f"      Found: chat={result['chat_id']}, message={result['message_id']}"
                )
                return False
        else:
            print("   ❌ FAILED - No message found")
            print("   This indicates the logfire lookup is not working correctly")
            return False

    except Exception as e:
        print(f"   💥 ERROR - Lookup failed with exception: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_logfire_message_lookup_without_user_id():
    """
    Test that logfire message lookup can find messages even when user_id is None.
    This simulates the case where forward metadata extraction fails initially.
    """
    print("\n" + "=" * 60)
    print("Testing Logfire Message Lookup (without user_id)")
    print("=" * 60)

    # Same parameters but without user_id (simulating failed forward metadata extraction)
    message_text = "Пусть будет больше света ☀️"
    forward_date = datetime.fromisoformat("2025-12-27T09:05:16.955510+00:00")
    user_id = None  # No user_id provided

    admin_chat_ids = [-1001660382870]

    print("🔍 Searching for original message (no user_id provided)...")
    print(f"   Text: '{message_text}'")
    print(f"   User ID: {user_id} (None)")
    print(f"   Forward date: {forward_date}")
    print(f"   Candidate chats: {admin_chat_ids}")
    print()

    try:
        result = await find_original_message(
            user_id=user_id,
            message_text=message_text,
            forward_date=forward_date,
            admin_chat_ids=admin_chat_ids,
            search_days_back=3,
        )

        print("📊 Lookup Results:")
        if result:
            print("   ✅ SUCCESS - Message found even without user_id!")
            print(f"   📍 Chat ID: {result['chat_id']}")
            print(f"   💬 Message ID: {result['message_id']}")
            print(f"   👤 User ID: {result.get('user_id', 'N/A')}")

            expected_chat_id = -1001660382870
            expected_message_id = 14225

            if (
                result["chat_id"] == expected_chat_id
                and result["message_id"] == expected_message_id
            ):
                print(
                    "   ✅ VERIFICATION PASSED - Found exact message without user_id!"
                )
                print(
                    "   🎯 This proves the logfire lookup can recover messages even when"
                )
                print("       forward metadata extraction fails for channel messages")
                return True
            else:
                print(
                    "   ⚠️  PARTIAL SUCCESS - Found a message but not the expected one"
                )
                return False
        else:
            print("   ❌ FAILED - No message found without user_id")
            print("   This suggests the text matching alone is not sufficient")
            return False

    except Exception as e:
        print(f"   💥 ERROR - Lookup failed with exception: {e}")
        import traceback

        traceback.print_exc()
        return False


async def main():
    """Run all logfire message lookup tests."""
    print("🧪 Logfire Message Lookup Integration Tests")
    print("Testing ability to find original messages from forwarded channel content")
    print()

    # Test 1: With user_id
    test1_passed = await test_logfire_message_lookup()

    # Test 2: Without user_id (simulating failed forward metadata extraction)
    test2_passed = await test_logfire_message_lookup_without_user_id()

    print("\n" + "=" * 60)
    print("📋 FINAL RESULTS")
    print("=" * 60)
    print(f"Test 1 (with user_id): {'✅ PASSED' if test1_passed else '❌ FAILED'}")
    print(f"Test 2 (without user_id): {'✅ PASSED' if test2_passed else '❌ FAILED'}")

    if test1_passed and test2_passed:
        print("\n🎉 ALL TESTS PASSED!")
        print("The logfire message lookup system is working correctly.")
        print(
            "It can successfully recover forwarded channel messages for spam examples."
        )
        return 0
    else:
        print("\n💥 SOME TESTS FAILED!")
        print("The logfire message lookup system needs investigation.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
