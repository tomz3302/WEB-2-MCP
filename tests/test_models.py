"""Tests for Pydantic models (models.py)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from web2mcp.models import (
    BrowseRequest,
    BrowseResult,
    ExtractionRequest,
    ExtractionResult,
    ScrapeRequest,
    ScrapeResult,
    StructuredWebData,
)


# ── BrowseRequest ──────────────────────────────────────────────────────────────


class TestBrowseRequest:
    def test_valid_minimal(self):
        req = BrowseRequest(url="https://example.com", task="Get the page title")
        assert req.url == "https://example.com"
        assert req.task == "Get the page title"
        assert req.max_steps == 50  # default

    def test_custom_max_steps(self):
        req = BrowseRequest(url="https://example.com", task="task", max_steps=10)
        assert req.max_steps == 10

    def test_max_steps_too_low(self):
        with pytest.raises(ValidationError):
            BrowseRequest(url="https://example.com", task="t", max_steps=0)

    def test_max_steps_too_high(self):
        with pytest.raises(ValidationError):
            BrowseRequest(url="https://example.com", task="t", max_steps=201)

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            BrowseRequest(url="https://example.com")  # task missing

    def test_serialisation_round_trip(self):
        req = BrowseRequest(url="https://example.com", task="t", max_steps=5)
        assert BrowseRequest(**req.model_dump()) == req


# ── BrowseResult ───────────────────────────────────────────────────────────────


class TestBrowseResult:
    def test_success_result(self):
        res = BrowseResult(url="https://example.com", content="Hello world", success=True)
        assert res.success is True
        assert res.error is None
        assert res.steps_taken == 0

    def test_failure_result(self):
        res = BrowseResult(
            url="https://example.com",
            content="",
            success=False,
            error="Timeout",
        )
        assert res.success is False
        assert res.error == "Timeout"

    def test_serialisation(self):
        res = BrowseResult(url="https://x.com", content="data", success=True, steps_taken=3)
        d = res.model_dump()
        assert d["steps_taken"] == 3
        assert d["error"] is None


# ── ScrapeRequest ──────────────────────────────────────────────────────────────


class TestScrapeRequest:
    def test_defaults(self):
        req = ScrapeRequest(url="https://example.com")
        assert req.wait_for_selector is None
        assert req.include_links is False

    def test_with_selector_and_links(self):
        req = ScrapeRequest(
            url="https://example.com",
            wait_for_selector="#main",
            include_links=True,
        )
        assert req.wait_for_selector == "#main"
        assert req.include_links is True


# ── ScrapeResult ───────────────────────────────────────────────────────────────


class TestScrapeResult:
    def test_success_result(self):
        res = ScrapeResult(
            url="https://example.com",
            title="Example",
            text="Hello",
            links=["https://other.com"],
            success=True,
        )
        assert res.title == "Example"
        assert len(res.links) == 1

    def test_empty_links_default(self):
        res = ScrapeResult(url="https://example.com", success=True)
        assert res.links == []
        assert res.text == ""

    def test_failure_result(self):
        res = ScrapeResult(url="https://example.com", success=False, error="DNS error")
        assert res.success is False
        assert res.error == "DNS error"


# ── ExtractionRequest ──────────────────────────────────────────────────────────


class TestExtractionRequest:
    def test_valid(self):
        req = ExtractionRequest(
            url="https://shop.example.com",
            task="Collect all product names",
            schema_description="List of product names as strings",
        )
        assert req.url == "https://shop.example.com"

    def test_missing_schema(self):
        with pytest.raises(ValidationError):
            ExtractionRequest(url="https://x.com", task="t")


# ── ExtractionResult ───────────────────────────────────────────────────────────


class TestExtractionResult:
    def test_success(self):
        res = ExtractionResult(
            url="https://example.com",
            data={"products": ["Widget A", "Widget B"]},
            raw_content="raw text",
            success=True,
        )
        assert res.data["products"] == ["Widget A", "Widget B"]

    def test_empty_data_default(self):
        res = ExtractionResult(url="https://x.com", success=True)
        assert res.data == {}
        assert res.raw_content == ""


# ── StructuredWebData ──────────────────────────────────────────────────────────


class TestStructuredWebData:
    def test_valid(self):
        s = StructuredWebData(
            data={"key": "value"},
            confidence=0.9,
            notes="Some fields were missing.",
        )
        assert s.confidence == 0.9
        assert s.notes == "Some fields were missing."

    def test_confidence_out_of_range(self):
        with pytest.raises(ValidationError):
            StructuredWebData(data={}, confidence=1.5)

    def test_confidence_negative(self):
        with pytest.raises(ValidationError):
            StructuredWebData(data={}, confidence=-0.1)

    def test_notes_default_empty(self):
        s = StructuredWebData(data={"x": 1}, confidence=0.5)
        assert s.notes == ""
