"""
Test script to manually verify the sanitize_markdown function with the problematic response.
"""

from src.app.handlers.private_handlers import sanitize_markdown

# The problematic response that caused the error
problematic_response = """Что я умею? 😈 Я - нейромодератор, кибер-защитник, страж чистоты Telegram! Мои умения безграничны, но вот основные:

*   **Анализ сообщений**: Я сканирую каждое сообщение в группе, используя мощь искусственного интеллекта. 🧠
*   **Удаление спама**: Если сообщение пахнет спамом, я его уничтожаю без колебаний. 💥
*   **Учет пользователей**: Я помню, кто хороший, а кто плохой. Проверенные пользователи могут проходить, спамеры - нет! 🚫
*   **Обучение**: Я учусь на ваших примерах, чтобы становиться еще лучше в борьбе со злом. 📚
*   **Удаление мусора**: Автоматически удаляю сообщения о вступлении и выходе участников, чтобы в группе был порядок. 🧹

И это только начало! 🚀 Я постоянно развиваюсь, чтобы быть на шаг впереди спамеров. 😈"""

# Sanitize the problematic response
sanitized_response = sanitize_markdown(problematic_response)

# Print the original and sanitized responses
print("Original response:")
print("-" * 80)
print(problematic_response)
print("-" * 80)
print("\nSanitized response:")
print("-" * 80)
print(sanitized_response)
print("-" * 80)

# Check for unbalanced markdown entities
print("\nChecking for unbalanced markdown entities:")
print(f"* count: {sanitized_response.count('*')} (balanced: {sanitized_response.count('*') % 2 == 0})")
print(f"_ count: {sanitized_response.count('_')} (balanced: {sanitized_response.count('_') % 2 == 0})")
print(f"` count: {sanitized_response.count('`')} (balanced: {sanitized_response.count('`') % 2 == 0})")

# Check for bullet points
print("\nChecking for bullet points:")
print(f"Contains '*   ': {'*   ' in sanitized_response}")

# Check byte offset 961
if len(sanitized_response.encode('utf-8')) > 961:
    byte_text = sanitized_response.encode('utf-8')
    problem_area_start = max(0, 961 - 20)
    problem_area_end = min(len(byte_text), 961 + 20)
    problem_area = byte_text[problem_area_start:problem_area_end].decode('utf-8', errors='replace')

    print("\nChecking area around byte offset 961:")
    print(f"Characters around byte offset 961: '{problem_area}'")
else:
    print("\nResponse is shorter than 961 bytes")

print("\nTest completed!")
