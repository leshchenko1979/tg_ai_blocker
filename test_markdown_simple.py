"""
Simple test script for markdown sanitization.
"""

def sanitize_markdown(text: str) -> str:
    """
    Sanitizes markdown text to ensure it's compatible with Telegram's markdown parser.

    Args:
        text: The markdown text to sanitize

    Returns:
        Sanitized markdown text
    """
    # First, handle bullet points by replacing them with Unicode bullets
    lines = text.split('\n')
    for i in range(len(lines)):
        if lines[i].strip().startswith('*   '):
            lines[i] = lines[i].replace('*   ', '•   ', 1)

    text = '\n'.join(lines)

    # Check if we have unbalanced markdown entities
    if text.count('*') % 2 != 0 or text.count('_') % 2 != 0 or text.count('`') % 2 != 0:
        # Escape all markdown characters
        text = text.replace('*', '\\*')
        text = text.replace('_', '\\_')
        text = text.replace('`', '\\`')
        text = text.replace('[', '\\[')
        text = text.replace(']', '\\]')

    return text

# Test cases
test_cases = [
    {
        "name": "Problematic response with bullet points",
        "input": """Что я умею? 😈 Я - нейромодератор, кибер-защитник, страж чистоты Telegram! Мои умения безграничны, но вот основные:

*   **Анализ сообщений**: Я сканирую каждое сообщение в группе, используя мощь искусственного интеллекта. 🧠
*   **Удаление спама**: Если сообщение пахнет спамом, я его уничтожаю без колебаний. 💥
*   **Учет пользователей**: Я помню, кто хороший, а кто плохой. Проверенные пользователи могут проходить, спамеры - нет! 🚫
*   **Обучение**: Я учусь на ваших примерах, чтобы становиться еще лучше в борьбе со злом. 📚
*   **Удаление мусора**: Автоматически удаляю сообщения о вступлении и выходе участников, чтобы в группе был порядок. 🧹

И это только начало! 🚀 Я постоянно развиваюсь, чтобы быть на шаг впереди спамеров. 😈"""
    },
    {
        "name": "Unbalanced asterisks",
        "input": "This is *unbalanced text"
    },
    {
        "name": "Unbalanced underscores",
        "input": "This is _unbalanced text"
    },
    {
        "name": "Unbalanced backticks",
        "input": "This is `unbalanced text"
    },
    {
        "name": "Multiple unbalanced symbols",
        "input": "This is *unbalanced _text with `multiple symbols"
    },
    {
        "name": "Balanced asterisks",
        "input": "This is *balanced* text"
    },
    {
        "name": "Balanced underscores",
        "input": "This is _balanced_ text"
    },
    {
        "name": "Balanced backticks",
        "input": "This is `balanced` text"
    },
    {
        "name": "Multiple balanced symbols",
        "input": "This is *balanced* _text_ with `multiple` symbols"
    },
    {
        "name": "Simple bullet points",
        "input": """List:
*   Item 1
*   Item 2
*   Item 3"""
    },
    {
        "name": "Bullet points with formatting",
        "input": """List:
*   **Item 1**
*   *Item 2*
*   `Item 3`"""
    }
]

# Run tests
for test_case in test_cases:
    print(f"\n{'=' * 80}")
    print(f"Test case: {test_case['name']}")
    print(f"{'=' * 80}")

    input_text = test_case['input']
    sanitized_text = sanitize_markdown(input_text)

    print("\nOriginal text:")
    print("-" * 80)
    print(input_text)
    print("-" * 80)

    print("\nSanitized text:")
    print("-" * 80)
    print(sanitized_text)
    print("-" * 80)

    # Check for unbalanced markdown entities
    print("\nChecking for unbalanced markdown entities:")
    print(f"* count: {sanitized_text.count('*')} (balanced: {sanitized_text.count('*') % 2 == 0})")
    print(f"_ count: {sanitized_text.count('_')} (balanced: {sanitized_text.count('_') % 2 == 0})")
    print(f"` count: {sanitized_text.count('`')} (balanced: {sanitized_text.count('`') % 2 == 0})")

    # Check for bullet points
    print("\nChecking for bullet points:")
    print(f"Contains '*   ': {'*   ' in sanitized_text}")
    print(f"Contains '•   ': {'•   ' in sanitized_text}")

    # Check if any markdown characters were escaped
    print("\nChecking for escaped markdown characters:")
    print(f"Contains '\\*': {'\\*' in sanitized_text}")
    print(f"Contains '\\_': {'\\_' in sanitized_text}")
    print(f"Contains '\\`': {'\\`' in sanitized_text}")
    print(f"Contains '\\[': {'\\[' in sanitized_text}")
    print(f"Contains '\\]': {'\\]' in sanitized_text}")

print("\nAll tests completed!")
