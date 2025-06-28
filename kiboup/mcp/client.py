"""KiboMcpClient - MCP protocol client wrapper."""

from typing import Any, Dict, List, Optional, Union

import httpx
from fastmcp.client import Client as FastMCPClient

from kiboup.shared.logger import create_logger

__all__ = ["KiboMcpClient"]


class _ApiKeyAuth(httpx.Auth):
    """httpx.Auth that injects an X-API-Key header."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    def auth_flow(self, request: httpx.Request):
        request.headers["X-API-Key"] = self._api_key
        yield request


class KiboMcpClient:
    """Client for MCP servers with optional KiboStudio integration.

    Security:
        Pass ``auth`` to authenticate with the MCP server:
        - A string is treated as a Bearer token
        - ``"oauth"`` triggers the FastMCP OAuth PKCE flow (browser-based)
        - An ``httpx.Auth`` instance for custom auth

        Pass ``api_key`` for X-API-Key header auth (used by ``ApiKeyMiddleware``).

    Studio integration:
        Pass ``studio_url`` and ``agent_id`` to automatically create a
        ``StudioClient`` and manage its lifecycle. Access it via the
        ``studio`` property.

        Alternatively, pass a pre-built ``StudioClient`` instance via
        the ``studio`` parameter for full control over its configuration.

    Example:
        async with KiboMcpClient("http://localhost:8000/sse", auth="my-bearer-token") as client:
            tools = await client.list_tools()

        async with KiboMcpClient(
            url="http://localhost:8080/sse",
            studio_url="http://localhost:8000",
            agent_id="my-agent",
        ) as client:
            tools = await client.list_tools()
            enabled = await client.studio.is_flag_enabled("my_flag")
    """

    def __init__(
        self,
        url: str = "http://localhost:8000/sse",
        auth: Union[str, httpx.Auth, None] = None,
        api_key: Optional[str] = None,
        *,
        studio=None,
        studio_url: Optional[str] = None,
        agent_id: Optional[str] = None,
        **studio_kwargs,
    ):
        self._url = url
        if api_key is not None and auth is None:
            self._auth: Union[str, httpx.Auth, None] = _ApiKeyAuth(api_key)
        else:
            self._auth = auth
        self._client: Optional[FastMCPClient] = None
        self.logger = create_logger("kiboup.mcp_client")

        self._studio = studio
        self._studio_owned = False
        if self._studio is None and studio_url:
            from kiboup.studio import StudioClient

            self._studio = StudioClient(
                studio_url=studio_url,
                agent_id=agent_id or "",
                **studio_kwargs,
            )
            self._studio_owned = True

    @property
    def studio(self):
        """Access the attached StudioClient (None if not configured)."""
        return self._studio

    async def __aenter__(self):
        kwargs: Dict[str, Any] = {}
        if self._auth is not None:
            kwargs["auth"] = self._auth
        self._client = FastMCPClient(self._url, **kwargs)
        await self._client.__aenter__()
        if self._studio is not None:
            await self._studio.__aenter__()
        return self

    async def __aexit__(self, *args):
        if self._studio is not None:
            try:
                await self._studio.__aexit__(*args)
            except Exception:
                pass
        if self._client:
            await self._client.__aexit__(*args)
            self._client = None

    async def list_tools(self) -> List[Dict[str, Any]]:
        """List available tools on the MCP server."""
        tools = await self._client.list_tools()
        return [{"name": t.name, "description": t.description} for t in tools]

    async def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        """Call a tool by name with arguments."""
        result = await self._client.call_tool(name, arguments or {})
        return result
