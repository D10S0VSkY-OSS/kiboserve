"""Tracing middleware for KiboStudio.

Pure ASGI middleware that instruments KiboAgentApp invocations,
creating spans and sending them to the Studio collector.
"""

import json
import time
import uuid

from starlette.types import ASGIApp, Receive, Scope, Send

from kiboup.studio.entities import SpanKind, _utc_now
from kiboup.studio.tracer import StudioTracer


class StudioTracingMiddleware:
    """ASGI middleware that auto-traces every invocation.

    Compatible with SSE/streaming (pure ASGI, no BaseHTTPMiddleware).

    Args:
        app: The ASGI application.
        tracer: StudioTracer instance (with store attached).
        agent_id: Identifier for this agent in traces.
        trace_paths: Paths to trace (default: ["/invocations"]).

    Example:
        from kiboup.studio.tracer import StudioTracer
        from kiboup.studio.db import SQLiteStore

        store = SQLiteStore("studio.db")
        tracer = StudioTracer(store=store, agent_id="my-agent")

        app = KiboAgentApp(
            middleware=[
                Middleware(StudioTracingMiddleware, tracer=tracer, agent_id="my-agent")
            ]
        )
    """

    def __init__(
        self,
        app: ASGIApp,
        tracer: StudioTracer,
        agent_id: str = "unknown",
        trace_paths: list | None = None,
    ):
        self.app = app
        self._tracer = tracer
        self._agent_id = agent_id
        self._trace_paths = set(trace_paths or ["/invocations"])

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path not in self._trace_paths:
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        request_id = headers.get(b"x-request-id", b"").decode() or str(uuid.uuid4())
        session_id = headers.get(b"x-session-id", b"").decode() or None

        body_chunks = []
        response_chunks = []
        response_status = 200

        async def tracing_receive():
            message = await receive()
            if message.get("type") == "http.request":
                body = message.get("body", b"")
                if body:
                    body_chunks.append(body)
            return message

        async def tracing_send(message):
            nonlocal response_status
            if message.get("type") == "http.response.start":
                response_status = message.get("status", 200)
            elif message.get("type") == "http.response.body":
                body = message.get("body", b"")
                if body:
                    response_chunks.append(body)
            await send(message)

        with self._tracer.trace(
            name=f"{scope.get('method', 'POST')} {path}",
            session_id=session_id,
            request_id=request_id,
        ) as ctx:
            try:
                input_data = None
                try:
                    raw_body = b"".join(body_chunks)
                    if raw_body:
                        input_data = json.loads(raw_body)
                except Exception:
                    pass
                if input_data:
                    ctx.set_input(input_data)

                await self.app(scope, tracing_receive, tracing_send)

                output_data = None
                try:
                    raw_response = b"".join(response_chunks)
                    if raw_response:
                        output_data = json.loads(raw_response)
                except Exception:
                    pass
                if output_data:
                    ctx.set_output(output_data)

                if response_status >= 400:
                    ctx.root_span.status = "error"
                    ctx.root_span.set_attribute("http.status_code", response_status) if hasattr(ctx.root_span, "set_attribute") else None
                    ctx._root_span.attributes["http.status_code"] = response_status

            except Exception as exc:
                ctx._root_span.status = "error"
                ctx._root_span.error = str(exc)
                raise
