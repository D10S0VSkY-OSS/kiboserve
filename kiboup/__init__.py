"""kiboup - Framework-agnostic library for deploying AI agents.

Supports three connection modes (server + client):
    - KiboAgentApp / KiboAgentClient: HTTP (pip install kiboup)
    - KiboAgentA2A / KiboA2AClient: A2A protocol (pip install kiboup[a2a])
    - KiboAgentMcp / KiboMcpClient: MCP server (pip install kiboup[mcp])
"""

from kiboup.shared.entities import HealthStatus, LLMUsage, RequestContext
from kiboup.http.server import KiboAgentApp
from kiboup.http.client import KiboAgentClient
from kiboup.shared.middleware import ApiKeyMiddleware

__all__ = [
    "KiboAgentApp",
    "KiboAgentClient",
    "ApiKeyMiddleware",
    "RequestContext",
    "HealthStatus",
    "LLMUsage",
]

try:
    from kiboup.a2a.server import KiboAgentA2A, TaskUpdater
    from kiboup.a2a.client import KiboA2AClient

    __all__.extend(["KiboAgentA2A", "KiboA2AClient", "TaskUpdater"])
except ImportError:
    pass

try:
    from kiboup.mcp.server import KiboAgentMcp
    from kiboup.mcp.client import KiboMcpClient

    __all__.extend(["KiboAgentMcp", "KiboMcpClient"])
except ImportError:
    pass
