"""Example: Chat client with streaming (SSE).

Connects to stream_server_example.py and prints tokens as they arrive.

First start the server:
    OPENAI_API_KEY=sk-... uv run python examples/stream_server_example.py

Then run this client:
    uv run python examples/stream_client_example.py
"""

import asyncio
import sys

from kiboup import KiboAgentClient

API_KEY = "sk-chat-abc"
SERVER_URL = "http://localhost:8080"


async def chat_loop():
    async with KiboAgentClient(SERVER_URL, api_key=API_KEY) as client:
        health = await client.ping()
        sys.stdout.write(f"Connected to {SERVER_URL} ({health['status']})\n\n")

        while True:
            try:
                user_input = input("You: ")
            except (EOFError, KeyboardInterrupt):
                sys.stdout.write("\nBye!\n")
                break

            if not user_input.strip():
                continue

            sys.stdout.write("AI: ")
            sys.stdout.flush()

            async for chunk in client.stream({"prompt": user_input}):
                token = chunk.get("token")
                if token:
                    sys.stdout.write(token)
                    sys.stdout.flush()

            sys.stdout.write("\n\n")


if __name__ == "__main__":
    asyncio.run(chat_loop())
