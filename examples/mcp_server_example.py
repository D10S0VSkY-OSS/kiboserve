"""Example: KiboAgentMcp with LangGraph + OpenAI GPT-4o-mini.

Demonstrates LLMUsage logging with token consumption data.

Run:
    OPENAI_API_KEY=sk-... uv run python examples/mcp_server_example.py

Test with MCP Inspector or any MCP client.
"""

import logging

from langchain_openai import ChatOpenAI
from langgraph.graph import START, MessagesState, StateGraph

from kiboup import KiboAgentMcp, LLMUsage

llm = ChatOpenAI(model="gpt-4o-mini")

graph_builder = StateGraph(MessagesState)


def chatbot(state: MessagesState):
    return {"messages": [llm.invoke(state["messages"])]}


graph_builder.add_node("chatbot", chatbot)
graph_builder.add_edge(START, "chatbot")
graph = graph_builder.compile()

app = KiboAgentMcp(
    name="LangGraph MCP Server",
    api_keys={
        "sk-mcp-abc": "web-app",
        "sk-mcp-xyz": "agent-client",
    },
)


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


@app.tool()
async def ask(question: str) -> str:
    """Ask a question to the LangGraph agent powered by GPT-4o-mini."""
    result = await graph.ainvoke(
        {"messages": [{"role": "user", "content": question}]}
    )
    last_message = result["messages"][-1]
    usage = _extract_llm_usage(last_message)
    app.logger.log(logging.INFO, "LLM response received", extra={"llm_usage": usage})
    return last_message.content


@app.tool()
def summarize(text: str) -> str:
    """Summarize the given text using GPT-4o-mini."""
    result = graph.invoke(
        {"messages": [{"role": "user", "content": f"Summarize this text:\n\n{text}"}]}
    )
    last_message = result["messages"][-1]
    usage = _extract_llm_usage(last_message)
    app.logger.log(logging.INFO, "LLM response received", extra={"llm_usage": usage})
    return last_message.content


if __name__ == "__main__":
    app.run(transport="sse")
