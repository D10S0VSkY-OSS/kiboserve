"""KiboAgentMcp - MCP server wrapper using FastMCP.

Wraps FastMCP (https://github.com/PrefectHQ/fastmcp) to simplify MCP server setup.
Install with: pip install kiboup[mcp]

Example:
    from kiboup import KiboAgentMcp

    app = KiboAgentMcp(name="My MCP Server")

    @app.tool()
    def search(query: str) -> str:
        \"\"\"Search for something.\"\"\"
        return f"Results for {query}"

    @app.resource("config://app")
    def get_config() -> str:
        return "config data"

    app.run()

Example with OAuth:
    from fastmcp.server.auth import OAuthProvider
    from kiboup import KiboAgentMcp

    auth = OAuthProvider(...)
    app = KiboAgentMcp(name="Secured MCP", auth=auth)

Example with static bearer token:
    from fastmcp.server.auth import StaticTokenVerifier, RemoteAuthProvider
    from kiboup import KiboAgentMcp

    verifier = StaticTokenVerifier("my-secret-token")
    auth = RemoteAuthProvider(
        issuer_url="https://auth.example.com",
        token_verifier=verifier,
    )
    app = KiboAgentMcp(name="Token MCP", auth=auth)
"""

from typing import Any, Optional

from fastmcp import FastMCP

from kiboup.shared.logger import create_logger
from kiboup.shared.banner import print_banner

__all__ = ["KiboAgentMcp"]


class KiboAgentMcp:
    """MCP server wrapper around FastMCP.

    Delegates tool/resource/prompt registration to the underlying FastMCP instance.

    Security:
        Pass an ``auth`` provider to enable authentication. FastMCP supports:
        - ``OAuthProvider`` - full OAuth 2.0 Authorization Server with PKCE
        - ``RemoteAuthProvider`` - token verification against external AS
        - ``StaticTokenVerifier`` - simple static token validation
        - ``JWTVerifier`` - JWT verification with JWKS
        - Pre-built providers: Auth0, Azure, Google, GitHub, etc.

        Per-tool authorization via ``@app.tool(auth=require_scopes("scope"))``.
    """

    def __init__(
        self,
        name: str,
        auth: Optional[Any] = None,
        api_keys: Optional[dict] = None,
        **kwargs,
    ):
        init_kwargs: dict = dict(kwargs)
        if auth is not None:
            init_kwargs["auth"] = auth
        self._mcp = FastMCP(name, **init_kwargs)
        self._api_keys = api_keys
        self.logger = create_logger("kiboup.mcp")

    def tool(self, *args, **kwargs):
        """Register an MCP tool. Delegates to FastMCP.tool().

        Supports ``auth`` parameter for per-tool authorization:
            @app.tool(auth=require_scopes("read"))
            def my_tool(query: str) -> str: ...
        """
        return self._mcp.tool(*args, **kwargs)

    def resource(self, *args, **kwargs):
        """Register an MCP resource. Delegates to FastMCP.resource()."""
        return self._mcp.resource(*args, **kwargs)

    def prompt(self, *args, **kwargs):
        """Register an MCP prompt. Delegates to FastMCP.prompt()."""
        return self._mcp.prompt(*args, **kwargs)

    def run(
        self,
        host: str = "0.0.0.0",
        port: int = 8000,
        transport: str = "sse",
        reload: bool = False,
        **kwargs,
    ):
        """Start the MCP server.

        Args:
            host: Host to bind (default: 0.0.0.0).
            port: Port to listen on (default: 8000).
            transport: MCP transport type (default: sse).
            reload: Enable auto-reload on code changes (default: False).
        """
        print_banner(f"MCP Server ({transport})", host, port)

        extra_kwargs: dict = {}
        if self._api_keys:
            from kiboup.shared.middleware import ApiKeyMiddleware
            from starlette.middleware import Middleware
            extra_kwargs["middleware"] = [
                Middleware(ApiKeyMiddleware, api_keys=self._api_keys),
            ]
        if reload:
            extra_kwargs["reload"] = True

        self._mcp.run(
            transport=transport, host=host, port=port,
            show_banner=False, **extra_kwargs, **kwargs,
        )
