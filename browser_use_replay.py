"""
browser_use_replay.py
─────────────────────
Two-phase, zero-LLM replay of any browser-use AgentHistoryList.

PHASE 1 – extract_steps(history)
    Walks every AgentHistory item and emits a flat list of plain dicts
    (ReplayStep).  Each dict has enough data to re-execute the action
    with only Playwright – no model, no DOM introspection.
    Also captures the `href` attribute from <a> elements so link clicks
    can be replayed as direct navigations (see Phase 2).

PHASE 2 – replay_steps(steps, page)
    Given a Playwright Page (already open) and the list from Phase 1,
    re-executes every step in order.  For click actions the dispatcher
    uses a four-strategy fallback chain:
      0. href navigate  – if the clicked element was an <a> with a full
                          http(s) URL, goto() it directly.  This is the
                          most reliable strategy for search results and
                          any other link whose DOM position is dynamic.
      1. XPath          – fastest for stable pages
      2. stable_hash    – JS evaluation of browser-use's own hash
      3. ax_name        – accessible name / text content search
    Retries each action up to max_retries times with exponential backoff.

Serialisation helpers
    save_steps / load_steps – JSON round-trip so you can persist a
    workflow once and replay it any number of times.

Usage example
─────────────
    # After your agent run:
    steps = extract_steps(agent_history_list)
    save_steps(steps, "my_workflow.json")

    # Later, zero-LLM replay:
    steps = load_steps("my_workflow.json")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        page = await browser.new_page()
        await replay_steps(steps, page)
        await browser.close()
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Any

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ReplayStep:
    """
    One atomic browser action, fully self-contained.

    action_type values mirror browser-use's action names:
        navigate, search, click, input_text, scroll,
        send_keys, screenshot, extract_content, done
    """
    step_number:   int
    action_type:   str                     # e.g. "click"
    params:        dict[str, Any]          # action-specific payload
    # Element targeting (populated for DOM-interaction actions)
    xpath:         str | None = None       # absolute xpath from browser-use
    stable_hash:   int | None = None       # browser-use stable element hash
    ax_name:       str | None = None       # accessible name for fallback
    href:          str | None = None       # href attribute if element is a link
    # Timing hints
    delay_seconds: float = 1.0            # inter-step delay
    # Diagnostics
    original_had_error: bool = False      # was this step errored in original run?


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 – extraction
# ─────────────────────────────────────────────────────────────────────────────

def extract_steps(history_list: Any) -> list[ReplayStep]:
    """
    Turn an AgentHistoryList (the live object or a dict loaded from JSON)
    into a portable list of ReplayStep.

    Works with:
      • The actual browser-use AgentHistoryList object
      • A plain dict / list from json.load() of a saved history file
    """
    items = _iter_history_items(history_list)
    steps: list[ReplayStep] = []

    prev_elem_hash: int | None = None   # for redundant-retry detection
    prev_succeeded = False

    for item in items:
        model_output = _get(item, "model_output")
        if model_output is None:
            continue

        actions = _get(model_output, "action") or []
        if not actions or actions == [None]:
            continue

        metadata   = _get(item, "metadata") or {}
        results    = _get(item, "result") or []
        state      = _get(item, "state") or {}
        step_num   = _get(metadata, "step_number") or len(steps)
        step_interval = _get(metadata, "step_interval")
        delay      = min(float(step_interval), 45.0) if step_interval else 1.0
        had_error  = any(_get(r, "error") for r in results)

        # Grab the first interacted element (browser-use stores a list)
        interacted = _get(state, "interacted_element") or []
        elem = interacted[0] if interacted else None

        xpath       = _get(elem, "x_path") if elem else None
        stable_hash = _get(elem, "stable_hash") if elem else None
        ax_name     = _get(elem, "ax_name") if elem else None
        # Pull href out of attributes dict (present on <a> elements)
        attrs       = _get(elem, "attributes") if elem else None
        href        = (_get(attrs, "href") if isinstance(attrs, dict) else None) if attrs else None

        # --- Redundant retry detection ----------------------------------------
        # If previous step targeted the same element AND succeeded, skip.
        is_redundant = (
            stable_hash is not None
            and stable_hash == prev_elem_hash
            and prev_succeeded
        )
        if is_redundant:
            logger.debug("Step %d: skipping redundant retry of hash %d", step_num, stable_hash)
            continue
        # -----------------------------------------------------------------------

        for raw_action in actions:
            if raw_action is None:
                continue
            action_type, params = _parse_action(raw_action)
            if action_type is None:
                continue

            steps.append(ReplayStep(
                step_number=step_num,
                action_type=action_type,
                params=params,
                xpath=xpath,
                stable_hash=stable_hash,
                ax_name=ax_name,
                href=href,
                delay_seconds=delay,
                original_had_error=had_error,
            ))

        prev_elem_hash = stable_hash
        prev_succeeded = not had_error

    logger.info("Extracted %d replayable steps", len(steps))
    return steps


def _iter_history_items(history_list: Any) -> list[Any]:
    """Accept either the live object or a raw dict/list."""
    # Live AgentHistoryList object
    if hasattr(history_list, "history"):
        return list(history_list.history)
    # Already a list (e.g. from JSON)
    if isinstance(history_list, list):
        return history_list
    # Dict with a "history" key
    if isinstance(history_list, dict):
        return history_list.get("history", [])
    return []


def _parse_action(raw: Any) -> tuple[str | None, dict]:
    """
    browser-use actions are either:
      • A dict with one key  → {"click": {"index": 3}}
      • An object with known attributes

    Returns (action_type, params_dict) or (None, {}) if unrecognised.
    """
    if isinstance(raw, dict):
        if len(raw) == 1:
            action_type = next(iter(raw))
            params = raw[action_type] or {}
            if not isinstance(params, dict):
                params = {"value": params}
            return action_type, params
        # Flat dict (action_type is a key)
        action_type = raw.get("action_type") or raw.get("type")
        if action_type:
            return action_type, {k: v for k, v in raw.items() if k not in ("action_type", "type")}
    # Pydantic / dataclass object
    if hasattr(raw, "__dict__"):
        d = raw.__dict__
        # Try to find the filled field
        for k, v in d.items():
            if v is not None and not k.startswith("_"):
                return k, v if isinstance(v, dict) else {"value": v}
    return None, {}


def _get(obj: Any, key: str) -> Any:
    """Attribute or dict key access, returns None on miss."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


