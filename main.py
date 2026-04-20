
import asyncio
import os
from dotenv import load_dotenv


from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.google import GoogleModel
from browser_use import Agent as BrowserAgent, ChatGoogle
from dataclasses import dataclass

# 1. Define your dependencies (The "Kitchen Equipment")
@dataclass
class BrowserDeps:
    llm: ChatGoogle

# 2. Define the structured output you want (The "Menu")
class ResearchResult(BaseModel):
    title: str
    summary: str
    url: str

# 3. Create the PydanticAI Agent

model = GoogleModel('gemma-4-31b-it')

research_agent = Agent(
    model=model,
    deps_type=BrowserDeps,
    output_type=ResearchResult, # walla output_type?
    system_prompt="You are a research assistant. Use the browser tool to find papers."
)

# 4. Wrap your browser-use code in a Tool
@research_agent.tool
async def search_meta_research(ctx: RunContext[BrowserDeps], query: str) -> str:
    """Uses a real browser to find specific research papers."""
    browser_agent = BrowserAgent(
        task=f"Find the paper: {query}",
        llm=ChatGoogle(model='models/gemma-4-31b-it')
    )
    history = await browser_agent.run()
    return history.final_result()

# 5. Run it
async def run_research():
    deps = BrowserDeps(llm=ChatGoogle(model='models/gemma-4-31b-it'))
    result = await research_agent.run(
        "Find the neural computers research paper by Meta", 
        deps=deps
    )
    print(result.output.title) # Perfectly typed data!

    print("===================================================================")
    for msg in result.all_messages():
        print(f"\n--- {type(msg).__name__} ---")
        print(msg)

load_dotenv()

async def main():

    
   await run_research()



if __name__ == "__main__":
    # This runs the async loop
    asyncio.run(main())