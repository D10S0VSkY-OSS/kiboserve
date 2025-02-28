"""Built-in middleware for kiboup.

Also re-exports starlette.middleware.Middleware for convenience:
    from kiboup.shared.middleware import Middleware, ApiKeyMiddleware
"""

import json
import logging

from starlette.middleware import Middleware
from starlette.types import ASGIApp, Receive, Scope, Send

from kiboup.shared.logger import create_logger

API_KEY_HEADER = "x-api-key"


class ApiKeyMiddleware:
    """API Key authentication middleware (pure ASGI).

    Validates X-API-Key header. Keys map to client identifiers
    so you know who is calling your agent.

    Compatible with SSE and streaming responses (does not use
    BaseHTTPMiddleware which breaks streaming/SSE).

    Args:
        app: The ASGI application.
        api_keys: dict mapping api_key -> client_id,
                  or list of valid api_keys (client_id defaults to "anonymous")
        exclude_paths: paths that skip auth (default: ["/ping"])

    Example:
        from kiboup import KiboAgentApp

        app = KiboAgentApp(api_keys={
            "sk-frontend-abc": "web-app",
            "sk-agent-xyz": "recommender-agent",
        })

        @app.entrypoint
        async def invoke(payload, context):
            who = context.client_id  # "web-app" | "recommender-agent"
            return {"response": "hello", "called_by": who}
    """

    def __init__(self, app: ASGIApp, api_keys, exclude_paths=None):
        self.app = app
        if isinstance(api_keys, dict):
            self._keys = api_keys
        elif isinstance(api_keys, (list, tuple)):
            self._keys = {k: "anonymous" for k in api_keys}
        else:
            raise ValueError("api_keys must be a dict or list")
        self._exclude = set(exclude_paths or ["/ping"])
        self._logger = create_logger("kiboup.middleware")

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in self._exclude:
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        api_key = headers.get(API_KEY_HEADER.encode(), b"").decode()

        if not api_key:
            body = json.dumps({"error": "Missing API key", "header": API_KEY_HEADER}).encode()
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    [b"content-type", b"application/json"],
                    [b"content-length", str(len(body)).encode()],
                ],
            })
            await send({"type": "http.response.body", "body": body})
            return

        client_id = self._keys.get(api_key)
        if client_id is None:
            body = json.dumps({"error": "Invalid API key"}).encode()
            await send({
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    [b"content-type", b"application/json"],
                    [b"content-length", str(len(body)).encode()],
                ],
            })
            await send({"type": "http.response.body", "body": body})
            return

        scope.setdefault("state", {})["client_id"] = client_id
        method = scope.get("method", "")
        self._logger.log(
            logging.INFO,
            "Request from client",
            extra={"client_id": client_id, "method": method, "path": path},
        )
        await self.app(scope, receive, send)
