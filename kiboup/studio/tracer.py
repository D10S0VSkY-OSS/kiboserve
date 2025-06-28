"""OpenTelemetry-based tracer for KiboStudio.

Instruments agent invocations and sends spans to the Studio collector.
"""

import time
import uuid
from contextlib import contextmanager
from typing import Any, Dict, Optional

from kiboup.studio.entities import Span, SpanKind, Trace, _utc_now


class StudioTracer:
    """Lightweight tracer that creates spans and sends them to a StudioStore.

    Can be used standalone (direct store) or remote (via StudioClient HTTP).

    Example:
        tracer = StudioTracer(store=sqlite_store, agent_id="my-agent")

        with tracer.trace("user-request") as t:
            with t.span("llm_call", kind=SpanKind.LLM_CALL) as s:
                result = call_llm(prompt)
                s.set_output({"response": result})
    """

    def __init__(self, store=None, agent_id: Optional[str] = None):
        self._store = store
        self._agent_id = agent_id

    @contextmanager
    def trace(self, name: str = "request", session_id: Optional[str] = None, request_id: Optional[str] = None):
        """Create a new trace context."""
        ctx = _TraceContext(
            store=self._store,
            agent_id=self._agent_id,
            name=name,
            session_id=session_id,
            request_id=request_id,
        )
        try:
            yield ctx
        except Exception as exc:
            ctx._trace.status = "error"
            ctx._root_span.error = str(exc)
            ctx._root_span.status = "error"
            raise
        finally:
            ctx._finalize()


class _TraceContext:
    """Active trace context that manages span creation."""

    def __init__(self, store, agent_id, name, session_id, request_id):
        self._store = store
        self._agent_id = agent_id
        self._start = time.time()

        trace_id = str(uuid.uuid4())
        self._trace = Trace(
            trace_id=trace_id,
            agent_id=agent_id,
            session_id=session_id,
            request_id=request_id or str(uuid.uuid4()),
        )

        self._root_span = Span(
            trace_id=trace_id,
            name=name,
            kind=SpanKind.INVOCATION,
            agent_id=agent_id,
        )
        self._spans = [self._root_span]

    @property
    def trace_id(self) -> str:
        return self._trace.trace_id

    @property
    def root_span(self) -> Span:
        return self._root_span

    @contextmanager
    def span(
        self,
        name: str,
        kind: SpanKind = SpanKind.CUSTOM,
        parent_span_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ):
        """Create a child span within this trace."""
        s = _SpanContext(
            trace_id=self._trace.trace_id,
            name=name,
            kind=kind,
            parent_span_id=parent_span_id or self._root_span.span_id,
            agent_id=self._agent_id,
            attributes=attributes,
        )
        try:
            yield s
        except Exception as exc:
            s._span.status = "error"
            s._span.error = str(exc)
            raise
        finally:
            s._finalize()
            self._spans.append(s._span)

    def set_input(self, data: Dict[str, Any]):
        self._root_span.input_data = data

    def set_output(self, data: Dict[str, Any]):
        self._root_span.output_data = data

    def add_event(self, name: str, attributes: Optional[Dict[str, Any]] = None):
        self._root_span.events.append({
            "name": name,
            "timestamp": _utc_now(),
            "attributes": attributes or {},
        })

    def _finalize(self):
        end = time.time()
        duration = (end - self._start) * 1000

        self._root_span.end_time = _utc_now()
        self._root_span.duration_ms = round(duration, 2)

        self._trace.end_time = _utc_now()
        self._trace.duration_ms = round(duration, 2)
        self._trace.span_count = len(self._spans)

        if self._store:
            self._store.save_trace(self._trace)
            for span in self._spans:
                self._store.save_span(span)


class _SpanContext:
    """Active span context for recording data."""

    def __init__(self, trace_id, name, kind, parent_span_id, agent_id, attributes):
        self._start = time.time()
        self._span = Span(
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            name=name,
            kind=kind,
            agent_id=agent_id,
            attributes=attributes or {},
        )

    @property
    def span_id(self) -> str:
        return self._span.span_id

    def set_input(self, data: Dict[str, Any]):
        self._span.input_data = data

    def set_output(self, data: Dict[str, Any]):
        self._span.output_data = data

    def set_attribute(self, key: str, value: Any):
        self._span.attributes[key] = value

    def add_event(self, name: str, attributes: Optional[Dict[str, Any]] = None):
        self._span.events.append({
            "name": name,
            "timestamp": _utc_now(),
            "attributes": attributes or {},
        })

    def _finalize(self):
        end = time.time()
        self._span.end_time = _utc_now()
        self._span.duration_ms = round((end - self._start) * 1000, 2)
