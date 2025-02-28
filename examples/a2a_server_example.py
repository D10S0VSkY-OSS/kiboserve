"""Example: KiboAgentA2A with LangGraph + OpenAI GPT-4o-mini.

Demonstrates LLMUsage logging with token consumption data.

Run:
    OPENAI_API_KEY=sk-... uv run python examples/a2a_server_example.py

Agent Card:
    http://localhost:8000/.well-known/agent.json
"""

import logging

from langchain_openai import ChatOpenAI
from langgraph.graph import START, MessagesState, StateGraph

from kiboup import LLMUsage
from kiboup.a2a.server import AgentExecutor, AgentSkill, KiboAgentA2A, TaskUpdater

llm = ChatOpenAI(model="gpt-4o-mini")

graph_builder = StateGraph(MessagesState)


def chatbot(state: MessagesState):
    return {"messages": [llm.invoke(state["messages"])]}


graph_builder.add_node("chatbot", chatbot)
graph_builder.add_edge(START, "chatbot")
graph = graph_builder.compile()

app = KiboAgentA2A(
    name="LangGraph Chat Agent",
    description="A simple chat agent using LangGraph with GPT-4o-mini",
    api_keys={
        "sk-a2a-xyz": "agent-client",
    },
    skills=[
        AgentSkill(
            id="chat",
            name="Chat",
            description="Answer questions using GPT-4o-mini via LangGraph",
            tags=["chat", "qa", "langgraph"],
            input_modes=["text/plain"],
            output_modes=["text/plain"],
        )
    ],
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


@app.executor
class ChatAgent(AgentExecutor):
    async def execute(self, context, event_queue):
        from a2a.utils import new_agent_text_message

        user_input = context.get_user_input()
        result = await graph.ainvoke(
            {"messages": [{"role": "user", "content": user_input}]}
        )
        last_message = result["messages"][-1]

        usage = _extract_llm_usage(last_message)
        app.logger.log(logging.INFO, "LLM response received", extra={"llm_usage": usage})

        await event_queue.enqueue_event(
            new_agent_text_message(last_message.content)
        )

    async def cancel(self, context, event_queue):
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.cancel()


if __name__ == "__main__":
    app.run()
