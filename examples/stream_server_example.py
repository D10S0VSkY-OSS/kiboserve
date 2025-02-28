"""Example: KiboAgentApp with LangGraph streaming (SSE).

Streams tokens from GPT-4o-mini via Server-Sent Events.

Run:
    OPENAI_API_KEY=sk-... uv run python examples/stream_server_example.py

Test with curl:
    curl -N -X POST http://127.0.0.1:8080/invocations \
        -H "Content-Type: application/json" \
        -H "X-API-Key: sk-chat-abc" \
        -d '{"prompt": "Tell me a short joke"}'
"""

from langchain_openai import ChatOpenAI
from langgraph.graph import START, MessagesState, StateGraph

from kiboup import KiboAgentApp

app = KiboAgentApp(
    api_keys={
        "sk-chat-abc": "chat-client",
    }
)

llm = ChatOpenAI(model="gpt-4o-mini", streaming=True)

graph_builder = StateGraph(MessagesState)


def chatbot(state: MessagesState):
    return {"messages": [llm.invoke(state["messages"])]}


graph_builder.add_node("chatbot", chatbot)
graph_builder.add_edge(START, "chatbot")
graph = graph_builder.compile()


@app.entrypoint
async def invoke(payload, context):
    prompt = payload.get("prompt", "")
    messages = payload.get("messages", [{"role": "user", "content": prompt}])

    async def token_stream():
        async for event in graph.astream_events(
            {"messages": messages},
            version="v2",
        ):
            kind = event.get("event")
            if kind == "on_chat_model_stream":
                content = event["data"]["chunk"].content
                if content:
                    yield {"token": content}
        yield {"done": True}

    return token_stream()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
