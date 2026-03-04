"""Example: mTLS between KiboAgentApp server and KiboAgentClient.

Demonstrates automatic certificate generation and mutual TLS
authentication with a real LLM (OpenAI GPT-4o-mini via LangGraph).

On first run, certificates are auto-generated in ~/.kiboserve/certs/.
Subsequent runs reuse the same certificates (renewed automatically
before expiry).

Run the server:
    OPENAI_API_KEY=sk-... uv run python examples/mtls_example.py server

Run the client (in another terminal):
    uv run python examples/mtls_example.py client

Custom certificate directory (env var):
    KIBO_CERTS_DIR=/tmp/my-certs uv run python examples/mtls_example.py server
    KIBO_CERTS_DIR=/tmp/my-certs uv run python examples/mtls_example.py client
"""

import asyncio
import sys

from langchain_openai import ChatOpenAI
from langgraph.graph import START, MessagesState, StateGraph

from kiboup import KiboAgentApp, KiboAgentClient, LLMUsage

MTLS_PORT = 8443


def _extract_llm_usage(ai_message) -> LLMUsage:
    """Extract LLM usage metadata from a LangChain AIMessage."""
    usage_meta = getattr(ai_message, "usage_metadata", None) or {}
    resp_meta = getattr(ai_message, "response_metadata", {})
    return LLMUsage(
        model=resp_meta.get("model_name"),
        provider="openai",
        input_tokens=usage_meta.get("input_tokens"),
        output_tokens=usage_meta.get("output_tokens"),
        total_tokens=usage_meta.get("total_tokens"),
    )


def run_server():
    """Start an HTTPS server with mTLS enabled and LangGraph + OpenAI."""
    app = KiboAgentApp()

    llm = ChatOpenAI(model="gpt-4o-mini")

    graph_builder = StateGraph(MessagesState)

    def chatbot(state: MessagesState):
        return {"messages": [llm.invoke(state["messages"])]}

    graph_builder.add_node("chatbot", chatbot)
    graph_builder.add_edge(START, "chatbot")
    graph = graph_builder.compile()

    @app.entrypoint
    async def invoke(payload, context):
        prompt = payload.get("prompt", "")
        result = await graph.ainvoke({"messages": [{"role": "user", "content": prompt}]})
        last_message = result["messages"][-1]

        usage = _extract_llm_usage(last_message)
        context._llm_usage = usage

        return {
            "response": last_message.content,
            "llm_usage": usage.to_dict(),
        }

    app.run(host="0.0.0.0", port=MTLS_PORT, mtls=True)


async def run_client():
    """Connect to the mTLS server and invoke the agent."""
    async with KiboAgentClient(
        base_url=f"https://localhost:{MTLS_PORT}",
        mtls=True,
    ) as client:
        health = await client.ping()
        sys.stdout.write(f"Server health: {health}\n")

        result = await client.invoke({"prompt": "What is the capital of France?"})
        sys.stdout.write(f"Response: {result['response']}\n")
        if "llm_usage" in result:
            sys.stdout.write(f"LLM usage: {result['llm_usage']}\n")


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "server"

    if command == "server":
        run_server()
    elif command == "client":
        asyncio.run(run_client())
    else:
        sys.stderr.write(f"Usage: {sys.argv[0]} [server|client]\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
