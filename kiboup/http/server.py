"""KiboAgentApp - HTTP entrypoint server for AI agents."""

import asyncio
import contextvars
import inspect
import json
import logging
import threading
import time
import uuid
from collections.abc import Sequence
from typing import Any, Callable, Dict, Optional

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route, WebSocketRoute
from starlette.types import Lifespan
from starlette.websockets import WebSocket, WebSocketDisconnect

from kiboup.shared.entities import HealthStatus, LLMUsage, RequestContext
from kiboup.shared.logger import create_logger
from kiboup.shared.banner import detect_host, print_banner, resolve_import_string

REQUEST_ID_HEADER = "x-request-id"
SESSION_ID_HEADER = "x-session-id"


class KiboAgentApp(Starlette):
    """HTTP server for AI agents with decorator-based routing.

    Example:
        app = KiboAgentApp(
            api_keys={"sk-my-key": "web-app"},
        )

        @app.entrypoint
        async def invoke(payload, context):
            return {"response": "Hello"}

        app.run()
    """

    def __init__(
        self,
        debug: bool = False,
        lifespan: Optional[Lifespan] = None,
        middleware: Sequence[Middleware] | None = None,
        api_keys: Optional[Dict[str, str]] = None,
    ):
        self.handlers: Dict[str, Callable] = {}
        self._ping_handler: Optional[Callable] = None
        self._websocket_handler: Optional[Callable] = None
        self._active_tasks: Dict[str, Dict[str, Any]] = {}
        self._task_lock = threading.Lock()
        self._forced_health_status: Optional[HealthStatus] = None

        all_middleware = list(middleware or [])
        if api_keys:
            from kiboup.shared.middleware import ApiKeyMiddleware
            all_middleware.insert(0, Middleware(ApiKeyMiddleware, api_keys=api_keys))

        routes = [
            Route("/invocations", self._handle_invocation, methods=["POST"]),
            Route("/ping", self._handle_ping, methods=["GET"]),
            Route("/tasks", self._handle_list_tasks, methods=["GET"]),
            Route("/tasks/{task_id}", self._handle_cancel_task, methods=["DELETE"]),
            WebSocketRoute("/ws", self._handle_websocket),
        ]
        super().__init__(routes=routes, lifespan=lifespan, middleware=all_middleware or None)
        self.debug = debug
        self.logger = create_logger("kiboup.agent", debug)

    # -- Decorators --

    def entrypoint(self, func: Callable) -> Callable:
        """Register a function as the main invocation handler (POST /invocations)."""
        self.handlers["main"] = func
        func.run = lambda port=8080, host=None: self.run(port, host)
        return func

    def ping(self, func: Callable) -> Callable:
        """Register a custom health check handler for GET /ping."""
        self._ping_handler = func
        return func

    def websocket(self, func: Callable) -> Callable:
        """Register a WebSocket handler at /ws."""
        self._websocket_handler = func
        return func

    def async_task(self, func: Callable) -> Callable:
        """Track async tasks for health status (BUSY while running).

        The wrapped function receives a ``task_id`` keyword argument that
        can be used to check cancellation status via
        ``app.is_task_cancelled(task_id)``.
        """
        if not asyncio.iscoroutinefunction(func):
            raise ValueError("@async_task requires an async function")

        async def wrapper(*args, context: RequestContext = None, **kwargs):
            client_id = context.client_id if context else None
            task_id = self.add_task(func.__name__, client_id=client_id)
            asyncio_task = asyncio.current_task()
            with self._task_lock:
                if task_id in self._active_tasks:
                    self._active_tasks[task_id]["asyncio_task"] = asyncio_task
            try:
                result = await func(*args, context=context, task_id=task_id, **kwargs)
                return result
            except asyncio.CancelledError:
                self._log(logging.INFO, "Task cancelled: %s" % task_id, context)
                raise
            finally:
                self.complete_task(task_id)

        wrapper.__name__ = func.__name__
        return wrapper

    # -- Health status --

    def get_health_status(self) -> HealthStatus:
        """Get current health: forced > custom handler > automatic."""
        status = None

        if self._forced_health_status is not None:
            status = self._forced_health_status
        elif self._ping_handler:
            try:
                result = self._ping_handler()
                status = HealthStatus(result) if isinstance(result, str) else result
            except Exception as exc:
                self.logger.warning("Custom ping handler failed: %s", exc)

        if status is None:
            status = HealthStatus.BUSY if self._active_tasks else HealthStatus.HEALTHY

        return status

    def force_health_status(self, status: HealthStatus):
        """Force health status to a fixed value."""
        self._forced_health_status = status

    def clear_forced_health_status(self):
        """Clear forced status, resume automatic detection."""
        self._forced_health_status = None

    # -- Task tracking --

    def add_task(self, name: str, client_id: Optional[str] = None) -> str:
        """Register a running task for health tracking.

        Args:
            name: Descriptive name for the task.
            client_id: Owner identifier (from API key). Only this
                client will be allowed to cancel the task.

        Returns:
            Unique task ID string.
        """
        with self._task_lock:
            task_id = str(uuid.uuid4())
            self._active_tasks[task_id] = {
                "name": name,
                "start_time": time.time(),
                "client_id": client_id,
                "asyncio_task": None,
            }
            return task_id

    def complete_task(self, task_id: str) -> bool:
        """Mark a task as complete. Returns True if found."""
        with self._task_lock:
            return self._active_tasks.pop(task_id, None) is not None

    def cancel_task(self, task_id: str, client_id: Optional[str] = None) -> bool:
        """Cancel a running task.

        Only the client that created the task (same ``client_id``) is
        allowed to cancel it. Returns True if the task was found and
        cancelled.

        Args:
            task_id: The task identifier returned by ``add_task``.
            client_id: The caller's client_id for ownership verification.

        Raises:
            PermissionError: If ``client_id`` does not match the task owner.
            KeyError: If the task does not exist.
        """
        with self._task_lock:
            task_info = self._active_tasks.get(task_id)
            if task_info is None:
                raise KeyError(task_id)

            owner = task_info.get("client_id")
            if owner is not None and owner != client_id:
                raise PermissionError(task_id)

            asyncio_task = task_info.get("asyncio_task")
            self._active_tasks.pop(task_id, None)

        if asyncio_task is not None and not asyncio_task.done():
            asyncio_task.cancel()

        return True

    def is_task_cancelled(self, task_id: str) -> bool:
        """Check if a task has been cancelled (no longer tracked)."""
        with self._task_lock:
            return task_id not in self._active_tasks

    # -- Server --

    def run(self, port: int = 8080, host: Optional[str] = None, reload: bool = False, **kwargs):
        """Start the server with uvicorn.

        Args:
            port: Port to listen on (default: 8080).
            host: Host to bind. Auto-detected if None.
            reload: Enable auto-reload on code changes (default: False).
        """
        import uvicorn

        if host is None:
            host = detect_host()

        print_banner("HTTP Agent", host, port)

        workers = kwargs.pop("workers", 1)
        needs_import_string = reload or workers > 1

        app_target = self
        if needs_import_string:
            import_string = resolve_import_string(self)
            if import_string is None:
                raise RuntimeError(
                    "Cannot resolve import string for the app. "
                    "When using workers > 1 or reload=True, the app variable "
                    "must be defined at module level. "
                    "Example: uvicorn examples.agent_server_example:app --workers 2"
                )
            app_target = import_string

        uvicorn_config = {
            "host": host,
            "port": port,
            "ws": "wsproto",
            "access_log": self.debug,
            "log_level": "info" if self.debug else "warning",
        }
        if reload:
            uvicorn_config["reload"] = True
        if workers > 1:
            uvicorn_config["workers"] = workers
        uvicorn_config.update(kwargs)
        uvicorn.run(app_target, **uvicorn_config)

    # -- Internal --

    def _log(
        self,
        level: int,
        message: str,
        context: RequestContext = None,
        llm_usage: LLMUsage | None = None,
        **kwargs,
    ):
        """Log with request context fields and optional LLM usage data."""
        extra = {}
        if context:
            extra["request_id"] = context.request_id
            if context.session_id:
                extra["session_id"] = context.session_id
            if context.client_id:
                extra["client_id"] = context.client_id
        if llm_usage is not None:
            extra["llm_usage"] = llm_usage
            context._llm_usage = llm_usage
        self.logger.log(level, message, extra=extra, **kwargs)

    def _build_context(self, request) -> RequestContext:
        headers = dict(request.headers)
        client_id = getattr(request.state, "client_id", None) if hasattr(request, "state") else None
        return RequestContext(
            request_id=headers.get(REQUEST_ID_HEADER, str(uuid.uuid4())),
            session_id=headers.get(SESSION_ID_HEADER),
            client_id=client_id,
            headers=headers,
            request=request,
        )

    def _handler_takes_context(self, handler: Callable) -> bool:
        try:
            params = list(inspect.signature(handler).parameters.keys())
            return len(params) >= 2 and params[1] == "context"
        except Exception:
            return False

    async def _invoke_handler(self, handler, payload, context):
        takes_ctx = self._handler_takes_context(handler)
        args = (payload, context) if takes_ctx else (payload,)

        if asyncio.iscoroutinefunction(handler):
            return await handler(*args)

        loop = asyncio.get_event_loop()
        ctx = contextvars.copy_context()
        return await loop.run_in_executor(None, ctx.run, handler, *args)

    async def _handle_invocation(self, request):
        context = self._build_context(request)
        start = time.time()

        try:
            payload = await request.json()

            handler = self.handlers.get("main")
            if not handler:
                return JSONResponse({"error": "No entrypoint defined"}, status_code=500)

            result = await self._invoke_handler(handler, payload, context)
            duration = time.time() - start

            if inspect.isgenerator(result):
                return StreamingResponse(
                    self._wrap_sync_stream(result), media_type="text/event-stream"
                )
            if inspect.isasyncgen(result):
                return StreamingResponse(
                    self._wrap_async_stream(result), media_type="text/event-stream"
                )

            llm_usage = getattr(context, "_llm_usage", None)
            self._log(
                logging.INFO,
                "Invocation completed (%.3fs)" % duration,
                context,
                llm_usage=llm_usage,
            )
            return Response(self._serialize(result), media_type="application/json")

        except json.JSONDecodeError as exc:
            return JSONResponse(
                {"error": "Invalid JSON", "details": str(exc)}, status_code=400
            )
        except Exception as exc:
            self._log(logging.ERROR, "Invocation failed (%.3fs)" % (time.time() - start), context, exc_info=True)
            return JSONResponse({"error": str(exc)}, status_code=500)

    def _handle_ping(self, request):
        try:
            status = self.get_health_status()
            return JSONResponse({"status": status.value})
        except Exception:
            return JSONResponse({"status": HealthStatus.HEALTHY.value})

    def _handle_list_tasks(self, request):
        """GET /tasks - List active tasks (filtered by caller's client_id)."""
        context = self._build_context(request)
        with self._task_lock:
            tasks = []
            for tid, info in self._active_tasks.items():
                if context.client_id is None or info.get("client_id") == context.client_id:
                    tasks.append({
                        "task_id": tid,
                        "name": info["name"],
                        "running_seconds": round(time.time() - info["start_time"], 1),
                    })
        return JSONResponse({"tasks": tasks})

    async def _handle_cancel_task(self, request):
        """DELETE /tasks/{task_id} - Cancel a task (owner only)."""
        context = self._build_context(request)
        task_id = request.path_params["task_id"]

        try:
            self.cancel_task(task_id, client_id=context.client_id)
        except KeyError:
            return JSONResponse(
                {"error": "Task not found", "task_id": task_id},
                status_code=404,
            )
        except PermissionError:
            return JSONResponse(
                {"error": "Only the task owner can cancel this task"},
                status_code=403,
            )

        self._log(logging.INFO, "Task cancelled via API: %s" % task_id, context)
        return JSONResponse({"status": "cancelled", "task_id": task_id})

    async def _handle_websocket(self, websocket: WebSocket):
        context = self._build_context(websocket)
        try:
            if not self._websocket_handler:
                await websocket.close(code=1011)
                return
            await self._websocket_handler(websocket, context)
        except WebSocketDisconnect:
            pass
        except Exception:
            self._log(logging.ERROR, "WebSocket handler failed", context, exc_info=True)
            try:
                await websocket.close(code=1011)
            except Exception:
                pass

    def _serialize(self, obj) -> str:
        try:
            return json.dumps(obj, ensure_ascii=False)
        except (TypeError, ValueError):
            try:
                return json.dumps(str(obj), ensure_ascii=False)
            except Exception:
                return json.dumps(
                    {"error": "Serialization failed", "type": type(obj).__name__}
                )

    def _to_sse(self, obj) -> bytes:
        data = self._serialize(obj)
        return f"data: {data}\n\n".encode("utf-8")

    async def _wrap_async_stream(self, generator):
        try:
            async for value in generator:
                yield self._to_sse(value)
        except Exception as exc:
            yield self._to_sse({"error": str(exc), "error_type": type(exc).__name__})

    def _wrap_sync_stream(self, generator):
        try:
            for value in generator:
                yield self._to_sse(value)
        except Exception as exc:
            yield self._to_sse({"error": str(exc), "error_type": type(exc).__name__})