# ─────────────────────────────────────────────────────────────────────────────
# Serialisation helpers
# ─────────────────────────────────────────────────────────────────────────────

def save_steps(steps: list[ReplayStep], path: str) -> None:
    """Persist steps to a JSON file for zero-dependency reuse."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([asdict(s) for s in steps], fh, indent=2, ensure_ascii=False)
    logger.info("Saved %d steps → %s", len(steps), path)


def load_steps(path: str) -> list[ReplayStep]:
    """Load steps previously saved with save_steps()."""
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    steps = [ReplayStep(**item) for item in raw]
    logger.info("Loaded %d steps ← %s", len(steps), path)
    return steps


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 – Playwright replay
# ─────────────────────────────────────────────────────────────────────────────

async def replay_steps(
    steps: list[ReplayStep],
    page: Any,                       # playwright.async_api.Page
    *,
    skip_errored: bool = True,       # skip steps that had errors in original run
    max_retries: int = 3,
    max_delay: float = 45.0,
    timeout_ms: int = 10_000,        # per-action Playwright timeout
) -> list[dict]:
    """
    Replay extracted steps on an already-open Playwright page.

    Returns a list of result dicts, one per step, with keys:
        step_number, action_type, status ("ok" | "skipped" | "failed"), error
    """
    results = []

    for step in steps:
        label = f"Step {step.step_number} [{step.action_type}]"

        # ── skip errored originals ────────────────────────────────────────────
        if skip_errored and step.original_had_error:
            logger.warning("%s: skipping (original had error)", label)
            results.append(_result(step, "skipped", "original had error"))
            continue

        # ── inter-step delay ──────────────────────────────────────────────────
        delay = min(step.delay_seconds, max_delay)
        if delay > 0:
            await asyncio.sleep(delay)

        # ── execute with retry ────────────────────────────────────────────────
        last_error: str | None = None
        succeeded = False
        for attempt in range(1, max_retries + 1):
            try:
                await _execute_step(step, page, timeout_ms=timeout_ms)
                succeeded = True
                break
            except Exception as exc:
                last_error = str(exc)
                if attempt < max_retries:
                    backoff = min(5.0 * (2 ** (attempt - 1)), 30.0)
                    logger.warning(
                        "%s attempt %d/%d failed: %s – retrying in %.1fs",
                        label, attempt, max_retries, last_error, backoff,
                    )
                    await asyncio.sleep(backoff)
                else:
                    logger.error("%s failed after %d attempts: %s", label, max_retries, last_error)

        if succeeded:
            logger.info("%s: ok", label)
            results.append(_result(step, "ok"))
        else:
            results.append(_result(step, "failed", last_error))

    return results


def _result(step: ReplayStep, status: str, error: str | None = None) -> dict:
    return {
        "step_number": step.step_number,
        "action_type": step.action_type,
        "status": status,
        "error": error,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Action dispatcher
# ─────────────────────────────────────────────────────────────────────────────

async def _execute_step(step: ReplayStep, page: Any, timeout_ms: int) -> None:
    """Route a ReplayStep to the appropriate Playwright call."""
    t = step.action_type

    if t == "navigate":
        url = step.params.get("url", "")
        await page.goto(url, timeout=timeout_ms * 3)

    elif t == "search":
        # browser-use's search action uses DuckDuckGo / Google by default
        engine = step.params.get("engine", "duckduckgo").lower()
        query  = step.params.get("query", "")
        url = _search_url(engine, query)
        await page.goto(url, timeout=timeout_ms * 3)

    elif t in ("click", "right_click", "double_click"):
        # ── Strategy 0: if the element is a plain link with a known href,
        #    navigate directly instead of trying to re-find it in the DOM.
        #    This is the most reliable approach for search-result links and
        #    any other <a> elements whose DOM position is dynamic.
        if t == "click" and step.href and _is_navigable_href(step.href):
            logger.debug("Click on <a href=%r>: using goto instead of DOM click", step.href)
            await page.goto(step.href, timeout=timeout_ms * 3)
        else:
            locator = await _locate_element(step, page, timeout_ms)
            if t == "right_click":
                await locator.click(button="right", timeout=timeout_ms)
            elif t == "double_click":
                await locator.dbl_click(timeout=timeout_ms)
            else:
                await locator.click(timeout=timeout_ms)

    elif t == "input_text":
        locator = await _locate_element(step, page, timeout_ms)
        text = step.params.get("text", "")
        await locator.fill(text, timeout=timeout_ms)

    elif t == "send_keys":
        keys = step.params.get("keys", "")
        await page.keyboard.press(keys)

    elif t == "scroll":
        direction = step.params.get("direction", "down").lower()
        amount    = int(step.params.get("amount", 3))
        delta = amount * 100
        if direction == "down":
            await page.mouse.wheel(0, delta)
        elif direction == "up":
            await page.mouse.wheel(0, -delta)
        elif direction == "right":
            await page.mouse.wheel(delta, 0)
        elif direction == "left":
            await page.mouse.wheel(-delta, 0)

    elif t == "go_back":
        await page.go_back(timeout=timeout_ms)

    elif t == "go_forward":
        await page.go_forward(timeout=timeout_ms)

    elif t == "screenshot":
        path = step.params.get("path", "screenshot.png")
        await page.screenshot(path=path)

    elif t == "wait":
        ms = int(step.params.get("ms", 1000))
        await asyncio.sleep(ms / 1000)

    elif t in ("extract_content", "done"):
        # No browser action needed – these are terminal / metadata steps
        pass

    else:
        # Unknown action – best effort: if there's an element, click it
        if step.xpath or step.stable_hash:
            locator = await _locate_element(step, page, timeout_ms)
            await locator.click(timeout=timeout_ms)
        else:
            logger.warning("Unknown action type %r – skipping", t)


def _search_url(engine: str, query: str) -> str:
    import urllib.parse
    q = urllib.parse.quote_plus(query)
    urls = {
        "duckduckgo": f"https://duckduckgo.com/?q={q}&ia=web",
        "google":     f"https://www.google.com/search?q={q}",
        "bing":       f"https://www.bing.com/search?q={q}",
    }
    return urls.get(engine, f"https://duckduckgo.com/?q={q}")


def _is_navigable_href(href: str) -> bool:
    """
    Return True if the href is a full URL we can safely goto() rather than
    a fragment (#section), javascript: void, or relative path that needs
    the current page's base URL to resolve correctly.

    Full http(s) URLs → True  (safe to goto directly)
    #fragment, javascript:, mailto:, relative paths → False (fall through to DOM click)
    """
    if not href:
        return False
    low = href.strip().lower()
    if low.startswith(("http://", "https://")):
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Element location  (mirrors browser-use's fallback chain)
# ─────────────────────────────────────────────────────────────────────────────

async def _locate_element(step: ReplayStep, page: Any, timeout_ms: int) -> Any:
    """
    Try to locate the saved element using three strategies in order:
      1. XPath  – fastest, breaks if DOM structure changed
      2. stable_hash – JS evaluation of browser-use's own hash function
      3. ax_name  – accessible name / text content search (most resilient)

    Raises RuntimeError if all strategies fail.
    """
    errors: list[str] = []

    # ── Strategy 1: XPath ─────────────────────────────────────────────────────
    if step.xpath:
        try:
            loc = page.locator(f"xpath={step.xpath}")
            await loc.wait_for(state="visible", timeout=timeout_ms)
            logger.debug("Located via xpath: %s", step.xpath)
            return loc
        except Exception as exc:
            errors.append(f"xpath: {exc}")

    # ── Strategy 2: stable_hash ───────────────────────────────────────────────
    if step.stable_hash:
        try:
            loc = await _find_by_stable_hash(page, step.stable_hash, timeout_ms)
            if loc is not None:
                logger.debug("Located via stable_hash: %d", step.stable_hash)
                return loc
        except Exception as exc:
            errors.append(f"stable_hash: {exc}")

    # ── Strategy 3: ax_name text search ───────────────────────────────────────
    if step.ax_name:
        try:
            loc = await _find_by_ax_name(page, step.ax_name, timeout_ms)
            if loc is not None:
                logger.debug("Located via ax_name: %r", step.ax_name)
                return loc
        except Exception as exc:
            errors.append(f"ax_name: {exc}")

    raise RuntimeError(
        f"Could not find element for step {step.step_number} "
        f"[{step.action_type}]. Tried: {'; '.join(errors)}"
    )


async def _find_by_stable_hash(page: Any, target_hash: int, timeout_ms: int) -> Any | None:
    """
    Evaluate browser-use's stable_hash on every interactive element
    and return the matching Playwright locator.

    The stable_hash is computed from element attributes in browser-use's
    DomService.  We replicate a compatible hash over the same attributes.
    """
    # JS implementation that mirrors browser-use's Python stable_hash logic.
    # browser-use hashes: tag + id + name + class + type + role + aria-label
    # using a simple djb2-style fold over the concatenated string.
    js = """
    (targetHash) => {
        function stableHash(s) {
            let h = 0n;
            for (let i = 0; i < s.length; i++) {
                h = (h * 31n + BigInt(s.charCodeAt(i))) & 0xFFFFFFFFFFFFFFFFn;
            }
            // Convert to signed 64-bit (matches Python's ctypes.c_int64)
            if (h >= 0x8000000000000000n) h -= 0x10000000000000000n;
            return Number(h);
        }

        const interactable = document.querySelectorAll(
            'a, button, input, select, textarea, [role="button"], ' +
            '[role="link"], [role="checkbox"], [role="menuitem"], ' +
            '[onclick], [tabindex]'
        );

        for (const el of interactable) {
            const sig = [
                el.tagName.toLowerCase(),
                el.id || '',
                el.name || '',
                el.className || '',
                el.type || '',
                el.getAttribute('role') || '',
                el.getAttribute('aria-label') || '',
            ].join('|');
            if (stableHash(sig) === targetHash) {
                return el;
            }
        }
        return null;
    }
    """
    try:
        element_handle = await page.evaluate_handle(js, target_hash)
        if element_handle:
            as_element = element_handle.as_element()
            if as_element:
                return page.locator(f"xpath={await _get_xpath(as_element)}")
    except Exception:
        pass
    return None


async def _find_by_ax_name(page: Any, ax_name: str, timeout_ms: int) -> Any | None:
    """
    Search for an element whose accessible name or visible text matches
    ax_name.  Tries role=button/link first, then falls back to text content.
    """
    # Try ARIA role-based locators first (most reliable for interactive elements)
    for role in ("button", "link", "menuitem", "option", "checkbox", "tab"):
        try:
            loc = page.get_by_role(role, name=ax_name, exact=False)
            if await loc.count() > 0:
                return loc.first
        except Exception:
            pass

    # Fall back to visible text
    try:
        loc = page.get_by_text(ax_name, exact=False)
        if await loc.count() > 0:
            return loc.first
    except Exception:
        pass

    return None


async def _get_xpath(element_handle: Any) -> str:
    """Compute an absolute XPath for a Playwright ElementHandle."""
    js = """
    (el) => {
        const parts = [];
        while (el && el.nodeType === Node.ELEMENT_NODE) {
            let idx = 1;
            let sib = el.previousSibling;
            while (sib) {
                if (sib.nodeType === Node.ELEMENT_NODE &&
                    sib.tagName === el.tagName) idx++;
                sib = sib.previousSibling;
            }
            parts.unshift(el.tagName.toLowerCase() + '[' + idx + ']');
            el = el.parentNode;
        }
        return '/' + parts.join('/');
    }
    """
    return await element_handle.evaluate(js)


# ─────────────────────────────────────────────────────────────────────────────
# End-to-end convenience wrapper
# ─────────────────────────────────────────────────────────────────────────────

async def run_workflow(
    history_list: Any,
    *,
    steps_json: str | None = None,   # optional: persist extracted steps here
    headless: bool = False,
    skip_errored: bool = True,
    max_retries: int = 3,
) -> list[dict]:
    """
    One-shot: extract → (optionally save) → replay.

        from playwright.async_api import async_playwright

        async def main():
            results = await run_workflow(
                my_agent_history_list,
                steps_json="workflow.json",
            )
            for r in results:
                print(r["step_number"], r["action_type"], r["status"])

        asyncio.run(main())
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise ImportError("Install playwright: pip install playwright && playwright install") from exc

    steps = extract_steps(history_list)
    if steps_json:
        save_steps(steps, steps_json)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        page = await browser.new_page()
        try:
            results = await replay_steps(
                steps, page,
                skip_errored=skip_errored,
                max_retries=max_retries,
            )
        finally:
            await browser.close()

    return results