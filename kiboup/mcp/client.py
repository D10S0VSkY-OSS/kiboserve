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
    """Client for MCP servers.

    Security:
        Pass ``auth`` to authenticate with the MCP server:
        - A string is treated as a Bearer token
        - ``"oauth"`` triggers the FastMCP OAuth PKCE flow (browser-based)
        - An ``httpx.Auth`` instance for custom auth

        Pass ``api_key`` for X-API-Key header auth (used by ``ApiKeyMiddleware``).

    Example:
        async with KiboMcpClient("http://localhost:8000/sse", auth="my-bearer-token") as client:
            tools = await client.list_tools()

        async with KiboMcpClient("http://localhost:8000/sse", api_key="sk-abc") as client:
            tools = await client.list_tools()
    """

    def __init__(
        self,
        url: str = "http://localhost:8000/sse",
        auth: Union[str, httpx.Auth, None] = None,
        api_key: Optional[str] = None,
    ):
        self._url = url
        if api_key is not None and auth is None:
            self._auth: Union[str, httpx.Auth, None] = _ApiKeyAuth(api_key)
        else:
            self._auth = auth
        self._client: Optional[FastMCPClient] = None
        self.logger = create_logger("kiboup.mcp_client")

    async def __aenter__(self):
        kwargs: Dict[str, Any] = {}
        if self._auth is not None:
            kwargs["auth"] = self._auth
        self._client = FastMCPClient(self._url, **kwargs)
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *args):
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
