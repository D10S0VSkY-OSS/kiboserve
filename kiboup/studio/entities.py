"""Domain entities for KiboStudio."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


class SpanKind(str, Enum):
    """Kind of span in an agent trace."""

    INVOCATION = "invocation"
    AGENT_RUN = "agent_run"
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    RETRIEVAL = "retrieval"
    CUSTOM = "custom"


class AgentStatus(str, Enum):
    """Health status of a registered agent."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    BUSY = "busy"
    UNREACHABLE = "unreachable"


class EvalMetric(str, Enum):
    """Available evaluation metrics."""

    ANSWER_RELEVANCY = "answer_relevancy"
    COHERENCE = "coherence"
    COMPLETENESS = "completeness"
    HARMFULNESS = "harmfulness"


class EvalStatus(str, Enum):
    """Status of an evaluation run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------


@dataclass
class Span:
    """A single span within a trace."""

    span_id: str = field(default_factory=_new_id)
    trace_id: str = ""
    parent_span_id: Optional[str] = None
    name: str = ""
    kind: SpanKind = SpanKind.CUSTOM
    start_time: str = field(default_factory=_utc_now)
    end_time: Optional[str] = None
    duration_ms: Optional[float] = None
    status: str = "ok"
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)
    input_data: Optional[Dict[str, Any]] = None
    output_data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    agent_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        raw = asdict(self)
        return {k: v for k, v in raw.items() if v is not None}


@dataclass
class Trace:
    """A complete trace grouping related spans."""

    trace_id: str = field(default_factory=_new_id)
    agent_id: Optional[str] = None
    session_id: Optional[str] = None
    request_id: Optional[str] = None
    start_time: str = field(default_factory=_utc_now)
    end_time: Optional[str] = None
    duration_ms: Optional[float] = None
    status: str = "ok"
    metadata: Dict[str, Any] = field(default_factory=dict)
    span_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        raw = asdict(self)
        return {k: v for k, v in raw.items() if v is not None}


# ---------------------------------------------------------------------------
# Prompt management
# ---------------------------------------------------------------------------


@dataclass
class PromptVersion:
    """A specific version of a prompt template."""

    version_id: str = field(default_factory=_new_id)
    prompt_id: str = ""
    version: int = 1
    content: str = ""
    model_config: Dict[str, Any] = field(default_factory=dict)
    variables: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    is_active: bool = False
    created_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PromptTemplate:
    """A prompt template with version history."""

    prompt_id: str = field(default_factory=_new_id)
    name: str = ""
    description: str = ""
    tags: List[str] = field(default_factory=list)
    active_version: Optional[int] = None
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


@dataclass
class EvalResult:
    """Result of an evaluation run."""

    eval_id: str = field(default_factory=_new_id)
    trace_id: str = ""
    agent_id: Optional[str] = None
    metrics: Dict[str, float] = field(default_factory=dict)
    status: EvalStatus = EvalStatus.PENDING
    error: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_utc_now)
    completed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        raw = asdict(self)
        return {k: v for k, v in raw.items() if v is not None}


# ---------------------------------------------------------------------------
# Discovery & feature flags
# ---------------------------------------------------------------------------


@dataclass
class AgentRegistration:
    """Registration record for an agent in the discovery service."""

    agent_id: str = field(default_factory=_new_id)
    name: str = ""
    protocol: str = "http"
    endpoint: str = ""
    capabilities: List[str] = field(default_factory=list)
    version: str = "0.0.0"
    metadata: Dict[str, Any] = field(default_factory=dict)
    status: AgentStatus = AgentStatus.HEALTHY
    registered_at: str = field(default_factory=_utc_now)
    last_heartbeat: Optional[str] = None
    heartbeat_interval_s: int = 15
    uptime_seconds: float = 0
    active_tasks: int = 0
    error_count_last_5m: int = 0
    memory_mb: float = 0

    def to_dict(self) -> Dict[str, Any]:
        raw = asdict(self)
        return {k: v for k, v in raw.items() if v is not None}


@dataclass
class FeatureFlag:
    """A feature flag for an agent or global."""

    flag_id: str = field(default_factory=_new_id)
    agent_id: str = "_global"
    name: str = ""
    enabled: bool = False
    value: Optional[Any] = None
    description: str = ""
    updated_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Parameter:
    """A configuration parameter for an agent or global."""

    param_id: str = field(default_factory=_new_id)
    agent_id: str = "_global"
    name: str = ""
    value: Any = None
    description: str = ""
    updated_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


@dataclass
class Session:
    """A chat session between a user and an agent."""

    session_id: str = field(default_factory=_new_id)
    agent_id: str = ""
    user_id: str = "user"
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SessionMessage:
    """A single message within a session."""

    message_id: str = field(default_factory=_new_id)
    session_id: str = ""
    role: str = "user"
    content: str = ""
    trace_id: Optional[str] = None
    created_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Eval Sets
# ---------------------------------------------------------------------------


@dataclass
class EvalSet:
    """A collection of eval cases for batch evaluation."""

    eval_set_id: str = field(default_factory=_new_id)
    name: str = ""
    agent_id: str = ""
    created_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EvalCase:
    """A single eval case linking a session to an eval set."""

    case_id: str = field(default_factory=_new_id)
    eval_set_id: str = ""
    session_id: str = ""
    status: str = "pending"
    result: Optional[Dict[str, Any]] = None
    created_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> Dict[str, Any]:
        raw = asdict(self)
        return raw
