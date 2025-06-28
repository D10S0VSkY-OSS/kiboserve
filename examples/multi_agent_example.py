"""Example: Two LangGraph agents collaborating via KiboStudio discovery.

Agent A ("researcher") uses GPT-4o-mini to research a topic, then
discovers Agent B ("writer") through KiboStudio and delegates the
formatting task.

Agent B ("writer") uses GPT-4o-mini to polish and structure the
research into a well-formatted response.

Prerequisites:
    1. Start KiboStudio:
        uv run python examples/studio_example.py

    2. Start both agents (in separate terminals):
        OPENAI_API_KEY=sk-... uv run python examples/multi_agent_example.py --agent researcher
        OPENAI_API_KEY=sk-... uv run python examples/multi_agent_example.py --agent writer

    3. Open http://127.0.0.1:8000/chat in KiboStudio, select
       "researcher" and send a message.

    Or test via curl:
        curl -X POST http://127.0.0.1:8081/invocations \\
            -H "Content-Type: application/json" \\
            -d '{"prompt": "Explain how black holes form"}'
"""

import argparse
import asyncio

import httpx
from langchain_openai import ChatOpenAI
from langgraph.graph import START, MessagesState, StateGraph

from kiboup import KiboAgentApp
from kiboup.shared.entities import LLMUsage
from kiboup.studio import StudioClient

STUDIO_URL = "http://127.0.0.1:8000"


# ---------------------------------------------------------------------------
# Agent A: Researcher - uses LLM to research, then delegates to writer
# ---------------------------------------------------------------------------

def _build_researcher_graph():
    llm = ChatOpenAI(model="gpt-4o-mini")
    builder = StateGraph(MessagesState)

    def research(state: MessagesState):
        system = {
            "role": "system",
            "content": (
                "You are a research assistant. Given a topic, produce a concise "
                "but thorough research summary with key facts, context, and "
                "relevant data points. Output raw findings only, no formatting."
            ),
        }
        return {"messages": [llm.invoke([system] + state["messages"])]}

    builder.add_node("research", research)
    builder.add_edge(START, "research")
    return builder.compile()


def create_researcher():
    app = KiboAgentApp()
    graph = _build_researcher_graph()

    studio = StudioClient(
        studio_url=STUDIO_URL,
        agent_id="researcher",
        agent_name="researcher",
        agent_endpoint="http://127.0.0.1:8081",
        capabilities=["research", "delegate"],
    )
    app.attach_studio(studio)

    @app.entrypoint
    async def invoke(payload, context):
        prompt = payload.get("prompt", "")

        result = await graph.ainvoke(
            {"messages": [{"role": "user", "content": prompt}]}
        )
        last_msg = result["messages"][-1]
        research = last_msg.content

        token_usage = getattr(last_msg, "response_metadata", {}).get(
            "token_usage", {}
        )
        if token_usage:
            context._llm_usage = LLMUsage(
                model="gpt-4o-mini",
                provider="openai",
                input_tokens=token_usage.get("prompt_tokens"),
                output_tokens=token_usage.get("completion_tokens"),
                total_tokens=token_usage.get("total_tokens"),
            )

        delegate_enabled = await studio.is_flag_enabled("delegate_to_writer")
        print(f"Delegate to writer enabled: {delegate_enabled}")
        writer_style = await studio.get_param("writer_style", default="markdown")

        if not delegate_enabled:
            return {
                "response": research,
                "delegated": False,
                "note": "Delegation disabled via feature flag 'delegate_to_writer'.",
            }

        agents = await studio.list_agents()
        writer = next(
            (a for a in agents if a.get("agent_id") == "writer"),
            None,
        )

        if not writer:
            return {
                "response": research,
                "delegated": False,
                "note": "Writer agent not available, returning raw research.",
            }

        endpoint = writer["endpoint"].rstrip("/")
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{endpoint}/invocations",
                json={
                    "prompt": prompt,
                    "research": research,
                    "style": writer_style,
                },
            )
            writer_result = resp.json()

        return {
            "response": writer_result.get("response", research),
            "delegated": True,
            "writer_agent": "writer",
            "writer_style": writer_style,
        }

    return app, studio


# ---------------------------------------------------------------------------
# Agent B: Writer - uses LLM to polish research into structured response
# ---------------------------------------------------------------------------

def _build_writer_graph():
    llm = ChatOpenAI(model="gpt-4o-mini")
    builder = StateGraph(MessagesState)

    def write(state: MessagesState):
        system = {
            "role": "system",
            "content": (
                "You are a professional writer. You receive raw research "
                "findings and transform them into a well-structured, "
                "clear and engaging response using markdown formatting. "
                "Include headers, bullet points, and a summary section."
            ),
        }
        return {"messages": [llm.invoke([system] + state["messages"])]}

    builder.add_node("write", write)
    builder.add_edge(START, "write")
    return builder.compile()


def create_writer():
    app = KiboAgentApp()
    graph = _build_writer_graph()

    studio = StudioClient(
        studio_url=STUDIO_URL,
        agent_id="writer",
        agent_name="writer",
        agent_endpoint="http://127.0.0.1:8082",
        capabilities=["writing", "formatting"],
    )
    app.attach_studio(studio)

    @app.entrypoint
    async def invoke(payload, context):
        prompt = payload.get("prompt", "")
        research = payload.get("research", "")
        style = payload.get("style", "markdown")

        content = prompt
        if research:
            content = (
                f"Topic: {prompt}\n\n"
                f"Research findings:\n{research}\n\n"
                f"Please format this into a polished response using {style} style."
            )

        result = await graph.ainvoke(
            {"messages": [{"role": "user", "content": content}]}
        )
        last_msg = result["messages"][-1]
        response = last_msg.content

        token_usage = getattr(last_msg, "response_metadata", {}).get(
            "token_usage", {}
        )
        if token_usage:
            context._llm_usage = LLMUsage(
                model="gpt-4o-mini",
                provider="openai",
                input_tokens=token_usage.get("prompt_tokens"),
                output_tokens=token_usage.get("completion_tokens"),
                total_tokens=token_usage.get("total_tokens"),
            )

        return {"response": response, "agent": "writer", "style": style}

    return app, studio


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Multi-agent example")
    parser.add_argument(
        "--agent",
        choices=["researcher", "writer"],
        required=True,
        help="Which agent to start",
    )
    args = parser.parse_args()

    if args.agent == "researcher":
        app, studio = create_researcher()
        port = 8081
    else:
        app, studio = create_writer()
        port = 8082

    loop = asyncio.new_event_loop()
    loop.run_until_complete(studio.__aenter__())
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
