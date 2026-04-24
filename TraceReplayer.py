import json
import asyncio
from playwright.async_api import async_playwright

class TraceReplayer:
    def __init__(self, trace_path):
        with open(trace_path, 'r') as f:
            self.steps = json.load(f)

    async def run(self):
        async with async_playwright() as p:
            # Launch original playwright
            browser = await p.chromium.launch(headless=False)
            page = await browser.new_page()

            for step in self.steps:
                model_output = step.get("model_output")
                if not model_output: continue # Skip initialization/error steps

                actions = model_output.get("action", [])
                # The state contains details of the elements the agent touched
                interacted_elements = step.get("state", {}).get("interacted_element", [])

                for idx, action in enumerate(actions):
                    try:
                        await self.execute_action(page, action, interacted_elements[idx])
                    except Exception as e:
                        print(f"Fast-path failed at step {step['step_number']}: {e}")
                        # This is where you would call browser-use to "HEAL"
                        return 

            print("Automation completed successfully.")

    async def execute_action(self, page, action, element_data):
        # 1. Handle Searches (High-level mapping)
        if "search" in action:
            query = action["search"]["query"]
            print(f"Replaying Search: {query}")
            await page.goto(f"https://duckduckgo.com/?q={query.replace(' ', '+')}")

        # 2. Handle Clicks (Using the recorded XPath)
        elif "click" in action:
            xpath = element_data.get("x_path")
            print(f"Replaying Click on XPath: {xpath}")
            # Use Playwright's locator for better reliability
            await page.locator(f"xpath={xpath}").click(timeout=5000)

        # 3. Handle Navigation
        elif "go_to_url" in action:
            await page.goto(action["go_to_url"]["url"])

# To run it:
replayer = TraceReplayer("playwright_trace.json")
asyncio.run(replayer.run())