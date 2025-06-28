"""HTTP collector endpoint for receiving spans from agents.

Receives span data via REST API and persists to the StudioStore.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from kiboup.studio.db import SQLiteStore
from kiboup.studio.entities import Span, SpanKind, Trace, _utc_now


class SpanCollector:
    """Receives and persists spans from remote agents."""

    def __init__(self, store: SQLiteStore, logger: Optional[logging.Logger] = None):
        self._store = store
        self._logger = logger

    def ingest_spans(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Ingest a batch of spans from an agent.

        Expected payload format:
            {
                "trace_id": "...",
                "agent_id": "...",
                "session_id": "...",
                "request_id": "...",
                "spans": [
                    {
                        "span_id": "...",
                        "parent_span_id": null,
                        "name": "invocation",
                        "kind": "invocation",
                        "start_time": "...",
                        "end_time": "...",
                        "duration_ms": 123.4,
                        "status": "ok",
                        "attributes": {},
                        "input_data": {},
                        "output_data": {},
                        "error": null
                    }
                ]
            }
        """
        trace_id = payload.get("trace_id", "")
        agent_id = payload.get("agent_id")
        session_id = payload.get("session_id")
        request_id = payload.get("request_id")
        raw_spans = payload.get("spans", [])

        if not trace_id or not raw_spans:
            return {"error": "trace_id and spans are required", "accepted": 0}

        existing_trace = self._store.get_trace(trace_id)
        if not existing_trace:
            start_times = [s.get("start_time", "") for s in raw_spans if s.get("start_time")]
            end_times = [s.get("end_time", "") for s in raw_spans if s.get("end_time")]

            trace = Trace(
                trace_id=trace_id,
                agent_id=agent_id,
                session_id=session_id,
                request_id=request_id,
                start_time=min(start_times) if start_times else _utc_now(),
                end_time=max(end_times) if end_times else None,
                status="ok",
            )
            durations = [s.get("duration_ms", 0) for s in raw_spans if s.get("duration_ms")]
            if durations:
                trace.duration_ms = max(durations)
            self._store.save_trace(trace)

        accepted = 0
        for raw in raw_spans:
            try:
                kind_str = raw.get("kind", "custom")
                try:
                    kind = SpanKind(kind_str)
                except ValueError:
                    kind = SpanKind.CUSTOM

                span = Span(
                    span_id=raw.get("span_id", ""),
                    trace_id=trace_id,
                    parent_span_id=raw.get("parent_span_id"),
                    name=raw.get("name", "unknown"),
                    kind=kind,
                    start_time=raw.get("start_time", _utc_now()),
                    end_time=raw.get("end_time"),
                    duration_ms=raw.get("duration_ms"),
                    status=raw.get("status", "ok"),
                    attributes=raw.get("attributes", {}),
                    events=raw.get("events", []),
                    input_data=raw.get("input_data"),
                    output_data=raw.get("output_data"),
                    error=raw.get("error"),
                    agent_id=agent_id,
                )
                self._store.save_span(span)
                accepted += 1
            except Exception as exc:
                if self._logger:
                    self._logger.warning("Failed to ingest span: %s", exc)

        if existing_trace:
            updated = self._store.get_trace(trace_id)
            if updated and end_times:
                latest_end = max(end_times)
                if not updated.end_time or latest_end > updated.end_time:
                    updated.end_time = latest_end
                    self._store.save_trace(updated)

        return {"trace_id": trace_id, "accepted": accepted, "total": len(raw_spans)}
