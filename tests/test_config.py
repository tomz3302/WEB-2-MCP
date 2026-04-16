"""Tests for the Settings / config module (config.py)."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from web2mcp.config import Settings, get_settings


class TestSettings:
    def test_defaults(self):
        s = Settings()
        assert s.llm_provider == "openai"
        assert s.llm_model == "gpt-4o"
        assert s.browser_headless is True
        assert s.browser_timeout == 30_000
        assert s.max_browser_steps == 50
        assert s.mcp_server_name == "WEB-2-MCP"

    def test_env_var_override(self):
        with patch.dict(
            os.environ,
            {
                "LLM_MODEL": "gpt-4o-mini",
                "BROWSER_HEADLESS": "false",
                "MAX_BROWSER_STEPS": "10",
            },
        ):
            s = Settings()
            assert s.llm_model == "gpt-4o-mini"
            assert s.browser_headless is False
            assert s.max_browser_steps == 10

    def test_api_key_from_env(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-key"}):
            s = Settings()
            assert s.openai_api_key == "sk-test-key"

    def test_get_settings_returns_settings(self):
        s = get_settings()
        assert isinstance(s, Settings)

    def test_custom_server_name(self):
        with patch.dict(os.environ, {"MCP_SERVER_NAME": "my-custom-server"}):
            s = Settings()
            assert s.mcp_server_name == "my-custom-server"

    def test_llm_provider_anthropic(self):
        with patch.dict(
            os.environ,
            {
                "LLM_PROVIDER": "anthropic",
                "ANTHROPIC_API_KEY": "ant-key",
            },
        ):
            s = Settings()
            assert s.llm_provider == "anthropic"
            assert s.anthropic_api_key == "ant-key"
