"""KiboAgentClient - HTTP client for KiboAgentApp servers."""

import json
from typing import Any, AsyncIterator, Dict, Optional

import httpx

from kiboup.shared.logger import create_logger


class KiboAgentClient:
    """HTTP client for KiboAgentApp servers with optional KiboStudio integration.

    Example:
        async with KiboAgentClient("http://localhost:8080", api_key="sk-abc") as client:
            result = await client.invoke({"prompt": "Hello"})

    Streaming example:
        async with KiboAgentClient("http://localhost:8080", api_key="sk-abc") as client:
            async for chunk in client.stream({"prompt": "Hello"}):
                print(chunk)

    Studio integration:
        async with KiboAgentClient(
            base_url="http://localhost:8080",
            studio_url="http://localhost:8000",
            agent_id="my-agent",
        ) as client:
            result = await client.invoke({"prompt": "Hello"})
            enabled = await client.studio.is_flag_enabled("my_flag")
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        api_key: Optional[str] = None,
        timeout: float = 120.0,
        *,
        studio=None,
        studio_url: Optional[str] = None,
        agent_id: Optional[str] = None,
        **studio_kwargs,
    ):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self.logger = create_logger("kiboup.agent_client")

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

    def _headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        return headers

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            headers=self._headers(),
        )
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
            await self._client.aclose()
            self._client = None

    async def invoke(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Send a request to POST /invocations."""
        response = await self._client.post("/invocations", json=payload)
        response.raise_for_status()
        return response.json()

    async def stream(self, payload: Dict[str, Any]) -> AsyncIterator[Any]:
        """Send a request to POST /invocations and stream SSE chunks.

        Yields parsed JSON objects from each SSE data line.
        """
        async with self._client.stream("POST", "/invocations", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    yield json.loads(data)

    async def ping(self) -> Dict[str, Any]:
        """Check server health via GET /ping."""
        response = await self._client.get("/ping")
        response.raise_for_status()
        return response.json()
