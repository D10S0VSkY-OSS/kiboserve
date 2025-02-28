"""Example: KiboAgentClient consuming the agent_server_example.py server.

First start the server:
    OPENAI_API_KEY=sk-... uv run python examples/agent_server_example.py

Then run this client:
    uv run python examples/agent_client_example.py
"""

import asyncio

from kiboup import KiboAgentClient


async def main():
    async with KiboAgentClient(
        base_url="http://127.0.0.1:8080",
        api_key="sk-frontend-abc",
    ) as client:
        health = await client.ping()
        print(f"Server health: {health}")

        result = await client.invoke({"prompt": "What is the capital of France?"})
        print(f"Response: {result['response']}")
        print(f"Called by: {result.get('called_by')}")


if __name__ == "__main__":
    asyncio.run(main())
