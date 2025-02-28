"""Example: KiboA2AClient consuming the a2a_server_example.py server.

First start the server:
    OPENAI_API_KEY=sk-... uv run python examples/a2a_server_example.py

Then run this client:
    uv run python examples/a2a_client_example.py
"""

import asyncio

from kiboup import KiboA2AClient


async def main():
    async with KiboA2AClient("http://localhost:8000", api_key="sk-a2a-xyz") as client:
        print(f"Agent: {client.agent_card.name}")
        print(f"Skills: {[s.name for s in client.agent_card.skills]}")

        response = await client.send("What is the capital of France?")
        print(f"Response: {response}")


if __name__ == "__main__":
    asyncio.run(main())
