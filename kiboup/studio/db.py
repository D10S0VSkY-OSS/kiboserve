"""Persistence layer for KiboStudio.

SQLite-based storage with abstract interface for future Redis/Postgres backends.
"""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from kiboup.studio.entities import (
    AgentRegistration,
    AgentStatus,
    EvalCase,
    EvalResult,
    EvalSet,
    SpanKind,
    EvalStatus,
    FeatureFlag,
    Parameter,
    PromptTemplate,
    PromptVersion,
    Session,
    SessionMessage,
    Span,
    Trace,
    _utc_now,
)


class StudioStore(Protocol):
    """Abstract store interface for KiboStudio backends."""

    # -- Traces --
    def save_trace(self, trace: Trace) -> None: ...
    def get_trace(self, trace_id: str) -> Optional[Trace]: ...
    def list_traces(self, limit: int = 50, offset: int = 0, agent_id: Optional[str] = None) -> List[Trace]: ...
    def delete_trace(self, trace_id: str) -> bool: ...

    # -- Spans --
    def save_span(self, span: Span) -> None: ...
    def get_span(self, span_id: str) -> Optional[Span]: ...
    def list_spans_by_trace(self, trace_id: str) -> List[Span]: ...

    # -- Prompts --
    def save_prompt(self, prompt: PromptTemplate) -> None: ...
    def get_prompt(self, prompt_id: str) -> Optional[PromptTemplate]: ...
    def get_prompt_by_name(self, name: str) -> Optional[PromptTemplate]: ...
    def list_prompts(self) -> List[PromptTemplate]: ...
    def delete_prompt(self, prompt_id: str) -> bool: ...
    def save_prompt_version(self, version: PromptVersion) -> None: ...
    def list_prompt_versions(self, prompt_id: str) -> List[PromptVersion]: ...
    def get_active_version(self, prompt_id: str) -> Optional[PromptVersion]: ...

    # -- Evaluations --
    def save_eval(self, result: EvalResult) -> None: ...
    def get_eval(self, eval_id: str) -> Optional[EvalResult]: ...
    def list_evals(self, limit: int = 50, trace_id: Optional[str] = None) -> List[EvalResult]: ...

    # -- Discovery --
    def save_agent(self, agent: AgentRegistration) -> None: ...
    def get_agent(self, agent_id: str) -> Optional[AgentRegistration]: ...
    def list_agents(self, status: Optional[str] = None, protocol: Optional[str] = None) -> List[AgentRegistration]: ...
    def delete_agent(self, agent_id: str) -> bool: ...

    # -- Feature flags --
    def save_flag(self, flag: FeatureFlag) -> None: ...
    def get_flags(self, agent_id: str) -> List[FeatureFlag]: ...
    def delete_flag(self, flag_id: str) -> bool: ...

    # -- Parameters --
    def save_param(self, param: Parameter) -> None: ...
    def get_params(self, agent_id: str) -> List[Parameter]: ...
    def delete_param(self, param_id: str) -> bool: ...

    # -- Sessions --
    def save_session(self, session: Session) -> None: ...
    def get_session(self, session_id: str) -> Optional[Session]: ...
    def list_sessions(self, agent_id: Optional[str] = None, limit: int = 50) -> List[Session]: ...
    def delete_session(self, session_id: str) -> bool: ...
    def save_message(self, message: SessionMessage) -> None: ...
    def list_messages(self, session_id: str) -> List[SessionMessage]: ...

    # -- Eval Sets --
    def save_eval_set(self, eval_set: EvalSet) -> None: ...
    def list_eval_sets(self, agent_id: Optional[str] = None) -> List[EvalSet]: ...
    def save_eval_case(self, case: EvalCase) -> None: ...
    def list_eval_cases(self, eval_set_id: str) -> List[EvalCase]: ...


