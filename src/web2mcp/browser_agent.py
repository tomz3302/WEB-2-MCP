"""
web2mcp – Browser agent.

Combines three technologies:

* **browser-use**: LLM-driven browser interaction (navigate, click, fill forms …)
* **playwright-stealth** (via ``playwright_stealth.Stealth``): Injects JavaScript
  patches that hide Playwright's automation fingerprint from anti-bot systems.
  For browser-use tasks the stealth payload is registered as a CDP init script
  so it runs on every new document.  For lightweight scraping a pure Playwright
  session is used and ``Stealth.apply_stealth_async`` is called directly.
* **PydanticAI**: Type-safe agent that structures the raw content returned by
  browser-use into the JSON schema requested by the caller.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_openai import ChatOpenAI
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.models.openai import OpenAIModel

from browser_use import Agent as BrowserAgent, BrowserProfile, BrowserSession
from browser_use.browser.events import BrowserConnectedEvent

from .config import Settings, get_settings
from .models import (
    BrowseResult,
    ExtractionResult,
    ScrapeResult,
    StructuredWebData,
)

logger = logging.getLogger(__name__)

# ── Stealth Chromium launch arguments ─────────────────────────────────────────

#: Extra Chromium flags that complement the JavaScript-level stealth patches.
STEALTH_CHROMIUM_ARGS: list[str] = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=AutomationControlled",
    "--disable-infobars",
    "--no-first-run",
    "--no-service-autorun",
    "--password-store=basic",
    "--use-mock-keychain",
    "--lang=en-US",
    "--accept-lang=en-US,en;q=0.9",
]


# ── Main agent class ───────────────────────────────────────────────────────────


class WebBrowserAgent:
    """Orchestrates browser-use, playwright-stealth, and PydanticAI together."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._stealth = Stealth()

    # ── LLM factories ─────────────────────────────────────────────────────────

    def _build_langchain_llm(self) -> ChatOpenAI:
        """Return a LangChain chat model for use with browser-use."""
        cfg = self._settings
        if cfg.llm_provider == "openai":
            return ChatOpenAI(
                model=cfg.llm_model,
                api_key=cfg.openai_api_key or None,
                base_url=cfg.openai_base_url,
            )
        raise ValueError(
            f"Unsupported llm_provider '{cfg.llm_provider}'.  "
            "Supported values: 'openai'."
        )

    def _build_pydantic_ai_model(self) -> OpenAIModel:
        """Return a PydanticAI model for use with the structuring agent."""
        cfg = self._settings
        if cfg.llm_provider == "openai":
            return OpenAIModel(
                cfg.llm_model,
                api_key=cfg.openai_api_key or None,
                base_url=cfg.openai_base_url,
            )
        raise ValueError(
            f"Unsupported llm_provider '{cfg.llm_provider}'.  "
            "Supported values: 'openai'."
        )

    # ── Stealth browser-session factory ───────────────────────────────────────

    def _build_stealth_session(self) -> BrowserSession:
        """
        Create a *browser-use* ``BrowserSession`` with stealth mode enabled.

        Stealth is applied at two layers:
        1. **Chromium launch args** – disable obvious automation flags.
        2. **CDP init script** – the ``playwright_stealth`` JS payload is
           registered via ``Page.addScriptToEvaluateOnNewDocument`` as soon as
           the browser connects so it runs before any page JavaScript.
        """
        profile = BrowserProfile(
            headless=self._settings.browser_headless,
            args=STEALTH_CHROMIUM_ARGS,
        )
        session = BrowserSession(browser_profile=profile)

        # Register the stealth script injection handler.
        stealth_payload = self._stealth.script_payload

        async def _inject_stealth(_event: BrowserConnectedEvent) -> None:
            if stealth_payload:
                try:
                    await session._cdp_add_init_script(stealth_payload)
                    logger.debug("Stealth init script injected via CDP.")
                except Exception:
                    logger.warning(
                        "Could not inject stealth init script; "
                        "continuing without JS-level stealth.",
                        exc_info=True,
                    )

        session.event_bus.on(BrowserConnectedEvent, _inject_stealth)
        return session

    # ── Public tool implementations ────────────────────────────────────────────

    async def browse_and_extract(
        self,
        url: str,
        task: str,
        max_steps: int = 50,
    ) -> BrowseResult:
        """
        Use a **browser-use** ``Agent`` (backed by a stealth Playwright session)
        to navigate *url* and carry out *task*.

        The LLM drives the browser autonomously — clicking, scrolling, filling
        forms — up to *max_steps* times before returning the final result.
        """
        cfg = self._settings
        session = self._build_stealth_session()
        llm = self._build_langchain_llm()

        full_task = f"Navigate to {url} and {task}. Summarise the result."

        agent = BrowserAgent(
            task=full_task,
            llm=llm,
            browser_session=session,
        )

        try:
            history = await agent.run(max_steps=max_steps)
            content = history.final_result() or ""
            steps = history.number_of_steps()
            success = not history.has_errors()

            return BrowseResult(
                url=url,
                content=content,
                success=success,
                steps_taken=steps,
            )
        except Exception as exc:
            logger.error("browse_and_extract failed for %s: %s", url, exc)
            return BrowseResult(
                url=url,
                content="",
                success=False,
                error=str(exc),
            )
        finally:
            try:
                await session.kill()
            except Exception:
                pass

    async def scrape_page(
        self,
        url: str,
        wait_for_selector: str | None = None,
        include_links: bool = False,
    ) -> ScrapeResult:
        """
        Lightweight page scrape using **pure Playwright** with
        ``playwright_stealth.Stealth.apply_stealth_async`` applied to both
        the browser context and every page.

        No LLM is involved; this simply returns the visible text and,
        optionally, all hyperlinks found on the page.
        """
        cfg = self._settings
        stealth = self._stealth

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    headless=cfg.browser_headless,
                    args=STEALTH_CHROMIUM_ARGS,
                )
                context = await browser.new_context()

                # Apply stealth at the context level so every page inherits it.
                await stealth.apply_stealth_async(context)

                # Also apply stealth to any page created inside this context.
                context.on(
                    "page",
                    lambda page: asyncio.ensure_future(
                        stealth.apply_stealth_async(page)
                    ),
                )

                page = await context.new_page()

                await page.goto(url, timeout=cfg.browser_timeout)

                if wait_for_selector:
                    await page.wait_for_selector(
                        wait_for_selector, timeout=cfg.browser_timeout
                    )

                title = await page.title()
                text = await page.evaluate(
                    "() => document.body ? document.body.innerText : ''"
                )

                links: list[str] = []
                if include_links:
                    hrefs = await page.evaluate(
                        "() => Array.from(document.querySelectorAll('a[href]'))"
                        ".map(a => a.href)"
                    )
                    links = [h for h in hrefs if isinstance(h, str) and h.startswith("http")]

                await browser.close()

                return ScrapeResult(
                    url=url,
                    title=title,
                    text=text,
                    links=links,
                    success=True,
                )

        except Exception as exc:
            logger.error("scrape_page failed for %s: %s", url, exc)
            return ScrapeResult(
                url=url,
                success=False,
                error=str(exc),
            )

    async def extract_structured_data(
        self,
        url: str,
        task: str,
        schema_description: str,
    ) -> ExtractionResult:
        """
        Two-phase extraction combining **browser-use** and **PydanticAI**:

        1. A browser-use ``Agent`` browses *url*, performs *task*, and returns
           the raw text content from the page.
        2. A **PydanticAI** ``Agent`` receives that raw content together with
           *schema_description* and returns a ``StructuredWebData`` object
           containing a typed ``dict`` that matches the requested schema.
        """
        # Phase 1 – browser-use collects raw content
        browse_result = await self.browse_and_extract(url, task)
        raw_content = browse_result.content

        if not browse_result.success or not raw_content:
            return ExtractionResult(
                url=url,
                raw_content=raw_content,
                success=False,
                error=browse_result.error or "No content extracted from page.",
            )

        # Phase 2 – PydanticAI structures the raw content
        try:
            pa_model = self._build_pydantic_ai_model()
            structuring_agent: PydanticAgent[None, StructuredWebData] = PydanticAgent(
                pa_model,
                output_type=StructuredWebData,
                system_prompt=(
                    "You are a data extraction assistant. "
                    "Given raw web page content, extract the requested information "
                    "and return it as structured JSON conforming to the schema description. "
                    "Set confidence to a value between 0 and 1 indicating how "
                    "completely the data was extracted."
                ),
            )

            prompt = (
                f"Schema description: {schema_description}\n\n"
                f"Raw page content:\n{raw_content[:8000]}"
            )
            result = await structuring_agent.run(prompt)
            structured: StructuredWebData = result.output

            return ExtractionResult(
                url=url,
                data=structured.data,
                raw_content=raw_content,
                success=True,
            )

        except Exception as exc:
            logger.error("PydanticAI structuring failed for %s: %s", url, exc)
            return ExtractionResult(
                url=url,
                raw_content=raw_content,
                success=False,
                error=f"Structuring failed: {exc}",
            )
