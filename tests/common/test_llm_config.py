"""Tests for config.yaml llm section validation and accessors."""

import pytest

from app.common.utils import (
    get_llm_http_client_timeout,
    get_llm_route_timeout,
    get_openrouter_models,
    reset_llm_config_validation,
    validate_llm_config,
)

VALID_LLM = {
    "llm": {
        "route_timeout_seconds": 30,
        "http_client_timeout_seconds": 60,
        "openrouter_models": [
            "meta-llama/llama-3.3-70b-instruct:free",
            "qwen/qwen3-next-80b-a3b-instruct:free",
        ],
    }
}


def test_validate_accepts_valid_config():
    reset_llm_config_validation()
    validate_llm_config(VALID_LLM)
    assert get_llm_route_timeout() == 30.0
    assert get_llm_http_client_timeout() == 60.0
    assert get_openrouter_models() == VALID_LLM["llm"]["openrouter_models"]


def test_getters_require_validation():
    reset_llm_config_validation()
    with pytest.raises(RuntimeError, match="not validated"):
        get_llm_route_timeout()


@pytest.mark.parametrize(
    "config,match",
    [
        ({}, "missing or invalid 'llm'"),
        ({"llm": "bad"}, "missing or invalid 'llm'"),
        ({"llm": {}}, "missing llm.route_timeout_seconds"),
        (
            {
                "llm": {
                    "route_timeout_seconds": 30,
                    "http_client_timeout_seconds": 60,
                }
            },
            "openrouter_models must be a non-empty list",
        ),
        (
            {
                "llm": {
                    "route_timeout_seconds": 30,
                    "http_client_timeout_seconds": 60,
                    "openrouter_models": [],
                }
            },
            "openrouter_models must be a non-empty list",
        ),
        (
            {
                "llm": {
                    "route_timeout_seconds": 30,
                    "http_client_timeout_seconds": 60,
                    "openrouter_models": "meta-llama/x:free",
                }
            },
            "openrouter_models must be a non-empty list",
        ),
        (
            {
                "llm": {
                    "route_timeout_seconds": "slow",
                    "http_client_timeout_seconds": 60,
                    "openrouter_models": ["a/b"],
                }
            },
            "route_timeout_seconds must be a number",
        ),
        (
            {
                "llm": {
                    "route_timeout_seconds": 30,
                    "http_client_timeout_seconds": 10,
                    "openrouter_models": ["a/b"],
                }
            },
            "http_client_timeout_seconds must be >=",
        ),
        (
            {
                "llm": {
                    "route_timeout_seconds": 30,
                    "http_client_timeout_seconds": 60,
                    "openrouter_models": ["no-slash"],
                }
            },
            r"openrouter_models\[0\].*containing",
        ),
    ],
)
def test_validate_rejects_invalid_config(config, match):
    reset_llm_config_validation()
    with pytest.raises(ValueError, match=match):
        validate_llm_config(config)


def test_project_config_yaml_is_valid():
    reset_llm_config_validation()
    validate_llm_config()
    models = get_openrouter_models()
    assert len(models) == 6
    assert models[0].startswith("meta-llama/")
