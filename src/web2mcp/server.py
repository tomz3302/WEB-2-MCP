"""
web2mcp – FastMCP server.

Exposes three MCP tools that any MCP-compatible agent can call:

| Tool                      | Description                                      |
|---------------------------|--------------------------------------------------|
| ``browse_and_extract``    | LLM-driven browser navigation with stealth       |
| ``scrape_page``           | Lightweight stealth Playwright scrape            |
| ``extract_structured_data``| browse-use + PydanticAI structured extraction   |

Run directly with::

    python -m web2mcp.server          # stdio transport (default)
    python -m web2mcp.server --http   # HTTP/SSE transport on port 8000

Or via the installed CLI entry-point::

    web2mcp

Environment variables (see .env.example):
    OPENAI_API_KEY   – Required for the default OpenAI provider.
    LLM_MODEL        – Model name (default: gpt-4o).
    BROWSER_HEADLESS – Set to 'false' to show the browser window.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from .browser_agent import WebBrowserAgent
from .config import get_settings
from .models import BrowseResult, ExtractionResult, ScrapeResult

logger = logging.getLogger(__name__)

# ── FastMCP server instance ────────────────────────────────────────────────────

mcp = FastMCP(
    name=get_settings().mcp_server_name,
    instructions=(
        "WEB-2-MCP turns any live website into callable MCP tools. "
        "Use 'browse_and_extract' for LLM-driven interaction, "
        "'scrape_page' for fast content extraction, "
        "and 'extract_structured_data' for schema-constrained JSON output."
    ),
)

# Module-level agent instance (re-used across tool calls).
_agent = WebBrowserAgent()


# ── MCP tools ─────────────────────────────────────────────────────────────────


@mcp.tool(
    name="browse_and_extract",
    description=(
        "Navigate to a URL using an LLM-driven browser agent (browser-use) "
        "running in Playwright stealth mode and perform the requested task. "
        "The agent can click, scroll, fill forms, and navigate multi-page flows "
        "autonomously. Returns the extracted content as plain text."
    ),
)
async def browse_and_extract(
    url: Annotated[str, Field(description="Full URL to visit (must include scheme).")],
    task: Annotated[
        str,
        Field(
            description=(
                "Natural-language instruction for the browser agent. "
                "Example: 'Find the top 5 trending repositories and return their names and star counts.'"
            )
        ),
    ],
    max_steps: Annotated[
        int,
        Field(
            default=50,
            ge=1,
            le=200,
            description="Maximum number of browser interaction steps.",
        ),
    ] = 50,
) -> BrowseResult:
    """LLM-driven stealth browser task."""
    return await _agent.browse_and_extract(url=url, task=task, max_steps=max_steps)


@mcp.tool(
    name="scrape_page",
    description=(
        "Scrape the visible text content (and optionally all hyperlinks) from a "
        "URL using Playwright in stealth mode. No LLM is involved – this is a fast "
        "deterministic operation. Optionally wait for a CSS selector before "
        "extracting content (useful for JavaScript-rendered pages)."
    ),
)
async def scrape_page(
    url: Annotated[str, Field(description="Full URL to scrape.")],
    wait_for_selector: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional CSS selector to wait for before extracting content. "
                "Useful for SPA pages where content loads asynchronously."
            ),
        ),
    ] = None,
    include_links: Annotated[
        bool,
        Field(
            default=False,
            description="Set to true to include all hyperlinks found on the page.",
        ),
    ] = False,
) -> ScrapeResult:
    """Fast stealth page scrape."""
    return await _agent.scrape_page(
        url=url,
        wait_for_selector=wait_for_selector,
        include_links=include_links,
    )


@mcp.tool(
    name="extract_structured_data",
    description=(
        "Browse a URL with the LLM-driven browser agent (browser-use + stealth "
        "Playwright), then use PydanticAI to structure the extracted content into "
        "a JSON object matching a plain-English schema description. "
        "Ideal when you need typed, validated output from a dynamic website."
    ),
)
async def extract_structured_data(
    url: Annotated[str, Field(description="Full URL to visit.")],
    task: Annotated[
        str,
        Field(
            description=(
                "Browsing task for the browser agent. "
                "Example: 'Go to the product listing page and collect all visible products.'"
            )
        ),
    ],
    schema_description: Annotated[
        str,
        Field(
            description=(
                "Plain-English description of the JSON structure you want. "
                "Example: 'A list of products, each with: name (string), "
                "price (number), rating (number 0-5), in_stock (boolean).'"
            )
        ),
    ],
) -> ExtractionResult:
    """Structured data extraction with browser-use + PydanticAI."""
    return await _agent.extract_structured_data(
        url=url,
        task=task,
        schema_description=schema_description,
    )


# ── Entry-point ────────────────────────────────────────────────────────────────


def main() -> None:
    """Start the MCP server (stdio transport by default)."""
    import sys

    transport = "stdio"
    if "--http" in sys.argv:
        transport = "streamable-http"

    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
