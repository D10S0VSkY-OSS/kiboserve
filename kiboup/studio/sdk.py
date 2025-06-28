"""SDK client for agents to interact with KiboStudio.

Provides a simple API for agents to:
- Register with discovery
- Send heartbeats
- Query feature flags and parameters
- Fetch managed prompts
- Send trace data
"""

import asyncio
import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional

import httpx

from kiboup.shared.logger import create_logger


class StudioClient:
    """Client for agents to communicate with KiboStudio server.

    Example:
        studio = StudioClient(
            studio_url="http://localhost:8000",
            agent_id="my-agent",
            agent_name="My Agent",
            agent_endpoint="http://localhost:8080",
        )

        async with studio:
            flags = await studio.get_flags()
            prompt = await studio.get_prompt("summarizer")
    """

    def __init__(
        self,
        studio_url: str = "http://localhost:8000",
        agent_id: str = "",
        agent_name: str = "",
        agent_endpoint: str = "",
        agent_protocol: str = "http",
        capabilities: Optional[List[str]] = None,
        version: str = "0.0.0",
        heartbeat_interval_s: int = 15,
        auto_register: bool = True,
        auto_heartbeat: bool = True,
        debug: bool = False,
    ):
        self._studio_url = studio_url.rstrip("/")
        self._agent_id = agent_id or agent_name or "unknown"
        self._agent_name = agent_name or agent_id or "unknown"
        self._agent_endpoint = agent_endpoint
        self._agent_protocol = agent_protocol
        self._capabilities = capabilities or []
        self._version = version
        self._heartbeat_interval = heartbeat_interval_s
        self._auto_register = auto_register
        self._auto_heartbeat = auto_heartbeat
        self._logger = create_logger("kiboup.studio.client", debug)

        self._client: Optional[httpx.AsyncClient] = None
        self._client_loop_id: Optional[int] = None
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._heartbeat_running = False
        self._start_time = time.time()

        self._flags_cache: Dict[str, Any] = {}
        self._params_cache: Dict[str, Any] = {}
        self._flags_cache_ts: float = 0
        self._params_cache_ts: float = 0
        self._cache_ttl: float = 30.0

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=10.0)
        self._client_loop_id = id(asyncio.get_event_loop())
        if self._auto_register:
            await self.register()
        if self._auto_heartbeat:
            self._start_heartbeat()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._stop_heartbeat()
        if self._client:
            await self._client.aclose()
            self._client = None

    # -- Registration --

    async def register(self) -> Dict[str, Any]:
        """Register this agent with KiboStudio discovery."""
        payload = {
            "agent_id": self._agent_id,
            "name": self._agent_name,
            "protocol": self._agent_protocol,
            "endpoint": self._agent_endpoint,
            "capabilities": self._capabilities,
            "version": self._version,
            "heartbeat_interval_s": self._heartbeat_interval,
        }
        try:
            resp = await self._post("/api/discovery/register", payload)
            return resp
        except Exception as exc:
            self._logger.warning("Failed to register with Studio: %s", exc)
            return {}

    # -- Heartbeat --

    def _start_heartbeat(self):
        if self._heartbeat_running:
            return
        self._heartbeat_running = True
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
            name=f"studio-heartbeat-{self._agent_id}",
        )
        self._heartbeat_thread.start()

    def _stop_heartbeat(self):
        self._heartbeat_running = False

    def _heartbeat_loop(self):
        loop = asyncio.new_event_loop()
        while self._heartbeat_running:
            try:
                loop.run_until_complete(self._send_heartbeat_isolated())
            except Exception as exc:
                self._logger.warning("Heartbeat failed: %s", exc)
            time.sleep(self._heartbeat_interval)
        loop.close()

    async def _send_heartbeat_isolated(self):
        """Send heartbeat using a dedicated client (avoids event loop mismatch)."""
        memory_mb = 0.0
        try:
            import psutil
            process = psutil.Process()
            memory_mb = process.memory_info().rss / (1024 * 1024)
        except ImportError:
            pass

        payload = {
            "agent_id": self._agent_id,
            "status": "healthy",
            "uptime_seconds": round(time.time() - self._start_time, 1),
            "active_tasks": 0,
            "error_count_last_5m": 0,
            "memory_mb": round(memory_mb, 1),
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self._studio_url}/api/discovery/heartbeat", json=payload
            )
            resp.raise_for_status()

    # -- Feature flags --

    async def get_flags(self, include_global: bool = True) -> Dict[str, Any]:
        """Get feature flags for this agent."""
        now = time.time()
        if now - self._flags_cache_ts < self._cache_ttl and self._flags_cache:
            return self._flags_cache

        try:
            params = {"include_global": "true" if include_global else "false"}
            resp = await self._get(f"/api/flags/{self._agent_id}", params=params)
            raw = resp.get("flags", {})
            if isinstance(raw, list):
                raw = {f["name"]: f for f in raw if isinstance(f, dict) and "name" in f}
            self._flags_cache = raw
            self._flags_cache_ts = now
            return self._flags_cache
        except Exception:
            return self._flags_cache

    async def is_flag_enabled(self, flag_name: str, default: bool = False) -> bool:
        """Check if a specific flag is enabled."""
        flags = await self.get_flags()
        flag = flags.get(flag_name)
        if flag is None:
            return default
        if isinstance(flag, dict):
            return flag.get("enabled", default)
        return bool(flag)

    # -- Parameters --

    async def get_params(self, include_global: bool = True) -> Dict[str, Any]:
        """Get configuration parameters for this agent."""
        now = time.time()
        if now - self._params_cache_ts < self._cache_ttl and self._params_cache:
            return self._params_cache

        try:
            params = {"include_global": "true" if include_global else "false"}
            resp = await self._get(f"/api/params/{self._agent_id}", params=params)
            raw = resp.get("params", {})
            if isinstance(raw, list):
                raw = {p["name"]: p.get("value") for p in raw if isinstance(p, dict) and "name" in p}
            self._params_cache = raw
            self._params_cache_ts = now
            return self._params_cache
        except Exception:
            return self._params_cache

    async def get_param(self, name: str, default: Any = None) -> Any:
        """Get a single parameter value."""
        params = await self.get_params()
        return params.get(name, default)

    # -- Prompts --

    async def get_prompt(self, name: str) -> Optional[Dict[str, Any]]:
        """Get the active prompt template by name.

        Returns dict with 'content', 'model_config', 'variables', 'version'.
        """
        try:
            resp = await self._get(f"/api/prompts/by-name/{name}")
            return resp
        except Exception:
            return None

    # -- Traces --

    async def send_traces(self, trace_data: Dict[str, Any]) -> Dict[str, Any]:
        """Send trace/span data to the Studio collector."""
        try:
            return await self._post("/api/traces/ingest", trace_data)
        except Exception as exc:
            self._logger.warning("Failed to send traces: %s", exc)
            return {}

    # -- Discovery --

    async def list_agents(self) -> List[Dict[str, Any]]:
        """List all registered agents."""
        try:
            resp = await self._get("/api/discovery/agents")
            return resp.get("agents", [])
        except Exception:
            return []

    # -- HTTP helpers --

    async def _ensure_client(self):
        """Ensure the httpx client belongs to the current event loop."""
        current_loop_id = id(asyncio.get_event_loop())
        if self._client and getattr(self, "_client_loop_id", None) == current_loop_id:
            return
        if self._client:
            try:
                await self._client.aclose()
            except Exception:
                pass
        self._client = httpx.AsyncClient(timeout=10.0)
        self._client_loop_id = current_loop_id

    async def _get(self, path: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        await self._ensure_client()
        resp = await self._client.get(f"{self._studio_url}{path}", params=params)
        resp.raise_for_status()
        return resp.json()

    async def _post(self, path: str, data: Dict[str, Any]) -> Dict[str, Any]:
        await self._ensure_client()
        resp = await self._client.post(f"{self._studio_url}{path}", json=data)
        resp.raise_for_status()
        return resp.json()
