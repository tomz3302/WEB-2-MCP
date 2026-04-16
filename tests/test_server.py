"""
Tests for the FastMCP server and WebBrowserAgent tool implementations.

All external I/O (Playwright browser, browser-use Agent, OpenAI API) is mocked
so that these tests remain fast and require no network access or API keys.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from web2mcp.models import BrowseResult, ScrapeResult, ExtractionResult
from web2mcp.browser_agent import WebBrowserAgent, STEALTH_CHROMIUM_ARGS
from web2mcp.config import Settings


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def settings() -> Settings:
    """Minimal settings for tests (no real API keys needed)."""
    return Settings(
        openai_api_key="sk-test",
        browser_headless=True,
        max_browser_steps=5,
    )


@pytest.fixture
def agent(settings: Settings) -> WebBrowserAgent:
    return WebBrowserAgent(settings=settings)


# ── STEALTH_CHROMIUM_ARGS sanity checks ────────────────────────────────────────


class TestStealthArgs:
    def test_automation_flag_disabled(self):
        assert "--disable-blink-features=AutomationControlled" in STEALTH_CHROMIUM_ARGS

    def test_no_first_run(self):
        assert "--no-first-run" in STEALTH_CHROMIUM_ARGS


# ── WebBrowserAgent construction ───────────────────────────────────────────────


class TestWebBrowserAgentInit:
    def test_uses_provided_settings(self, agent: WebBrowserAgent, settings: Settings):
        assert agent._settings is settings

    def test_stealth_object_created(self, agent: WebBrowserAgent):
        from playwright_stealth import Stealth

        assert isinstance(agent._stealth, Stealth)

    def test_unsupported_provider_raises(self, settings: Settings):
        settings.llm_provider = "unsupported"
        a = WebBrowserAgent(settings=settings)
        with pytest.raises(ValueError, match="Unsupported llm_provider"):
            a._build_langchain_llm()

    def test_unsupported_provider_pydantic_ai_raises(self, settings: Settings):
        settings.llm_provider = "unsupported"
        a = WebBrowserAgent(settings=settings)
        with pytest.raises(ValueError, match="Unsupported llm_provider"):
            a._build_pydantic_ai_model()


# ── browse_and_extract ─────────────────────────────────────────────────────────


class TestBrowseAndExtract:
    @pytest.mark.asyncio
    async def test_success_path(self, agent: WebBrowserAgent):
        """Happy-path: browser-use Agent finishes and returns content."""
        mock_history = MagicMock()
        mock_history.final_result.return_value = "Extracted content"
        mock_history.number_of_steps.return_value = 3
        mock_history.has_errors.return_value = False

        mock_session = MagicMock()
        mock_session.event_bus = MagicMock()
        mock_session.event_bus.on = MagicMock()
        mock_session.kill = AsyncMock()

        mock_llm = MagicMock()

        mock_browser_agent = AsyncMock()
        mock_browser_agent.run.return_value = mock_history

        with (
            patch.object(agent, "_build_stealth_session", return_value=mock_session),
            patch.object(agent, "_build_langchain_llm", return_value=mock_llm),
            patch("web2mcp.browser_agent.BrowserAgent", return_value=mock_browser_agent),
        ):
            result = await agent.browse_and_extract(
                url="https://example.com",
                task="Get the page title",
                max_steps=5,
            )

        assert isinstance(result, BrowseResult)
        assert result.success is True
        assert result.content == "Extracted content"
        assert result.steps_taken == 3
        assert result.error is None

    @pytest.mark.asyncio
    async def test_browser_exception_returns_failure(self, agent: WebBrowserAgent):
        """If the browser agent raises, browse_and_extract returns a failure result."""
        mock_session = MagicMock()
        mock_session.event_bus = MagicMock()
        mock_session.event_bus.on = MagicMock()
        mock_session.kill = AsyncMock()

        mock_browser_agent = AsyncMock()
        mock_browser_agent.run.side_effect = RuntimeError("Browser crashed")

        with (
            patch.object(agent, "_build_stealth_session", return_value=mock_session),
            patch.object(agent, "_build_langchain_llm", return_value=MagicMock()),
            patch("web2mcp.browser_agent.BrowserAgent", return_value=mock_browser_agent),
        ):
            result = await agent.browse_and_extract(
                url="https://example.com", task="task"
            )

        assert result.success is False
        assert "Browser crashed" in result.error
        mock_session.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_session_kill_called_on_success(self, agent: WebBrowserAgent):
        """Session.kill() must be called even on the happy path."""
        mock_history = MagicMock()
        mock_history.final_result.return_value = "ok"
        mock_history.number_of_steps.return_value = 1
        mock_history.has_errors.return_value = False

        mock_session = MagicMock()
        mock_session.event_bus = MagicMock()
        mock_session.event_bus.on = MagicMock()
        mock_session.kill = AsyncMock()

        mock_browser_agent = AsyncMock()
        mock_browser_agent.run.return_value = mock_history

        with (
            patch.object(agent, "_build_stealth_session", return_value=mock_session),
            patch.object(agent, "_build_langchain_llm", return_value=MagicMock()),
            patch("web2mcp.browser_agent.BrowserAgent", return_value=mock_browser_agent),
        ):
            await agent.browse_and_extract(url="https://example.com", task="task")

        mock_session.kill.assert_called_once()


# ── scrape_page ────────────────────────────────────────────────────────────────


class TestScrapePage:
    @pytest.mark.asyncio
    async def test_success_path(self, agent: WebBrowserAgent):
        """Happy-path scrape with mocked Playwright."""
        mock_page = AsyncMock()
        mock_page.title.return_value = "Test Title"
        mock_page.evaluate.side_effect = [
            "Hello World",  # body.innerText
        ]

        mock_context = AsyncMock()
        mock_context.new_page.return_value = mock_page
        # context.on() is a synchronous event-listener registration in Playwright.
        mock_context.on = MagicMock()

        mock_browser = AsyncMock()
        mock_browser.new_context.return_value = mock_context

        mock_pw = AsyncMock()
        mock_pw.chromium.launch.return_value = mock_browser

        mock_stealth = MagicMock()
        mock_stealth.apply_stealth_async = AsyncMock()
        mock_stealth.script_payload = "// stealth"
        agent._stealth = mock_stealth

        with patch(
            "web2mcp.browser_agent.async_playwright"
        ) as mock_ap:
            mock_ap.return_value.__aenter__.return_value = mock_pw
            result = await agent.scrape_page(url="https://example.com")

        assert isinstance(result, ScrapeResult)
        assert result.success is True
        assert result.title == "Test Title"
        assert result.text == "Hello World"
        assert result.links == []

    @pytest.mark.asyncio
    async def test_include_links(self, agent: WebBrowserAgent):
        """When include_links=True the result contains extracted hrefs."""
        mock_page = AsyncMock()
        mock_page.title.return_value = "Page"
        mock_page.evaluate.side_effect = [
            "text content",  # innerText
            ["https://a.com", "https://b.com"],  # links
        ]

        mock_context = AsyncMock()
        mock_context.new_page.return_value = mock_page
        mock_context.on = MagicMock()

        mock_browser = AsyncMock()
        mock_browser.new_context.return_value = mock_context

        mock_pw = AsyncMock()
        mock_pw.chromium.launch.return_value = mock_browser

        mock_stealth = MagicMock()
        mock_stealth.apply_stealth_async = AsyncMock()
        agent._stealth = mock_stealth

        with patch("web2mcp.browser_agent.async_playwright") as mock_ap:
            mock_ap.return_value.__aenter__.return_value = mock_pw
            result = await agent.scrape_page(
                url="https://example.com", include_links=True
            )

        assert result.links == ["https://a.com", "https://b.com"]

    @pytest.mark.asyncio
    async def test_playwright_exception_returns_failure(self, agent: WebBrowserAgent):
        """Playwright errors surface as a failure ScrapeResult."""
        mock_stealth = MagicMock()
        mock_stealth.apply_stealth_async = AsyncMock()
        agent._stealth = mock_stealth

        with patch("web2mcp.browser_agent.async_playwright") as mock_ap:
            mock_ap.return_value.__aenter__.side_effect = OSError("browser not found")
            result = await agent.scrape_page(url="https://example.com")

        assert result.success is False
        assert "browser not found" in result.error


# ── extract_structured_data ────────────────────────────────────────────────────


class TestExtractStructuredData:
    @pytest.mark.asyncio
    async def test_success_path(self, agent: WebBrowserAgent):
        """Browse succeeds and PydanticAI returns structured data."""
        from web2mcp.models import StructuredWebData

        mock_browse = BrowseResult(
            url="https://example.com",
            content="Widget A $9.99, Widget B $14.99",
            success=True,
            steps_taken=2,
        )

        mock_structured = StructuredWebData(
            data={"products": [{"name": "Widget A", "price": 9.99}]},
            confidence=0.95,
        )

        mock_pa_result = MagicMock()
        mock_pa_result.output = mock_structured

        mock_pa_agent = AsyncMock()
        mock_pa_agent.run.return_value = mock_pa_result

        with (
            patch.object(agent, "browse_and_extract", new=AsyncMock(return_value=mock_browse)),
            patch.object(agent, "_build_pydantic_ai_model", return_value=MagicMock()),
            patch("web2mcp.browser_agent.PydanticAgent", return_value=mock_pa_agent),
        ):
            result = await agent.extract_structured_data(
                url="https://example.com",
                task="Collect products",
                schema_description="List of products with name and price",
            )

        assert isinstance(result, ExtractionResult)
        assert result.success is True
        assert "products" in result.data
        assert result.raw_content == "Widget A $9.99, Widget B $14.99"

    @pytest.mark.asyncio
    async def test_browse_failure_propagates(self, agent: WebBrowserAgent):
        """If the browse step fails, the extraction result is also a failure."""
        mock_browse = BrowseResult(
            url="https://example.com",
            content="",
            success=False,
            error="Timeout",
        )

        with patch.object(
            agent, "browse_and_extract", new=AsyncMock(return_value=mock_browse)
        ):
            result = await agent.extract_structured_data(
                url="https://example.com",
                task="task",
                schema_description="schema",
            )

        assert result.success is False
        assert "Timeout" in (result.error or "")

    @pytest.mark.asyncio
    async def test_pydantic_ai_failure_propagates(self, agent: WebBrowserAgent):
        """PydanticAI errors surface as a failure ExtractionResult."""
        mock_browse = BrowseResult(
            url="https://example.com",
            content="some content",
            success=True,
        )

        mock_pa_agent = AsyncMock()
        mock_pa_agent.run.side_effect = RuntimeError("API quota exceeded")

        with (
            patch.object(agent, "browse_and_extract", new=AsyncMock(return_value=mock_browse)),
            patch.object(agent, "_build_pydantic_ai_model", return_value=MagicMock()),
            patch("web2mcp.browser_agent.PydanticAgent", return_value=mock_pa_agent),
        ):
            result = await agent.extract_structured_data(
                url="https://example.com",
                task="task",
                schema_description="schema",
            )

        assert result.success is False
        assert "API quota exceeded" in (result.error or "")


# ── FastMCP server tool registration ──────────────────────────────────────────


class TestMCPServerTools:
    @pytest.mark.asyncio
    async def test_tools_registered(self):
        """All three tools are registered on the FastMCP server."""
        from web2mcp.server import mcp

        tools = await mcp.list_tools()
        tool_names = {t.name for t in tools}
        assert "browse_and_extract" in tool_names
        assert "scrape_page" in tool_names
        assert "extract_structured_data" in tool_names

    def test_server_has_correct_name(self):
        from web2mcp.server import mcp

        assert mcp.name == "WEB-2-MCP"
