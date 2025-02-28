"""Example: Chainlit chat UI with KiboAgentApp streaming.

Chainlit provides a web chat interface that connects to the
kiboup streaming server via SSE.

1. Start the streaming server:
    OPENAI_API_KEY=sk-... uv run python examples/stream_server_example.py

2. Run this Chainlit app:
    uv run chainlit run examples/chainlit_example.py

3. Open http://localhost:8000 in your browser.

Install chainlit:
    uv add chainlit --optional examples
"""

import chainlit as cl

from kiboup import KiboAgentClient

SERVER_URL = "http://localhost:8080"
API_KEY = "sk-chat-abc"


@cl.on_chat_start
async def on_start():
    cl.user_session.set("history", [])


@cl.on_message
async def on_message(message: cl.Message):
    history = cl.user_session.get("history", [])
    history.append({"role": "user", "content": message.content})

    response = cl.Message(content="")
    await response.send()

    full_response = ""
    async with KiboAgentClient(SERVER_URL, api_key=API_KEY) as client:
        async for chunk in client.stream({
            "prompt": message.content,
            "messages": history,
        }):
            token = chunk.get("token")
            if token:
                full_response += token
                await response.stream_token(token)

    await response.update()
    history.append({"role": "assistant", "content": full_response})
    cl.user_session.set("history", history)