_SCHEMA = """
CREATE TABLE IF NOT EXISTS traces (
    trace_id TEXT PRIMARY KEY,
    agent_id TEXT,
    session_id TEXT,
    request_id TEXT,
    start_time TEXT NOT NULL,
    end_time TEXT,
    duration_ms REAL,
    status TEXT DEFAULT 'ok',
    metadata TEXT DEFAULT '{}',
    span_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS spans (
    span_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    parent_span_id TEXT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT,
    duration_ms REAL,
    status TEXT DEFAULT 'ok',
    attributes TEXT DEFAULT '{}',
    events TEXT DEFAULT '[]',
    input_data TEXT,
    output_data TEXT,
    error TEXT,
    agent_id TEXT,
    FOREIGN KEY (trace_id) REFERENCES traces(trace_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS prompts (
    prompt_id TEXT PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    description TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    active_version INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prompt_versions (
    version_id TEXT PRIMARY KEY,
    prompt_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    content TEXT NOT NULL,
    model_config TEXT DEFAULT '{}',
    variables TEXT DEFAULT '[]',
    metadata TEXT DEFAULT '{}',
    is_active INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (prompt_id) REFERENCES prompts(prompt_id) ON DELETE CASCADE,
    UNIQUE(prompt_id, version)
);

CREATE TABLE IF NOT EXISTS evaluations (
    eval_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    agent_id TEXT,
    metrics TEXT DEFAULT '{}',
    status TEXT DEFAULT 'pending',
    error TEXT,
    details TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (trace_id) REFERENCES traces(trace_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    protocol TEXT DEFAULT 'http',
    endpoint TEXT NOT NULL,
    capabilities TEXT DEFAULT '[]',
    version TEXT DEFAULT '0.0.0',
    metadata TEXT DEFAULT '{}',
    status TEXT DEFAULT 'healthy',
    registered_at TEXT NOT NULL,
    last_heartbeat TEXT,
    heartbeat_interval_s INTEGER DEFAULT 15,
    uptime_seconds REAL DEFAULT 0,
    active_tasks INTEGER DEFAULT 0,
    error_count_last_5m INTEGER DEFAULT 0,
    memory_mb REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS feature_flags (
    flag_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL DEFAULT '_global',
    name TEXT NOT NULL,
    enabled INTEGER DEFAULT 0,
    value TEXT,
    description TEXT DEFAULT '',
    updated_at TEXT NOT NULL,
    UNIQUE(agent_id, name)
);

CREATE TABLE IF NOT EXISTS parameters (
    param_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL DEFAULT '_global',
    name TEXT NOT NULL,
    value TEXT,
    description TEXT DEFAULT '',
    updated_at TEXT NOT NULL,
    UNIQUE(agent_id, name)
);

CREATE INDEX IF NOT EXISTS idx_spans_trace_id ON spans(trace_id);
CREATE INDEX IF NOT EXISTS idx_traces_agent_id ON traces(agent_id);
CREATE INDEX IF NOT EXISTS idx_traces_start_time ON traces(start_time);
CREATE INDEX IF NOT EXISTS idx_evaluations_trace_id ON evaluations(trace_id);
CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);
CREATE INDEX IF NOT EXISTS idx_feature_flags_agent ON feature_flags(agent_id);
CREATE INDEX IF NOT EXISTS idx_parameters_agent ON parameters(agent_id);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    user_id TEXT DEFAULT 'user',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_messages (
    message_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    content TEXT NOT NULL DEFAULT '',
    trace_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS eval_sets (
    eval_set_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eval_cases (
    case_id TEXT PRIMARY KEY,
    eval_set_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    result TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (eval_set_id) REFERENCES eval_sets(eval_set_id) ON DELETE CASCADE,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sessions_agent ON sessions(agent_id);
CREATE INDEX IF NOT EXISTS idx_session_messages_session ON session_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_eval_cases_set ON eval_cases(eval_set_id);
"""


