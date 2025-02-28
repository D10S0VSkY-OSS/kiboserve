"""Example: KiboAgentApp with LangGraph + OpenAI GPT-4o-mini.

Demonstrates LLMUsage logging with token consumption data and
task cancellation (only the API key owner can cancel its own tasks).

Run:
    OPENAI_API_KEY=sk-... uv run python examples/agent_server_example.py

Test invocation:
    curl -X POST http://127.0.0.1:8080/invocations \
        -H "Content-Type: application/json" \
        -H "X-API-Key: sk-frontend-abc" \
        -d '{"prompt": "What is the capital of France?"}'

List tasks:
    curl http://127.0.0.1:8080/tasks -H "X-API-Key: sk-frontend-abc"

Cancel a task:
    curl -X DELETE http://127.0.0.1:8080/tasks/<task_id> \
        -H "X-API-Key: sk-frontend-abc"
"""

from langchain_openai import ChatOpenAI
from langgraph.graph import START, MessagesState, StateGraph

from kiboup import KiboAgentApp, LLMUsage

app = KiboAgentApp(
    api_keys={
        "sk-frontend-abc": "web-app",
        "sk-agent-xyz": "recommender-agent",
    }
)

llm = ChatOpenAI(model="gpt-4o-mini")

graph_builder = StateGraph(MessagesState)


def chatbot(state: MessagesState):
    return {"messages": [llm.invoke(state["messages"])]}


graph_builder.add_node("chatbot", chatbot)
graph_builder.add_edge(START, "chatbot")
graph = graph_builder.compile()


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


@app.entrypoint
async def invoke(payload, context):
    prompt = payload.get("prompt", "")
    result = await graph.ainvoke({"messages": [{"role": "user", "content": prompt}]})
    last_message = result["messages"][-1]

    usage = _extract_llm_usage(last_message)
    context._llm_usage = usage

    return {
        "response": last_message.content,
        "called_by": context.client_id,
        "llm_usage": usage.to_dict(),
    }


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080,reload=True)
