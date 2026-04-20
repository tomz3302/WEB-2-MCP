# Web2MCP: Bridging the "API-less" Web to AI Agents

Web2MCP solves the problem of **"API-less data."** While AI agents in 2026 are highly capable, they struggle to interact with websites that lack APIs or require brittle, manual scrapers. Web2MCP uses an LLM to navigate the web like a human and packages that capability into a standardized **Model Context Protocol (MCP)** tool.

## Core Architecture

The system operates across three distinct layers:

### 1. The Discovery Layer (browser-use)
Instead of manual CSS selectors, you provide a goal (e.g., "Find the next Bus 42 on the transit site").
- **Mechanism:** `browser-use` takes screenshots and sends them to a vision model.
- **Action:** The model identifies elements by coordinates and interacts with them.
- **Result:** The agent successfully navigates to the target data.

### 2. The Recording Layer (The "Trace")
To ensure speed and cost-efficiency, the navigation is recorded.
- **Trace JSON:** Stores the sequence of actions (URL -> Click -> Select -> Extract).
- **Hybrid Paths:** Stores both "hard" CSS selectors and "semantic" paths (labels/text) for redundancy.

### 3. The Serving Layer (FastMCP)
The recorded trace is wrapped in an MCP server.
- **Integration:** Tools appear directly in IDEs like Cursor or Claude Desktop.
- **Execution:** When called, the Python script executes the pre-recorded trace.

## The "Self-Healing" Logic

Websites change constantly, which typically breaks scrapers. Web2MCP implements a self-healing loop:

1.  **Trace Failure:** An element (e.g., `button#submit`) is missing or moved.
2.  **Detection:** The system triggers a `HealingAgent` instead of crashing.
3.  **Recovery:** The vision loop identifies the new location of the element on the live page.
4.  **Patching:** The Trace JSON is updated with the new selector, and execution resumes.

---