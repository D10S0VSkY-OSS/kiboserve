"""KiboAgentA2A - Agent-to-Agent protocol server wrapper.

Wraps the official a2a-sdk to simplify A2A server setup.
Install with: pip install kiboup[a2a]

Example:
    from kiboup.a2a.server import KiboAgentA2A, AgentExecutor, AgentSkill

    app = KiboAgentA2A(
        name="My Agent",
        description="A simple A2A agent",
        skills=[
            AgentSkill(
                id="greet",
                name="Greet",
                description="Greets the user",
                tags=["greeting"],
                input_modes=["text/plain"],
                output_modes=["text/plain"],
            )
        ],
    )

    @app.executor
    class MyAgent(AgentExecutor):
        async def execute(self, context, event_queue):
            from a2a.server.utils import new_agent_text_message
            msg = context.get_user_input()
            await event_queue.enqueue_event(new_agent_text_message(f"Hello: {msg}"))

        async def cancel(self, context, event_queue):
            raise NotImplementedError

    app.run()
"""

from typing import Any, Dict, List, Optional

from a2a.server.agent_execution import AgentExecutor
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentSkill, SecurityScheme

from kiboup.shared.logger import create_logger
from kiboup.shared.banner import print_banner, resolve_import_string

__all__ = [
    "KiboAgentA2A",
    "AgentExecutor",
    "AgentCapabilities",
    "AgentCard",
    "AgentSkill",
    "TaskUpdater",
]


class KiboAgentA2A:
    """A2A protocol server wrapper.

    Simplifies the boilerplate of creating AgentCard, TaskStore,
    RequestHandler, and A2AStarletteApplication.

    Security:
        The ``security`` and ``security_schemes`` parameters are declared
        on the ``AgentCard`` so clients can discover which auth mechanisms
        are required. Server-side enforcement must be done via Starlette
        middleware (e.g. ``ApiKeyMiddleware``) passed in ``middleware``.

        Supported schemes (a2a-sdk types):
        - ``HTTPAuthSecurityScheme`` (Bearer tokens)
        - ``APIKeySecurityScheme`` (API keys in headers)
        - ``OAuth2SecurityScheme`` (OAuth 2.0 flows)
        - ``OpenIdConnectSecurityScheme`` (OIDC)
        - ``MutualTLSSecurityScheme`` (mTLS - declarative only)
    """

    def __init__(
        self,
        name: str,
        description: str,
        version: str = "1.0.0",
        skills: Optional[List[AgentSkill]] = None,
        url: Optional[str] = None,
        capabilities: Optional[AgentCapabilities] = None,
        default_input_modes: Optional[List[str]] = None,
        default_output_modes: Optional[List[str]] = None,
        security: Optional[List[Dict[str, List[str]]]] = None,
        security_schemes: Optional[Dict[str, SecurityScheme]] = None,
        middleware: Optional[List[Any]] = None,
        api_keys: Optional[Dict[str, str]] = None,
    ):
        self._name = name
        self._description = description
        self._version = version
        self._skills = skills or []
        self._url = url
        self._capabilities = capabilities or AgentCapabilities()
        self._default_input_modes = default_input_modes or ["text/plain"]
        self._default_output_modes = default_output_modes or ["text/plain"]
        self._security = security
        self._security_schemes = security_schemes
        self._middleware = list(middleware or [])
        if api_keys:
            from starlette.middleware import Middleware
            from kiboup.shared.middleware import ApiKeyMiddleware
            self._middleware.insert(0, Middleware(ApiKeyMiddleware, api_keys=api_keys))
        self._executor_cls: Optional[type] = None
        self.logger = create_logger("kiboup.a2a")

    def executor(self, cls):
        """Register an AgentExecutor subclass.

        Usage:
            @app.executor
            class MyAgent(AgentExecutor):
                async def execute(self, context, event_queue): ...
                async def cancel(self, context, event_queue): ...
        """
        if not (isinstance(cls, type) and issubclass(cls, AgentExecutor)):
            raise ValueError("@executor requires a subclass of AgentExecutor")
        self._executor_cls = cls
        return cls

    def run(self, host: str = "0.0.0.0", port: int = 8000, reload: bool = False, **kwargs):
        """Start the A2A server with uvicorn.

        Args:
            host: Host to bind (default: 0.0.0.0).
            port: Port to listen on (default: 8000).
            reload: Enable auto-reload on code changes (default: False).
        """
        import uvicorn

        if self._executor_cls is None:
            raise RuntimeError(
                "No executor registered. Use @app.executor on an AgentExecutor subclass."
            )

        url = self._url or f"http://localhost:{port}"

        card_kwargs: Dict[str, Any] = {
            "name": self._name,
            "description": self._description,
            "url": url,
            "version": self._version,
            "skills": self._skills,
            "capabilities": self._capabilities,
            "default_input_modes": self._default_input_modes,
            "default_output_modes": self._default_output_modes,
        }
        if self._security is not None:
            card_kwargs["security"] = self._security
        if self._security_schemes is not None:
            card_kwargs["security_schemes"] = self._security_schemes

        agent_card = AgentCard(**card_kwargs)

        task_store = InMemoryTaskStore()
        request_handler = DefaultRequestHandler(
            agent_executor=self._executor_cls(),
            task_store=task_store,
        )

        starlette_app = A2AStarletteApplication(
            agent_card=agent_card,
            http_handler=request_handler,
        )

        build_kwargs: Dict[str, Any] = {}
        if self._middleware:
            build_kwargs["middleware"] = self._middleware

        app = starlette_app.build(**build_kwargs)

        print_banner("A2A Agent", host, port)

        workers = kwargs.pop("workers", 1)
        needs_import_string = reload or workers > 1

        app_target = app
        if needs_import_string:
            import_string = resolve_import_string(self)
            if import_string is None:
                raise RuntimeError(
                    "Cannot resolve import string for the app. "
                    "When using workers > 1 or reload=True, the app variable "
                    "must be defined at module level. "
                    "Example: uvicorn examples.a2a_server_example:app --workers 2"
                )
            self._built_app = app
            module_name, var_name = import_string.split(":")
            app_target = f"{module_name}:{var_name}._built_app"

        run_kwargs: Dict[str, Any] = {"host": host, "port": port, "ws": "wsproto"}
        if reload:
            run_kwargs["reload"] = True
        if workers > 1:
            run_kwargs["workers"] = workers
        run_kwargs.update(kwargs)
        uvicorn.run(app_target, **run_kwargs)
