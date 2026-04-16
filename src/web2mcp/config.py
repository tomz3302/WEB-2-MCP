"""
web2mcp – Configuration management.

Settings are loaded from environment variables or an .env file.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file."""

    # ── LLM provider ──────────────────────────────────────────────────────────
    llm_provider: str = "openai"
    """LLM provider to use: 'openai' or 'anthropic'."""

    llm_model: str = "gpt-4o"
    """Model name passed to the LLM provider."""

    openai_api_key: str = ""
    """OpenAI API key (required when llm_provider='openai')."""

    openai_base_url: str = "https://api.openai.com/v1"
    """OpenAI-compatible base URL (useful for local proxies)."""

    anthropic_api_key: str = ""
    """Anthropic API key (required when llm_provider='anthropic')."""

    # ── Browser settings ──────────────────────────────────────────────────────
    browser_headless: bool = True
    """Run the browser in headless mode."""

    browser_timeout: int = 30_000
    """Default page-load / action timeout in milliseconds."""

    max_browser_steps: int = 50
    """Maximum number of steps the browser-use Agent may take per task."""

    # ── MCP server ────────────────────────────────────────────────────────────
    mcp_server_name: str = "WEB-2-MCP"
    """Human-readable name shown in the MCP server banner."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Allow OPENAI_API_KEY (upper-case) as the env var name
        case_sensitive=False,
    )


def get_settings() -> Settings:
    """Return a cached Settings instance (module-level singleton)."""
    return _settings


_settings = Settings()
