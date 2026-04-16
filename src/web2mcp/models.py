"""
web2mcp – Pydantic request / response models.

All public MCP tool inputs and outputs are typed through these models so that
callers receive well-structured, validated data.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, HttpUrl


# ── Tool inputs ────────────────────────────────────────────────────────────────


class BrowseRequest(BaseModel):
    """Input for the *browse_and_extract* tool."""

    url: str = Field(..., description="Full URL of the page to visit.")
    task: str = Field(
        ...,
        description=(
            "Natural-language description of what information to extract "
            "or what action to perform on the page."
        ),
    )
    max_steps: int = Field(
        50,
        ge=1,
        le=200,
        description="Maximum number of browser steps the agent may take.",
    )


class ScrapeRequest(BaseModel):
    """Input for the *scrape_page* tool."""

    url: str = Field(..., description="Full URL of the page to scrape.")
    wait_for_selector: str | None = Field(
        None,
        description="Optional CSS selector to wait for before extracting content.",
    )
    include_links: bool = Field(
        False, description="When True, the result includes all hyperlinks found."
    )


class ExtractionRequest(BaseModel):
    """Input for the *extract_structured_data* tool."""

    url: str = Field(..., description="Full URL of the page to visit.")
    task: str = Field(
        ...,
        description="Description of the browsing task to perform on the page.",
    )
    schema_description: str = Field(
        ...,
        description=(
            "Plain-English description of the JSON structure you want returned. "
            "Example: 'A list of products, each with name, price, and rating.'"
        ),
    )


# ── Tool outputs ───────────────────────────────────────────────────────────────


class BrowseResult(BaseModel):
    """Result returned by *browse_and_extract*."""

    url: str = Field(..., description="The URL that was visited.")
    content: str = Field(
        ..., description="Raw text extracted or produced by the browser agent."
    )
    success: bool = Field(True, description="Whether the agent completed the task.")
    error: str | None = Field(None, description="Error message if the task failed.")
    steps_taken: int = Field(0, description="Number of browser steps executed.")


class ScrapeResult(BaseModel):
    """Result returned by *scrape_page*."""

    url: str = Field(..., description="The URL that was scraped.")
    title: str = Field("", description="Page <title> value.")
    text: str = Field("", description="Visible text content of the page.")
    links: list[str] = Field(
        default_factory=list,
        description="All hyperlinks found on the page (only when requested).",
    )
    success: bool = Field(True, description="Whether the scrape succeeded.")
    error: str | None = Field(None, description="Error message if scraping failed.")


class ExtractionResult(BaseModel):
    """Result returned by *extract_structured_data*."""

    url: str = Field(..., description="The URL that was visited.")
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Extracted data structured according to *schema_description*.",
    )
    raw_content: str = Field(
        "", description="Raw content retrieved from the page before structuring."
    )
    success: bool = Field(True, description="Whether the extraction succeeded.")
    error: str | None = Field(None, description="Error message if extraction failed.")


# ── PydanticAI inner agent output ──────────────────────────────────────────────


class StructuredWebData(BaseModel):
    """Typed output produced by the PydanticAI structuring agent."""

    data: dict[str, Any] = Field(
        ..., description="Extracted data matching the requested schema."
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score between 0 and 1.",
    )
    notes: str = Field(
        "",
        description="Optional notes about missing fields or extraction caveats.",
    )
