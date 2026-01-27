#!/usr/bin/env python3
"""
Test the specific case from the logfire span to verify the fix works.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from src.app.spam.spam_classifier import is_spam
from src.app.spam.context_types import SpamClassificationContext

async def test_specific_case():
    """Test the exact scenario from the logfire span."""
    
    # The exact message from the span
    message = "Какой минимальный взнос в проект?"
    
    # The exact reply context from the span (the spam message being replied to)
    reply_context = """❗️❗️❗️Уважаемые инвесторы, добрый день!

Напоминаем, что мы все еще осуществляем сбор денежных средств в упомянутый выше проект с доходностью 30% годовых!

Желающим войти в сделку просьба обращаться к:

Виктория Максимова, 
директор по продажам 
💚@Victoria_YaFT
💚 WhatsApp
+7-916-770-67-98 

ЯрФинТраст. Инвестиции в недвижимость"""

    # Create context with the reply
    context = SpamClassificationContext(
        reply=reply_context
    )
    
    print("=== TESTING SPECIFIC CASE FROM LOGFIRE SPAN ===")
    print(f"Message: {message!r}")
    print(f"Reply Context: {reply_context[:100]}..." if len(reply_context) > 100 else f"Reply Context: {reply_context!r}")
    print()
    
    try:
        score, reason = await is_spam(comment=message, context=context)
        
        print("=== RESULTS ===")
        print(f"Score: {score}")
        print(f"Reason: {reason}")
        print(f"Classification: {'SPAM' if score > 0 else 'LEGITIMATE'}")
        print()
        
        if score <= 0:
            print("✅ SUCCESS: Message correctly classified as legitimate!")
        else:
            print("❌ FAILURE: Message incorrectly classified as spam!")
            
        return score <= 0  # True if correctly classified as legitimate
        
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False

if __name__ == "__main__":
    success = asyncio.run(test_specific_case())
    sys.exit(0 if success else 1)
