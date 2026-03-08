"""A2A bounded context for kiboup.

Re-exports the full a2a-sdk surface so users can always import from
``kiboup.a2a`` instead of ``a2a`` directly.

Submodules:
    - ``kiboup.a2a.server``  — server classes (KiboAgentA2A + all SDK server symbols)
    - ``kiboup.a2a.client``  — client classes (KiboA2AClient + all SDK client symbols)
    - ``kiboup.a2a.types``   — all A2A protocol Pydantic models
    - ``kiboup.a2a.utils``   — all A2A utility functions and constants
"""

from kiboup.a2a.server import KiboAgentA2A
from kiboup.a2a.client import KiboA2AClient

__all__ = [
    "KiboAgentA2A",
    "KiboA2AClient",
]
