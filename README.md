# WEB-2-MCP

Turn any dynamic website into a standardised **Model Context Protocol (MCP)** tool that
other agents can call like a native function.

## Tech Stack

| Library | Role |
|---------|------|
| [**browser-use**](https://github.com/browser-use/browser-use) | LLM-driven browser interaction – clicks, scrolling, form-filling |
| [**PydanticAI**](https://ai.pydantic.dev/) | Type-safe, production-grade agent for structured output |
| [**FastMCP**](https://github.com/jlowin/fastmcp) | High-level Python SDK for building MCP servers in minutes |
| [**Playwright + playwright-stealth**](https://playwright.dev/) | Underlying browser instance with anti-bot evasion |

---

## MCP Tools

### `browse_and_extract`
Use a **browser-use** `Agent` (backed by a stealth Playwright session) to navigate
a URL and carry out an arbitrary task described in natural language.

```json
{
  "url": "https://news.ycombinator.com",
  "task": "Return the titles and URLs of the top 5 stories",
  "max_steps": 10
}
```

### `scrape_page`
Lightweight page scrape using **pure Playwright** with stealth patches applied.
No LLM involved – returns the visible text, page title, and optionally all links.

```json
{
  "url": "https://example.com",
  "include_links": true,
  "wait_for_selector": "#main-content"
}
```

### `extract_structured_data`
Two-phase extraction: **browser-use** browses the page, then a **PydanticAI**
agent structures the raw content into a typed JSON object matching a
plain-English schema description.

```json
{
  "url": "https://shop.example.com/products",
  "task": "Collect all visible products",
  "schema_description": "A list of products each with: name (string), price (number), in_stock (boolean)"
}
```

---

## Quick Start

### 1. Prerequisites

```bash
pip install -e ".[dev]"
playwright install chromium
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env and set OPENAI_API_KEY
```

### 3. Run the MCP server

```bash
# stdio transport (works with Claude Desktop and most MCP clients)
web2mcp

# HTTP / SSE transport (useful for testing with curl / Postman)
web2mcp --http
```

### 4. Use with Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "web2mcp": {
      "command": "web2mcp",
      "env": { "OPENAI_API_KEY": "sk-..." }
    }
  }
}
```

---

## Project Structure

```
src/
└── web2mcp/
    ├── __init__.py        # Public exports
    ├── config.py          # Settings (pydantic-settings)
    ├── models.py          # Pydantic I/O models
    ├── browser_agent.py   # WebBrowserAgent (browser-use + stealth + PydanticAI)
    └── server.py          # FastMCP server & tool definitions
tests/
    ├── test_models.py     # Model validation tests
    ├── test_config.py     # Settings tests
    └── test_server.py     # Agent & MCP tool tests (mocked I/O)
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | OpenAI API key (required) |
| `LLM_MODEL` | `gpt-4o` | Model to use |
| `LLM_PROVIDER` | `openai` | LLM provider (`openai`) |
| `BROWSER_HEADLESS` | `true` | Run browser headlessly |
| `BROWSER_TIMEOUT` | `30000` | Page-load timeout (ms) |
| `MAX_BROWSER_STEPS` | `50` | Max steps per browser-use task |
| `MCP_SERVER_NAME` | `WEB-2-MCP` | Server name shown to MCP clients |

---

## How Stealth Works

Stealth is applied at two complementary layers:

1. **Chromium launch flags** – `--disable-blink-features=AutomationControlled` and
   several companion flags hide obvious automation markers at the browser-process level.

2. **JavaScript init scripts** – `playwright_stealth.Stealth.script_payload` is
   registered via Chrome's `Page.addScriptToEvaluateOnNewDocument` (CDP) so the
   patches execute before any page JavaScript, spoofing `navigator.webdriver`,
   `navigator.plugins`, WebGL metadata, and more.

For the lightweight `scrape_page` tool, `Stealth.apply_stealth_async` is called
directly on the Playwright `BrowserContext` and every page created within it.

---

## Running Tests

```bash
pytest
```