class SQLiteStore:
    """SQLite-based implementation of StudioStore."""

    def __init__(self, db_path: str = "kibostudio.db"):
        self._db_path = db_path
        self._persistent_conn: sqlite3.Connection | None = None
        if db_path == ":memory:":
            self._persistent_conn = sqlite3.connect(":memory:")
            self._persistent_conn.execute("PRAGMA journal_mode=WAL")
            self._persistent_conn.execute("PRAGMA foreign_keys=ON")
            self._persistent_conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _conn(self):
        if self._persistent_conn is not None:
            yield self._persistent_conn
            self._persistent_conn.commit()
            return
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # -- Traces --

    def save_trace(self, trace: Trace) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO traces
                (trace_id, agent_id, session_id, request_id, start_time, end_time,
                 duration_ms, status, metadata, span_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    trace.trace_id, trace.agent_id, trace.session_id, trace.request_id,
                    trace.start_time, trace.end_time, trace.duration_ms, trace.status,
                    json.dumps(trace.metadata), trace.span_count,
                ),
            )

    def get_trace(self, trace_id: str) -> Optional[Trace]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM traces WHERE trace_id = ?", (trace_id,)).fetchone()
            if not row:
                return None
            return self._row_to_trace(row)

    def list_traces(self, limit: int = 50, offset: int = 0, agent_id: Optional[str] = None) -> List[Trace]:
        with self._conn() as conn:
            if agent_id:
                rows = conn.execute(
                    "SELECT * FROM traces WHERE agent_id = ? ORDER BY start_time DESC LIMIT ? OFFSET ?",
                    (agent_id, limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM traces ORDER BY start_time DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
            return [self._row_to_trace(r) for r in rows]

    def delete_trace(self, trace_id: str) -> bool:
        with self._conn() as conn:
            cursor = conn.execute("DELETE FROM traces WHERE trace_id = ?", (trace_id,))
            return cursor.rowcount > 0

    # -- Spans --

    def save_span(self, span: Span) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO spans
                (span_id, trace_id, parent_span_id, name, kind, start_time, end_time,
                 duration_ms, status, attributes, events, input_data, output_data, error, agent_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    span.span_id, span.trace_id, span.parent_span_id, span.name,
                    span.kind.value if isinstance(span.kind, SpanKind) else span.kind,
                    span.start_time, span.end_time, span.duration_ms, span.status,
                    json.dumps(span.attributes), json.dumps(span.events),
                    json.dumps(span.input_data) if span.input_data else None,
                    json.dumps(span.output_data) if span.output_data else None,
                    span.error, span.agent_id,
                ),
            )
            conn.execute(
                "UPDATE traces SET span_count = (SELECT COUNT(*) FROM spans WHERE trace_id = ?) WHERE trace_id = ?",
                (span.trace_id, span.trace_id),
            )

    def get_span(self, span_id: str) -> Optional[Span]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM spans WHERE span_id = ?", (span_id,)).fetchone()
            if not row:
                return None
            return self._row_to_span(row)

    def list_spans_by_trace(self, trace_id: str) -> List[Span]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM spans WHERE trace_id = ? ORDER BY start_time ASC",
                (trace_id,),
            ).fetchall()
            return [self._row_to_span(r) for r in rows]

    # -- Prompts --

    def save_prompt(self, prompt: PromptTemplate) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO prompts
                (prompt_id, name, description, tags, active_version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    prompt.prompt_id, prompt.name, prompt.description,
                    json.dumps(prompt.tags), prompt.active_version,
                    prompt.created_at, prompt.updated_at,
                ),
            )

    def get_prompt(self, prompt_id: str) -> Optional[PromptTemplate]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM prompts WHERE prompt_id = ?", (prompt_id,)).fetchone()
            if not row:
                return None
            return self._row_to_prompt(row)

    def get_prompt_by_name(self, name: str) -> Optional[PromptTemplate]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM prompts WHERE name = ?", (name,)).fetchone()
            if not row:
                return None
            return self._row_to_prompt(row)

    def list_prompts(self) -> List[PromptTemplate]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM prompts ORDER BY updated_at DESC").fetchall()
            return [self._row_to_prompt(r) for r in rows]

    def delete_prompt(self, prompt_id: str) -> bool:
        with self._conn() as conn:
            cursor = conn.execute("DELETE FROM prompts WHERE prompt_id = ?", (prompt_id,))
            return cursor.rowcount > 0

    def save_prompt_version(self, version: PromptVersion) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO prompt_versions
                (version_id, prompt_id, version, content, model_config, variables,
                 metadata, is_active, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    version.version_id, version.prompt_id, version.version,
                    version.content, json.dumps(version.model_config),
                    json.dumps(version.variables), json.dumps(version.metadata),
                    1 if version.is_active else 0, version.created_at,
                ),
            )

    def list_prompt_versions(self, prompt_id: str) -> List[PromptVersion]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM prompt_versions WHERE prompt_id = ? ORDER BY version DESC",
                (prompt_id,),
            ).fetchall()
            return [self._row_to_prompt_version(r) for r in rows]

    def get_active_version(self, prompt_id: str) -> Optional[PromptVersion]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM prompt_versions WHERE prompt_id = ? AND is_active = 1",
                (prompt_id,),
            ).fetchone()
            if not row:
                return None
            return self._row_to_prompt_version(row)

    # -- Evaluations --

    def save_eval(self, result: EvalResult) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO evaluations
                (eval_id, trace_id, agent_id, metrics, status, error, details,
                 created_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    result.eval_id, result.trace_id, result.agent_id,
                    json.dumps(result.metrics),
                    result.status.value if isinstance(result.status, EvalStatus) else result.status,
                    result.error, json.dumps(result.details),
                    result.created_at, result.completed_at,
                ),
            )

    def get_eval(self, eval_id: str) -> Optional[EvalResult]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM evaluations WHERE eval_id = ?", (eval_id,)).fetchone()
            if not row:
                return None
            return self._row_to_eval(row)

    def list_evals(self, limit: int = 50, trace_id: Optional[str] = None) -> List[EvalResult]:
        with self._conn() as conn:
            if trace_id:
                rows = conn.execute(
                    "SELECT * FROM evaluations WHERE trace_id = ? ORDER BY created_at DESC LIMIT ?",
                    (trace_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM evaluations ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [self._row_to_eval(r) for r in rows]

    # -- Discovery --

    def save_agent(self, agent: AgentRegistration) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO agents
                (agent_id, name, protocol, endpoint, capabilities, version,
                 metadata, status, registered_at, last_heartbeat,
                 heartbeat_interval_s, uptime_seconds, active_tasks,
                 error_count_last_5m, memory_mb)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    agent.agent_id, agent.name, agent.protocol, agent.endpoint,
                    json.dumps(agent.capabilities), agent.version,
                    json.dumps(agent.metadata),
                    agent.status.value if isinstance(agent.status, AgentStatus) else agent.status,
                    agent.registered_at, agent.last_heartbeat,
                    agent.heartbeat_interval_s, agent.uptime_seconds,
                    agent.active_tasks, agent.error_count_last_5m, agent.memory_mb,
                ),
            )

    def get_agent(self, agent_id: str) -> Optional[AgentRegistration]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
            if not row:
                return None
            return self._row_to_agent(row)

    def list_agents(self, status: Optional[str] = None, protocol: Optional[str] = None) -> List[AgentRegistration]:
        with self._conn() as conn:
            query = "SELECT * FROM agents"
            params: list = []
            conditions = []
            if status:
                conditions.append("status = ?")
                params.append(status)
            if protocol:
                conditions.append("protocol = ?")
                params.append(protocol)
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY name ASC"
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_agent(r) for r in rows]

    def delete_agent(self, agent_id: str) -> bool:
        with self._conn() as conn:
            cursor = conn.execute("DELETE FROM agents WHERE agent_id = ?", (agent_id,))
            return cursor.rowcount > 0

    # -- Feature flags --

    def save_flag(self, flag: FeatureFlag) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO feature_flags
                (flag_id, agent_id, name, enabled, value, description, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    flag.flag_id, flag.agent_id, flag.name,
                    1 if flag.enabled else 0,
                    json.dumps(flag.value) if flag.value is not None else None,
                    flag.description, flag.updated_at,
                ),
            )

    def get_flags(self, agent_id: str) -> List[FeatureFlag]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM feature_flags WHERE agent_id = ? ORDER BY name ASC",
                (agent_id,),
            ).fetchall()
            return [self._row_to_flag(r) for r in rows]

    def delete_flag(self, flag_id: str) -> bool:
        with self._conn() as conn:
            cursor = conn.execute("DELETE FROM feature_flags WHERE flag_id = ?", (flag_id,))
            return cursor.rowcount > 0

    # -- Parameters --

    def save_param(self, param: Parameter) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO parameters
                (param_id, agent_id, name, value, description, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    param.param_id, param.agent_id, param.name,
                    json.dumps(param.value) if param.value is not None else None,
                    param.description, param.updated_at,
                ),
            )

    def get_params(self, agent_id: str) -> List[Parameter]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM parameters WHERE agent_id = ? ORDER BY name ASC",
                (agent_id,),
            ).fetchall()
            return [self._row_to_param(r) for r in rows]

    def delete_param(self, param_id: str) -> bool:
        with self._conn() as conn:
            cursor = conn.execute("DELETE FROM parameters WHERE param_id = ?", (param_id,))
            return cursor.rowcount > 0

    # -- Sessions --

    def save_session(self, session: Session) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO sessions
                (session_id, agent_id, user_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)""",
                (session.session_id, session.agent_id, session.user_id,
                 session.created_at, session.updated_at),
            )

    def get_session(self, session_id: str) -> Optional[Session]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
            if not row:
                return None
            return Session(
                session_id=row["session_id"], agent_id=row["agent_id"],
                user_id=row["user_id"], created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    def list_sessions(self, agent_id: Optional[str] = None, limit: int = 50) -> List[Session]:
        with self._conn() as conn:
            if agent_id:
                rows = conn.execute(
                    "SELECT * FROM sessions WHERE agent_id = ? ORDER BY updated_at DESC LIMIT ?",
                    (agent_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?", (limit,),
                ).fetchall()
            return [
                Session(session_id=r["session_id"], agent_id=r["agent_id"],
                        user_id=r["user_id"], created_at=r["created_at"],
                        updated_at=r["updated_at"])
                for r in rows
            ]

    def delete_session(self, session_id: str) -> bool:
        with self._conn() as conn:
            cursor = conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            return cursor.rowcount > 0

    def save_message(self, message: SessionMessage) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO session_messages
                (message_id, session_id, role, content, trace_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (message.message_id, message.session_id, message.role,
                 message.content, message.trace_id, message.created_at),
            )
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                (_utc_now(), message.session_id),
            )

    def list_messages(self, session_id: str) -> List[SessionMessage]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM session_messages WHERE session_id = ? ORDER BY created_at ASC",
                (session_id,),
            ).fetchall()
            return [
                SessionMessage(
                    message_id=r["message_id"], session_id=r["session_id"],
                    role=r["role"], content=r["content"],
                    trace_id=r["trace_id"], created_at=r["created_at"],
                )
                for r in rows
            ]

    # -- Eval Sets --

    def save_eval_set(self, eval_set: EvalSet) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO eval_sets
                (eval_set_id, name, agent_id, created_at)
                VALUES (?, ?, ?, ?)""",
                (eval_set.eval_set_id, eval_set.name, eval_set.agent_id,
                 eval_set.created_at),
            )

    def list_eval_sets(self, agent_id: Optional[str] = None) -> List[EvalSet]:
        with self._conn() as conn:
            if agent_id:
                rows = conn.execute(
                    "SELECT * FROM eval_sets WHERE agent_id = ? ORDER BY created_at DESC",
                    (agent_id,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM eval_sets ORDER BY created_at DESC").fetchall()
            return [
                EvalSet(eval_set_id=r["eval_set_id"], name=r["name"],
                        agent_id=r["agent_id"], created_at=r["created_at"])
                for r in rows
            ]

    def save_eval_case(self, case: EvalCase) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO eval_cases
                (case_id, eval_set_id, session_id, status, result, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (case.case_id, case.eval_set_id, case.session_id,
                 case.status, json.dumps(case.result or {}), case.created_at),
            )

    def list_eval_cases(self, eval_set_id: str) -> List[EvalCase]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM eval_cases WHERE eval_set_id = ? ORDER BY created_at ASC",
                (eval_set_id,),
            ).fetchall()
            return [
                EvalCase(
                    case_id=r["case_id"], eval_set_id=r["eval_set_id"],
                    session_id=r["session_id"], status=r["status"],
                    result=json.loads(r["result"]) if r["result"] else {},
                    created_at=r["created_at"],
                )
                for r in rows
            ]

    # -- Row mappers --

    @staticmethod
    def _row_to_trace(row: sqlite3.Row) -> Trace:
        return Trace(
            trace_id=row["trace_id"],
            agent_id=row["agent_id"],
            session_id=row["session_id"],
            request_id=row["request_id"],
            start_time=row["start_time"],
            end_time=row["end_time"],
            duration_ms=row["duration_ms"],
            status=row["status"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            span_count=row["span_count"] or 0,
        )

    @staticmethod
    def _row_to_span(row: sqlite3.Row) -> Span:
        from kiboup.studio.entities import SpanKind
        kind_val = row["kind"]
        try:
            kind = SpanKind(kind_val)
        except ValueError:
            kind = SpanKind.CUSTOM
        return Span(
            span_id=row["span_id"],
            trace_id=row["trace_id"],
            parent_span_id=row["parent_span_id"],
            name=row["name"],
            kind=kind,
            start_time=row["start_time"],
            end_time=row["end_time"],
            duration_ms=row["duration_ms"],
            status=row["status"],
            attributes=json.loads(row["attributes"]) if row["attributes"] else {},
            events=json.loads(row["events"]) if row["events"] else [],
            input_data=json.loads(row["input_data"]) if row["input_data"] else None,
            output_data=json.loads(row["output_data"]) if row["output_data"] else None,
            error=row["error"],
            agent_id=row["agent_id"],
        )

    @staticmethod
    def _row_to_prompt(row: sqlite3.Row) -> PromptTemplate:
        return PromptTemplate(
            prompt_id=row["prompt_id"],
            name=row["name"],
            description=row["description"],
            tags=json.loads(row["tags"]) if row["tags"] else [],
            active_version=row["active_version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_prompt_version(row: sqlite3.Row) -> PromptVersion:
        return PromptVersion(
            version_id=row["version_id"],
            prompt_id=row["prompt_id"],
            version=row["version"],
            content=row["content"],
            model_config=json.loads(row["model_config"]) if row["model_config"] else {},
            variables=json.loads(row["variables"]) if row["variables"] else [],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_eval(row: sqlite3.Row) -> EvalResult:
        status_val = row["status"]
        try:
            status = EvalStatus(status_val)
        except ValueError:
            status = EvalStatus.PENDING
        return EvalResult(
            eval_id=row["eval_id"],
            trace_id=row["trace_id"],
            agent_id=row["agent_id"],
            metrics=json.loads(row["metrics"]) if row["metrics"] else {},
            status=status,
            error=row["error"],
            details=json.loads(row["details"]) if row["details"] else {},
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )

    @staticmethod
    def _row_to_agent(row: sqlite3.Row) -> AgentRegistration:
        status_val = row["status"]
        try:
            status = AgentStatus(status_val)
        except ValueError:
            status = AgentStatus.HEALTHY
        return AgentRegistration(
            agent_id=row["agent_id"],
            name=row["name"],
            protocol=row["protocol"],
            endpoint=row["endpoint"],
            capabilities=json.loads(row["capabilities"]) if row["capabilities"] else [],
            version=row["version"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            status=status,
            registered_at=row["registered_at"],
            last_heartbeat=row["last_heartbeat"],
            heartbeat_interval_s=row["heartbeat_interval_s"] or 15,
            uptime_seconds=row["uptime_seconds"] or 0,
            active_tasks=row["active_tasks"] or 0,
            error_count_last_5m=row["error_count_last_5m"] or 0,
            memory_mb=row["memory_mb"] or 0,
        )

    @staticmethod
    def _row_to_flag(row: sqlite3.Row) -> FeatureFlag:
        return FeatureFlag(
            flag_id=row["flag_id"],
            agent_id=row["agent_id"],
            name=row["name"],
            enabled=bool(row["enabled"]),
            value=json.loads(row["value"]) if row["value"] else None,
            description=row["description"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_param(row: sqlite3.Row) -> Parameter:
        return Parameter(
            param_id=row["param_id"],
            agent_id=row["agent_id"],
            name=row["name"],
            value=json.loads(row["value"]) if row["value"] else None,
            description=row["description"],
            updated_at=row["updated_at"],
        )
