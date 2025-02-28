"""KiboA2AClient - A2A protocol client wrapper."""

from typing import Any, Dict, Optional

import httpx

from a2a.client import (
    ClientConfig,
    ClientFactory,
    create_text_message_object,
)

from kiboup.shared.logger import create_logger

__all__ = ["KiboA2AClient"]


class KiboA2AClient:
    """Client for A2A protocol servers.

    Security:
        Pass ``api_key`` for X-API-Key header auth (used by ApiKeyMiddleware),
        or ``bearer_token`` for Authorization Bearer header.

        Authentication is injected at the HTTP transport level,
        independent of A2A protocol specifics.

    Example:
        async with KiboA2AClient("http://localhost:8000", api_key="sk-key") as client:
            response = await client.send("Hello!")
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        timeout: float = 120.0,
        bearer_token: Optional[str] = None,
        api_key: Optional[str] = None,
        client_config: Optional[ClientConfig] = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._bearer_token = bearer_token
        self._api_key = api_key
        self._client_config = client_config
        self._client = None
        self._card = None
        self._httpx_client: Optional[httpx.AsyncClient] = None
        self.logger = create_logger("kiboup.a2a_client")

    def _build_client_config(self) -> ClientConfig:
        """Build ClientConfig injecting auth headers via httpx."""
        config = self._client_config or ClientConfig()

        headers: Dict[str, str] = {}
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        if self._bearer_token:
            headers["Authorization"] = f"Bearer {self._bearer_token}"

        if headers:
            self._httpx_client = httpx.AsyncClient(
                headers=headers,
                timeout=self._timeout,
            )
            config.httpx_client = self._httpx_client

        return config

    async def __aenter__(self):
        config = self._build_client_config()
        self._client = await ClientFactory.connect(
            agent=self._base_url,
            client_config=config,
        )
        self._card = getattr(self._client, "_card", None)
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.close()
            self._client = None
        self._card = None

    async def send(self, text: str) -> Any:
        """Send a text message and return the response."""
        message = create_text_message_object(content=text)
        result = None
        async for event in self._client.send_message(message):
            result = event
        if hasattr(result, "model_dump"):
            return result.model_dump()
        return result

    @property
    def agent_card(self):
        """Access the resolved AgentCard."""
        return self._card
