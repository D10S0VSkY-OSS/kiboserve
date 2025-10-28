# KiboUP

**Framework-agnostic library for deploying AI agents via HTTP, A2A, and MCP** — with built-in observability, prompt management, evaluation, and agent discovery through **KiboStudio**.

[![PyPI](https://img.shields.io/pypi/v/kiboup)](https://pypi.org/project/kiboup/)
[![Python](https://img.shields.io/badge/python-3.13%2B-blue)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## Table of Contents

- [Overview](#overview)
- [Installation](#installation)
- [Protocols: When to Use What](#protocols-when-to-use-what)
- [Quick Start](#quick-start)
  - [HTTP Agent (Server + Client)](#http-agent-server--client)
  - [Streaming (SSE)](#streaming-sse)
  - [MCP Server + Client](#mcp-server--client)
  - [A2A Server + Client](#a2a-server--client)
  - [Chainlit Chat UI](#chainlit-chat-ui)
- [KiboStudio](#kibostudio)
  - [Getting Started](#getting-started)
  - [Agent Discovery & Multi-Agent Collaboration](#agent-discovery--multi-agent-collaboration)
  - [Traces & Observability](#traces--observability)
  - [Graph Visualization](#graph-visualization)
  - [Chat Interface](#chat-interface)
  - [Feature Flags & Parameters](#feature-flags--parameters)
  - [Prompt Management](#prompt-management)
  - [Evaluation (LLM-as-Judge)](#evaluation-llm-as-judge)
  - [StudioClient SDK](#studioclient-sdk)
- [Examples](#examples)

---

## Overview

KiboUP lets you build and deploy AI agents with **one codebase** and expose them over three industry-standard protocols:

| Protocol | Best For | Server Class | Client Class |
|----------|----------|-------------|--------------|
| **HTTP** | Web apps, REST APIs, microservices | `KiboAgentApp` | `KiboAgentClient` |
| **MCP** | Tool-based agents, IDE integrations | `KiboAgentMcp` | `KiboMcpClient` |
| **A2A** | Agent-to-agent communication | `KiboAgentA2A` | `KiboA2AClient` |

All three protocols share:
- API key authentication middleware
- Structured JSON logging with `LLMUsage` metadata
- Health checks and task management
- Optional **KiboStudio** integration for observability

---

## Installation

```bash
# Core (HTTP only)
pip install kiboup

# With MCP support
pip install kiboup[mcp]

# With A2A support
pip install kiboup[a2a]

# With KiboStudio (observability, prompts, eval, discovery)
pip install kiboup[studio]

# Everything
pip install kiboup[all]
```

> Recommended: use `uv` for faster installs — `uv add kiboup[all]`

---

## Protocols: When to Use What

### HTTP (`KiboAgentApp` / `KiboAgentClient`)

Use HTTP when you need a **standard REST API** for your agent. This is the most versatile option — it works with any frontend, supports streaming via SSE, WebSocket connections, task tracking, and integrates seamlessly with KiboStudio tracing.

**Best for:** Web applications, mobile backends, microservice architectures, any client that speaks HTTP.

**Features:**
- `POST /invocations` — invoke the agent
- `GET /ping` — health check (Healthy / Busy)
- `GET /tasks` — list active tasks
- `DELETE /tasks/{id}` — cancel a task
- `WS /ws` — WebSocket endpoint
- SSE streaming support
- API key authentication
- Automatic KiboStudio trace reporting

### MCP (`KiboAgentMcp` / `KiboMcpClient`)

Use MCP when your agent exposes **tools** that other agents or IDEs can discover and call. The Model Context Protocol is the standard for tool-based interactions — think of it as a plugin system for LLMs.

**Best for:** IDE integrations (Cursor, VS Code), tool-based agents, agents that expose capabilities as callable functions.

**Features:**
- Tool registration via `@app.tool()` decorator
- Resource and prompt registration
- SSE and stdio transports
- Compatible with MCP Inspector and all MCP clients
- API key authentication

### A2A (`KiboAgentA2A` / `KiboA2AClient`)

Use A2A when agents need to **discover and communicate with each other** using Google's Agent-to-Agent protocol. Each agent publishes an Agent Card at `/.well-known/agent.json` describing its skills.

**Best for:** Multi-agent systems, agent marketplaces, cross-organization agent communication.

**Features:**
- Agent Card auto-generation at `/.well-known/agent.json`
- Skill-based routing
- Task lifecycle management (create, cancel)
- Bearer token and API key authentication
- Compatible with any A2A client

---

## Quick Start

### HTTP Agent (Server + Client)

**Server** (`agent_server_example.py`):

```python
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
    app.run(host="0.0.0.0", port=8080, reload=True)
```

**Client** (`agent_client_example.py`):

```python
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

if __name__ == "__main__":
    asyncio.run(main())
```

**Test with curl:**

```bash
curl -X POST http://127.0.0.1:8080/invocations \
    -H "Content-Type: application/json" \
    -H "X-API-Key: sk-frontend-abc" \
    -d '{"prompt": "What is the capital of France?"}'
```

---

### Streaming (SSE)

**Server** (`stream_server_example.py`):

```python
from langchain_openai import ChatOpenAI
from langgraph.graph import START, MessagesState, StateGraph
from kiboup import KiboAgentApp

app = KiboAgentApp(api_keys={"sk-chat-abc": "chat-client"})
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
        async for event in graph.astream_events({"messages": messages}, version="v2"):
            if event.get("event") == "on_chat_model_stream":
                content = event["data"]["chunk"].content
                if content:
                    yield {"token": content}
        yield {"done": True}

    return token_stream()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
```

**Client** (`stream_client_example.py`):

```python
import asyncio, sys
from kiboup import KiboAgentClient

async def chat_loop():
    async with KiboAgentClient("http://localhost:8080", api_key="sk-chat-abc") as client:
        health = await client.ping()
        print(f"Connected ({health['status']})\n")

        while True:
            user_input = input("You: ")
            if not user_input.strip():
                continue

            sys.stdout.write("AI: ")
            async for chunk in client.stream({"prompt": user_input}):
                token = chunk.get("token")
                if token:
                    sys.stdout.write(token)
                    sys.stdout.flush()
            print("\n")

if __name__ == "__main__":
    asyncio.run(chat_loop())
```

---

### MCP Server + Client

**Server** (`mcp_server_example.py`):

```python
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
    api_keys={"sk-mcp-abc": "web-app"},
)

@app.tool()
async def ask(question: str) -> str:
    """Ask a question to the LangGraph agent powered by GPT-4o-mini."""
    result = await graph.ainvoke(
        {"messages": [{"role": "user", "content": question}]}
    )
    return result["messages"][-1].content

@app.tool()
def summarize(text: str) -> str:
    """Summarize the given text using GPT-4o-mini."""
    result = graph.invoke(
        {"messages": [{"role": "user", "content": f"Summarize this text:\n\n{text}"}]}
    )
    return result["messages"][-1].content

if __name__ == "__main__":
    app.run(transport="sse")
```

**Client** (`mcp_client_example.py`):

```python
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
```

---

### A2A Server + Client

**Server** (`a2a_server_example.py`):

```python
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
    api_keys={"sk-a2a-xyz": "agent-client"},
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

@app.executor
class ChatAgent(AgentExecutor):
    async def execute(self, context, event_queue):
        from a2a.utils import new_agent_text_message
        user_input = context.get_user_input()
        result = await graph.ainvoke(
            {"messages": [{"role": "user", "content": user_input}]}
        )
        await event_queue.enqueue_event(
            new_agent_text_message(result["messages"][-1].content)
        )

    async def cancel(self, context, event_queue):
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.cancel()

if __name__ == "__main__":
    app.run()
```

**Client** (`a2a_client_example.py`):

```python
import asyncio
from kiboup import KiboA2AClient

async def main():
    async with KiboA2AClient("http://localhost:8000", api_key="sk-a2a-xyz") as client:
        print(f"Agent: {client.agent_card.name}")
        print(f"Skills: {[s.name for s in client.agent_card.skills]}")

        response = await client.send("What is the capital of France?")
        print(f"Response: {response}")

if __name__ == "__main__":
    asyncio.run(main())
```

---

### Chainlit Chat UI

```python
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
```

Start the streaming server first, then run:

```bash
uv run chainlit run examples/chainlit_example.py
```

---

## KiboStudio

KiboStudio is the built-in **developer console** for observability, prompt management, evaluation, and agent discovery. It runs as a standalone web server with a SQLite backend.

### Getting Started

```python
from kiboup.studio import KiboStudio

studio = KiboStudio(db_path="kibostudio.db", debug=True)

if __name__ == "__main__":
    studio.run(host="0.0.0.0", port=8000, reload=True)
```

Open `http://127.0.0.1:8000` in your browser.

### Agent Discovery & Multi-Agent Collaboration

KiboStudio acts as a **service registry** where agents register themselves, send heartbeats, and discover each other at runtime.

```python
from kiboup import KiboAgentApp
from kiboup.studio import StudioClient

app = KiboAgentApp()
studio = StudioClient(
    studio_url="http://127.0.0.1:8000",
    agent_id="researcher",
    agent_name="researcher",
    agent_endpoint="http://127.0.0.1:8081",
    capabilities=["research", "delegate"],
)
app.attach_studio(studio)
```

Once registered, agents can discover each other:

```python
agents = await studio.list_agents()
writer = next((a for a in agents if a.get("agent_id") == "writer"), None)
endpoint = writer["endpoint"]
```

The **Discovery** tab in the UI shows all registered agents with health status, uptime, memory usage, and capabilities.

### Traces & Observability

Every invocation through `KiboAgentApp` with an attached `StudioClient` automatically reports traces with:

- **Span hierarchy**: invocation > agent_run > llm_call / tool_call / retrieval
- **Input/Output data** for each span
- **LLM token usage**: model, provider, input/output/total tokens
- **Duration** and **status** (ok/error)
- **Attributes**: custom key-value pairs

The **Traces** tab groups traces by agent and shows timing, status, and token consumption at a glance.

### Graph Visualization

The **Graph** tab renders an ADK-style visual graph of each trace's span hierarchy:

- **Agent nodes**: green filled ellipses with robot emoji
- **Tool nodes**: rounded rectangles with wrench emoji
- **LLM nodes**: rounded rectangles with brain emoji
- **Retrieval nodes**: rounded rectangles with magnifier emoji
- Dark background (`#333537`), left-to-right layout, bezier curve edges with arrowheads
- Click any node to inspect its span details

### Chat Interface

The **Chat** tab provides a built-in chat interface to test any registered agent directly from the browser. Select an agent, type a message, and see the response rendered with full markdown support.

### Feature Flags & Parameters

Control agent behavior at runtime without redeploying:

**Feature Flags** — toggle capabilities on/off:

```python
delegate_enabled = await studio.is_flag_enabled("delegate_to_writer")
if not delegate_enabled:
    return {"response": research, "delegated": False}
```

**Parameters** — dynamic configuration values:

```python
writer_style = await studio.get_param("writer_style", default="markdown")
```

Both support **global** (apply to all agents) and **per-agent** scopes. The SDK caches values with a 30-second TTL for performance.

### Prompt Management

The **Prompts** tab lets you manage prompt templates with:

- Version history
- Variable extraction
- Active version selection
- Model configuration per version

Agents can fetch prompts at runtime:

```python
prompt = await studio.get_prompt("research_system_prompt")
content = prompt["content"]
```

### Evaluation (LLM-as-Judge)

The **Eval** tab runs automated quality evaluation on traces using an LLM-as-judge approach (GPT-4o-mini). It scores each trace on four metrics:

| Metric | Description |
|--------|-------------|
| **Answer Relevancy** | How relevant is the response to the input question |
| **Coherence** | Logical flow and consistency of the response |
| **Completeness** | Whether the response fully addresses the query |
| **Harmfulness** | Detection of harmful or inappropriate content |

Each metric is scored 0.0 to 1.0. Results are stored per trace and displayed with visual score bars.

### StudioClient SDK

The `StudioClient` provides a full async Python SDK for agents to interact with KiboStudio:

```python
from kiboup.studio import StudioClient

studio = StudioClient(
    studio_url="http://127.0.0.1:8000",
    agent_id="my-agent",
    agent_name="My Agent",
    agent_endpoint="http://127.0.0.1:8081",
    capabilities=["chat"],
    heartbeat_interval_s=15,
)

async with studio:
    # Discovery
    agents = await studio.list_agents()

    # Feature flags
    enabled = await studio.is_flag_enabled("my_flag")

    # Parameters
    value = await studio.get_param("my_param", default="fallback")

    # Prompts
    prompt = await studio.get_prompt("system_prompt")

    # Traces
    await studio.send_traces(trace_data)
```

The client can also be embedded directly into `KiboAgentClient` or `KiboMcpClient`:

```python
async with KiboAgentClient(
    base_url="http://localhost:8080",
    studio_url="http://localhost:8000",
    agent_id="my-agent",
) as client:
    result = await client.invoke({"prompt": "Hello"})
    flags = await client.studio.get_flags()
```

---

## Examples

| Example | File | Description |
|---------|------|-------------|
| HTTP Server | `examples/agent_server_example.py` | LangGraph + GPT-4o-mini with LLMUsage tracking |
| HTTP Client | `examples/agent_client_example.py` | Async client with health check and invocation |
| SSE Streaming Server | `examples/stream_server_example.py` | Token-by-token streaming via SSE |
| SSE Streaming Client | `examples/stream_client_example.py` | Interactive CLI chat with streaming |
| MCP Server | `examples/mcp_server_example.py` | Tool-based MCP server with `ask` and `summarize` |
| MCP Client | `examples/mcp_client_example.py` | MCP client listing tools and calling them |
| A2A Server | `examples/a2a_server_example.py` | A2A agent with skill registration |
| A2A Client | `examples/a2a_client_example.py` | A2A client reading agent card and sending messages |
| Chainlit UI | `examples/chainlit_example.py` | Web chat interface with streaming |
| KiboStudio | `examples/studio_example.py` | Launch the developer console |
| Multi-Agent | `examples/multi_agent_example.py` | Researcher + Writer agents with discovery, flags, and params |

Run any example:

```bash
OPENAI_API_KEY=sk-... uv run python examples/<example_file>.py
```

---

## License

[MIT](LICENSE)
