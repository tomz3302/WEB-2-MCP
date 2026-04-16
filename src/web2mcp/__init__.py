"""web2mcp – Turns any dynamic website into a standardised MCP tool."""

from __future__ import annotations

from .browser_agent import WebBrowserAgent
from .config import Settings, get_settings
from .models import (
    BrowseRequest,
    BrowseResult,
    ExtractionRequest,
    ExtractionResult,
    ScrapeRequest,
    ScrapeResult,
    StructuredWebData,
)
from .server import mcp

__all__ = [
    "WebBrowserAgent",
    "Settings",
    "get_settings",
    "BrowseRequest",
    "BrowseResult",
    "ExtractionRequest",
    "ExtractionResult",
    "ScrapeRequest",
    "ScrapeResult",
    "StructuredWebData",
    "mcp",
]
