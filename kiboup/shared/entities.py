"""Core domain entities for kiboup."""

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class HealthStatus(str, Enum):
    """Health status for ping/health endpoints."""

    HEALTHY = "Healthy"
    BUSY = "Busy"


@dataclass
class LLMUsage:
    """Optional LLM response metadata for structured logging.

    All fields are optional. Pass an instance to ``_log()`` or attach
    it to a log record via ``extra={"llm_usage": usage}`` to include
    LLM metrics in the JSON log output.

    Example:
        usage = LLMUsage(
            model="gpt-4o-mini",
            input_tokens=120,
            output_tokens=58,
            total_tokens=178,
            latency_ms=430.5,
        )
        self._log(logging.INFO, "LLM call done", context, llm_usage=usage)
    """

    model: Optional[str] = None
    provider: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    latency_ms: Optional[float] = None
    extra: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return non-None fields as a dict."""
        raw = asdict(self)
        return {k: v for k, v in raw.items() if v is not None}


@dataclass
class RequestContext:
    """Request context passed to handler functions."""

    request_id: str = ""
    session_id: Optional[str] = None
    client_id: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    request: Any = None
    _llm_usage: Optional[Any] = field(default=None, repr=False)
