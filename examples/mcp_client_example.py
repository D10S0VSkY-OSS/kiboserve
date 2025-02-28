"""Example: KiboMcpClient consuming the mcp_server_example.py server.

First start the server:
    OPENAI_API_KEY=sk-... uv run python examples/mcp_server_example.py

Then run this client:
    uv run python examples/mcp_client_example.py
"""

import asyncio

from kiboup import KiboMcpClient


async def main():
    async with KiboMcpClient("http://localhost:8000/sse", api_key="sk-mcp-abc") as client:
        tools = await client.list_tools()
        print(f"Available tools: {tools}")

        result = await client.call_tool("ask", {"question": "What is the capital of France?"})
        print(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
