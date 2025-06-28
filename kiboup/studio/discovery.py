"""Agent discovery service for KiboStudio."""

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from kiboup.studio.db import SQLiteStore
from kiboup.studio.entities import AgentRegistration, AgentStatus, _utc_now


class DiscoveryService:
    """Service registry with heartbeat-based health monitoring.

    Agents register themselves and send periodic heartbeats.
    If a heartbeat is missed for 3x the interval, the agent
    is marked as unreachable.
    """

    def __init__(
        self,
        store: SQLiteStore,
        logger: Optional[logging.Logger] = None,
        check_interval_s: int = 10,
        error_threshold: int = 5,
    ):
        self._store = store
        self._logger = logger
        self._check_interval = check_interval_s
        self._error_threshold = error_threshold
        self._monitor_thread: Optional[threading.Thread] = None
        self._running = False

    def start_monitor(self):
        """Start the background health monitor thread."""
        if self._running:
            return
        self._running = True
        self._monitor_thread = threading.Thread(
            target=self._health_monitor_loop,
            daemon=True,
            name="studio-discovery-monitor",
        )
        self._monitor_thread.start()

    def stop_monitor(self):
        self._running = False

    def register(self, data: Dict) -> AgentRegistration:
        """Register or update an agent."""
        agent_id = data.get("agent_id", "")
        existing = self._store.get_agent(agent_id) if agent_id else None

        if existing:
            existing.name = data.get("name", existing.name)
            existing.protocol = data.get("protocol", existing.protocol)
            existing.endpoint = data.get("endpoint", existing.endpoint)
            existing.capabilities = data.get("capabilities", existing.capabilities)
            existing.version = data.get("version", existing.version)
            existing.metadata = data.get("metadata", existing.metadata)
            existing.heartbeat_interval_s = data.get("heartbeat_interval_s", existing.heartbeat_interval_s)
            existing.last_heartbeat = _utc_now()
            existing.status = AgentStatus.HEALTHY
            self._store.save_agent(existing)
            return existing

        agent = AgentRegistration(
            agent_id=agent_id or data.get("name", "unknown"),
            name=data.get("name", "unknown"),
            protocol=data.get("protocol", "http"),
            endpoint=data.get("endpoint", ""),
            capabilities=data.get("capabilities", []),
            version=data.get("version", "0.0.0"),
            metadata=data.get("metadata", {}),
            status=AgentStatus.HEALTHY,
            registered_at=_utc_now(),
            last_heartbeat=_utc_now(),
            heartbeat_interval_s=data.get("heartbeat_interval_s", 15),
        )
        self._store.save_agent(agent)
        return agent

    def heartbeat(self, data: Dict) -> Optional[AgentRegistration]:
        """Process a heartbeat from an agent.

        Expected payload:
            {
                "agent_id": "...",
                "status": "healthy",
                "uptime_seconds": 3600,
                "active_tasks": 2,
                "error_count_last_5m": 0,
                "memory_mb": 256
            }
        """
        agent_id = data.get("agent_id", "")
        agent = self._store.get_agent(agent_id)
        if not agent:
            return None

        agent.last_heartbeat = _utc_now()
        agent.uptime_seconds = data.get("uptime_seconds", agent.uptime_seconds)
        agent.active_tasks = data.get("active_tasks", agent.active_tasks)
        agent.error_count_last_5m = data.get("error_count_last_5m", agent.error_count_last_5m)
        agent.memory_mb = data.get("memory_mb", agent.memory_mb)

        reported_status = data.get("status", "healthy")
        if reported_status == "busy":
            agent.status = AgentStatus.BUSY
        elif agent.error_count_last_5m >= self._error_threshold:
            agent.status = AgentStatus.DEGRADED
        else:
            try:
                agent.status = AgentStatus(reported_status)
            except ValueError:
                agent.status = AgentStatus.HEALTHY

        self._store.save_agent(agent)
        return agent

    def deregister(self, agent_id: str) -> bool:
        return self._store.delete_agent(agent_id)

    def get_agent(self, agent_id: str) -> Optional[AgentRegistration]:
        return self._store.get_agent(agent_id)

    def list_agents(
        self,
        status: Optional[str] = None,
        protocol: Optional[str] = None,
    ) -> List[AgentRegistration]:
        return self._store.list_agents(status=status, protocol=protocol)

    def _health_monitor_loop(self):
        """Background loop that marks stale agents as unreachable."""
        while self._running:
            try:
                self._check_agent_health()
            except Exception as exc:
                if self._logger:
                    self._logger.warning("Health monitor error: %s", exc)
            time.sleep(self._check_interval)

    def _check_agent_health(self):
        """Check all agents and mark stale ones as unreachable."""
        agents = self._store.list_agents()
        now = datetime.now(timezone.utc)

        for agent in agents:
            if agent.status == AgentStatus.UNREACHABLE:
                continue
            if not agent.last_heartbeat:
                continue

            try:
                last_hb = datetime.fromisoformat(
                    agent.last_heartbeat.replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                continue

            timeout_s = agent.heartbeat_interval_s * 3
            elapsed = (now - last_hb).total_seconds()

            if elapsed > timeout_s:
                agent.status = AgentStatus.UNREACHABLE
                self._store.save_agent(agent)
                if self._logger:
                    self._logger.info(
                        "Agent %s marked unreachable (no heartbeat for %.0fs)",
                        agent.agent_id,
                        elapsed,
                    )
