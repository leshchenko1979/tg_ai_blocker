from src.app.common.utils import sanitize_markdown


def test_sanitize_markdown_bold():
    # Простой случай с жирным текстом
    assert sanitize_markdown("*bold*") == "*bold*"
    # С пробелами
    assert sanitize_markdown(" *bold* ") == " *bold* "
    # С пунктуацией
    assert sanitize_markdown("*bold*, text") == "*bold*, text"
    assert sanitize_markdown("text, *bold*.") == "text, *bold*."


def test_sanitize_markdown_italic():
    # Простой случай с курсивом
    assert sanitize_markdown("_italic_") == "_italic_"
    # С пробелами
    assert sanitize_markdown(" _italic_ ") == " _italic_ "
    # С пунктуацией
    assert sanitize_markdown("_italic_, text") == "_italic_, text"
    assert sanitize_markdown("text, _italic_.") == "text, _italic_."


def test_sanitize_markdown_code():
    # Простой случай с кодом
    assert sanitize_markdown("`code`") == "`code`"
    # С пробелами
    assert sanitize_markdown(" `code` ") == " `code` "
    # С пунктуацией
    assert sanitize_markdown("`code`, text") == "`code`, text"


def test_sanitize_markdown_links():
    # Простой случай со ссылкой
    assert sanitize_markdown("[link](url)") == "[link](url)"
    # С пробелами
    assert sanitize_markdown(" [link](url) ") == " [link](url) "


def test_sanitize_markdown_escape_single():
    # Одиночные символы должны экранироваться
    assert sanitize_markdown("some_variable_name") == "some\\_variable\\_name"
    assert sanitize_markdown("some_variable_1") == "some\\_variable\\_1"
    assert sanitize_markdown("5 * 3 = 15") == "5 \\* 3 = 15"
    assert (
        sanitize_markdown("function(x) { return `x` }") == "function(x) { return `x` }"
    )


def test_sanitize_markdown_mixed():
    # Смешанное форматирование
    assert sanitize_markdown("*bold* and _italic_") == "*bold* and _italic_"
    assert sanitize_markdown("_italic_ and *bold*") == "_italic_ and *bold*"
    assert sanitize_markdown("*bold*, _italic_.") == "*bold*, _italic_."


def test_sanitize_markdown_newlines():
    # Проверка работы с переносами строк
    text = """*Title*
    Some text with _italic_
    And *bold* formatting"""
    expected = """*Title*
    Some text with _italic_
    And *bold* formatting"""
    assert sanitize_markdown(text) == expected


def test_sanitize_markdown_bullets():
    # Проверка замены маркеров списка
    text = """List:
    *   First item
    *   Second item"""
    expected = """List:
    •   First item
    •   Second item"""
    assert sanitize_markdown(text) == expected


def test_sanitize_markdown_edge_cases():
    # Пустая строка
    assert sanitize_markdown("") == ""
    # Только пробелы
    assert sanitize_markdown("   ") == "   "
    # Только символы форматирования
    assert sanitize_markdown("***") == "\\*\\*\\*"
    # Незакрытые теги
    assert sanitize_markdown("*bold") == "\\*bold"
    assert sanitize_markdown("_italic") == "\\_italic"
