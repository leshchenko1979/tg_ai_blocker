"""Static checks: referenced t() keys and help callbacks exist as strings in en/ru YAML."""

from tests.support.i18n_keys_audit import run_i18n_keys_audit


def test_all_referenced_i18n_keys_exist_in_locales() -> None:
    """
    AST scan of app/, plus HELP_PAGE_CALLBACK_KEYS and known dynamic keys,
    must resolve to string leaves in both en.yaml and ru.yaml.
    """
    result = run_i18n_keys_audit()
    assert not result.missing_by_lang["en"], (
        "Missing or non-string in en.yaml:\n  "
        + "\n  ".join(result.missing_by_lang["en"])
    )
    assert not result.missing_by_lang["ru"], (
        "Missing or non-string in ru.yaml:\n  "
        + "\n  ".join(result.missing_by_lang["ru"])
    )
