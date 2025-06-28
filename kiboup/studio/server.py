"""KiboStudio - Development environment server for AI agents.

Provides a web UI and REST API for:
- LLM Observability (traces, spans)
- Prompt Management (CRUD, versioning)
- Evaluation (Ragas metrics)
- Agent Discovery (registry, heartbeat, health)
- Feature Flags & Parameter Store
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional, Sequence

import httpx
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.types import Lifespan

from kiboup.shared.banner import detect_host, print_banner, resolve_import_string
from kiboup.shared.logger import create_logger
from kiboup.studio.collector import SpanCollector
from kiboup.studio.db import SQLiteStore
from kiboup.studio.discovery import DiscoveryService
from kiboup.studio.entities import EvalCase, EvalSet, Session, SessionMessage
from kiboup.studio.evaluator import Evaluator
from kiboup.studio.feature_flags import FeatureFlagService
from kiboup.studio.prompts import PromptStore

_UI_DIR = Path(__file__).parent / "ui"


class KiboStudio(Starlette):
    """KiboStudio development server.

    Example:
        studio = KiboStudio()
        studio.run(port=8000)
    """

    def __init__(
        self,
        db_path: str = "kibostudio.db",
        debug: bool = False,
        lifespan: Optional[Lifespan] = None,
        middleware: Sequence[Middleware] | None = None,
    ):
        self.logger = create_logger("kiboup.studio", debug)
        self._static_version = str(int(__import__("time").time()))
        self.store = SQLiteStore(db_path)

        self.collector = SpanCollector(self.store, self.logger)
        self.discovery = DiscoveryService(self.store, self.logger)
        self.evaluator = Evaluator(self.store, self.logger)
        self.prompts = PromptStore(self.store)
        self.flags = FeatureFlagService(self.store)

        routes = self._build_routes()
        all_middleware = list(middleware or [])

        super().__init__(
            routes=routes,
            lifespan=lifespan,
            middleware=all_middleware or None,
            debug=debug,
        )
        self.debug = debug

    def _build_routes(self):
        api_routes = [
            # -- Traces --
            Route("/traces", self._api_list_traces, methods=["GET"]),
            Route("/traces/ingest", self._api_ingest_traces, methods=["POST"]),
            Route("/traces/{trace_id}", self._api_get_trace, methods=["GET", "DELETE"]),
            Route("/traces/{trace_id}/spans", self._api_list_spans, methods=["GET"]),
            Route("/spans/{span_id}", self._api_get_span, methods=["GET"]),

            # -- Prompts --
            Route("/prompts", self._api_prompts_collection, methods=["GET", "POST"]),
            Route("/prompts/by-name/{name}", self._api_get_prompt_by_name, methods=["GET"]),
            Route("/prompts/{prompt_id}", self._api_prompt_item, methods=["GET", "PUT", "DELETE"]),
            Route("/prompts/{prompt_id}/versions", self._api_prompt_versions, methods=["GET", "POST"]),
            Route("/prompts/{prompt_id}/versions/{version}/activate", self._api_activate_version, methods=["PUT"]),

            # -- Evaluations --
            Route("/eval/run", self._api_run_eval, methods=["POST"]),
            Route("/eval/results", self._api_list_evals, methods=["GET"]),
            Route("/eval/results/{eval_id}", self._api_get_eval, methods=["GET"]),

            # -- Discovery --
            Route("/discovery/register", self._api_register_agent, methods=["POST"]),
            Route("/discovery/heartbeat", self._api_heartbeat, methods=["POST"]),
            Route("/discovery/agents", self._api_list_agents, methods=["GET"]),
            Route("/discovery/agents/{agent_id}", self._api_get_agent, methods=["GET", "DELETE"]),

            # -- Feature flags --
            Route("/flags/{agent_id}", self._api_flags_item, methods=["GET", "PUT"]),
            Route("/flags/{agent_id}/{flag_id}", self._api_delete_flag, methods=["DELETE"]),

            # -- Parameters --
            Route("/params/{agent_id}", self._api_params_item, methods=["GET", "PUT"]),
            Route("/params/{agent_id}/{param_id}", self._api_delete_param, methods=["DELETE"]),

            # -- Sessions --
            Route("/sessions", self._api_sessions_collection, methods=["GET", "POST"]),
            Route("/sessions/{session_id}", self._api_session_item, methods=["GET", "DELETE"]),
            Route("/sessions/{session_id}/messages", self._api_session_messages, methods=["GET", "POST"]),

            # -- Eval Sets --
            Route("/eval/sets", self._api_eval_sets_collection, methods=["GET", "POST"]),
            Route("/eval/sets/{eval_set_id}/cases", self._api_eval_cases, methods=["GET", "POST"]),
            Route("/eval/sets/{eval_set_id}/run", self._api_run_eval_set, methods=["POST"]),

            # -- Chat --
            Route("/chat/{agent_id}", self._api_chat_send, methods=["POST"]),
        ]

        routes = [
            Mount("/api", routes=api_routes),
            Route("/", self._ui_studio, methods=["GET"]),
            Route("/traces", self._ui_traces, methods=["GET"]),
            Route("/traces/{trace_id}", self._ui_trace_detail, methods=["GET"]),
            Route("/prompts", self._ui_prompts, methods=["GET"]),
            Route("/eval", self._ui_eval, methods=["GET"]),
            Route("/discovery", self._ui_discovery, methods=["GET"]),
            Route("/flags", self._ui_flags, methods=["GET"]),
            Route("/chat", self._ui_chat, methods=["GET"]),
        ]

        static_dir = _UI_DIR / "static"
        if static_dir.exists():
            routes.append(Mount("/static", app=StaticFiles(directory=str(static_dir)), name="static"))

        return routes

    def run(self, port: int = 8000, host: Optional[str] = None, reload: bool = False, **kwargs):
        """Start the KiboStudio server."""
        import uvicorn

        if host is None:
            host = detect_host()

        print_banner("Studio", host, port)

        self.discovery.start_monitor()

        workers = kwargs.pop("workers", 1)
        needs_import_string = reload or workers > 1

        app_target = self
        if needs_import_string:
            import_string = resolve_import_string(self)
            if import_string is None:
                raise RuntimeError(
                    "Cannot resolve import string for the app. "
                    "When using workers > 1 or reload=True, the app variable "
                    "must be defined at module level."
                )
            app_target = import_string

        uvicorn_config = {
            "host": host,
            "port": port,
            "access_log": self.debug,
            "log_level": "info" if self.debug else "warning",
        }
        if reload:
            uvicorn_config["reload"] = True
        if workers > 1:
            uvicorn_config["workers"] = workers
        uvicorn_config.update(kwargs)
        uvicorn.run(app_target, **uvicorn_config)

    # -----------------------------------------------------------------------
    # API handlers - Traces
    # -----------------------------------------------------------------------

    async def _api_list_traces(self, request):
        limit = int(request.query_params.get("limit", 50))
        offset = int(request.query_params.get("offset", 0))
        agent_id = request.query_params.get("agent_id")
        traces = self.store.list_traces(limit=limit, offset=offset, agent_id=agent_id)
        return JSONResponse({"traces": [t.to_dict() for t in traces]})

    async def _api_ingest_traces(self, request):
        payload = await request.json()
        result = self.collector.ingest_spans(payload)
        return JSONResponse(result)

    async def _api_get_trace(self, request):
        trace_id = request.path_params["trace_id"]
        if request.method == "DELETE":
            ok = self.store.delete_trace(trace_id)
            if not ok:
                return JSONResponse({"error": "Trace not found"}, status_code=404)
            return JSONResponse({"status": "deleted"})

        trace = self.store.get_trace(trace_id)
        if not trace:
            return JSONResponse({"error": "Trace not found"}, status_code=404)
        spans = self.store.list_spans_by_trace(trace_id)
        return JSONResponse({
            "trace": trace.to_dict(),
            "spans": [s.to_dict() for s in spans],
        })

    async def _api_list_spans(self, request):
        trace_id = request.path_params["trace_id"]
        spans = self.store.list_spans_by_trace(trace_id)
        return JSONResponse({"spans": [s.to_dict() for s in spans]})

    async def _api_get_span(self, request):
        span_id = request.path_params["span_id"]
        span = self.store.get_span(span_id)
        if not span:
            return JSONResponse({"error": "Span not found"}, status_code=404)
        return JSONResponse({"span": span.to_dict()})

    # -----------------------------------------------------------------------
    # API handlers - Prompts
    # -----------------------------------------------------------------------

    async def _api_prompts_collection(self, request):
        if request.method == "POST":
            return await self._api_create_prompt(request)
        return await self._api_list_prompts(request)

    async def _api_prompt_item(self, request):
        if request.method == "PUT":
            return await self._api_update_prompt(request)
        if request.method == "DELETE":
            return await self._api_delete_prompt(request)
        return await self._api_get_prompt(request)

    async def _api_prompt_versions(self, request):
        if request.method == "POST":
            return await self._api_create_version(request)
        return await self._api_list_versions(request)

    async def _api_list_prompts(self, request):
        prompts = self.prompts.list_prompts()
        return JSONResponse({"prompts": [p.to_dict() for p in prompts]})

    async def _api_create_prompt(self, request):
        data = await request.json()
        prompt = self.prompts.create_prompt(
            name=data.get("name", ""),
            description=data.get("description", ""),
            tags=data.get("tags"),
            content=data.get("content", ""),
            model_config=data.get("model_config"),
            variables=data.get("variables"),
        )
        return JSONResponse(prompt.to_dict(), status_code=201)

    async def _api_get_prompt(self, request):
        prompt_id = request.path_params["prompt_id"]
        prompt = self.prompts.get_prompt(prompt_id)
        if not prompt:
            return JSONResponse({"error": "Prompt not found"}, status_code=404)
        versions = self.prompts.list_versions(prompt_id)
        return JSONResponse({
            "prompt": prompt.to_dict(),
            "versions": [v.to_dict() for v in versions],
        })

    async def _api_get_prompt_by_name(self, request):
        name = request.path_params["name"]
        result = self.prompts.get_active_content(name)
        if not result:
            return JSONResponse({"error": "Prompt not found"}, status_code=404)
        return JSONResponse(result)

    async def _api_update_prompt(self, request):
        prompt_id = request.path_params["prompt_id"]
        data = await request.json()
        prompt = self.prompts.update_prompt(
            prompt_id,
            name=data.get("name"),
            description=data.get("description"),
            tags=data.get("tags"),
        )
        if not prompt:
            return JSONResponse({"error": "Prompt not found"}, status_code=404)
        return JSONResponse(prompt.to_dict())

    async def _api_delete_prompt(self, request):
        prompt_id = request.path_params["prompt_id"]
        ok = self.prompts.delete_prompt(prompt_id)
        if not ok:
            return JSONResponse({"error": "Prompt not found"}, status_code=404)
        return JSONResponse({"status": "deleted"})

    async def _api_list_versions(self, request):
        prompt_id = request.path_params["prompt_id"]
        versions = self.prompts.list_versions(prompt_id)
        return JSONResponse({"versions": [v.to_dict() for v in versions]})

    async def _api_create_version(self, request):
        prompt_id = request.path_params["prompt_id"]
        data = await request.json()
        version = self.prompts.create_version(
            prompt_id,
            content=data.get("content", ""),
            model_config=data.get("model_config"),
            variables=data.get("variables"),
            metadata=data.get("metadata"),
            activate=data.get("activate", False),
        )
        if not version:
            return JSONResponse({"error": "Prompt not found"}, status_code=404)
        return JSONResponse(version.to_dict(), status_code=201)

    async def _api_activate_version(self, request):
        prompt_id = request.path_params["prompt_id"]
        version = int(request.path_params["version"])
        ok = self.prompts.activate_version(prompt_id, version)
        if not ok:
            return JSONResponse({"error": "Version not found"}, status_code=404)
        return JSONResponse({"status": "activated", "version": version})

    # -----------------------------------------------------------------------
    # API handlers - Evaluations
    # -----------------------------------------------------------------------

    async def _api_run_eval(self, request):
        data = await request.json()
        trace_id = data.get("trace_id", "")
        metrics = data.get("metrics")
        if not trace_id:
            return JSONResponse({"error": "trace_id required"}, status_code=400)
        result = self.evaluator.run_evaluation(trace_id, metrics=metrics)
        return JSONResponse(result.to_dict())

    async def _api_list_evals(self, request):
        limit = int(request.query_params.get("limit", 50))
        trace_id = request.query_params.get("trace_id")
        results = self.evaluator.list_results(limit=limit, trace_id=trace_id)
        return JSONResponse({"evaluations": [r.to_dict() for r in results]})

    async def _api_get_eval(self, request):
        eval_id = request.path_params["eval_id"]
        result = self.evaluator.get_result(eval_id)
        if not result:
            return JSONResponse({"error": "Evaluation not found"}, status_code=404)
        return JSONResponse(result.to_dict())

    # -----------------------------------------------------------------------
    # API handlers - Discovery
    # -----------------------------------------------------------------------

    async def _api_register_agent(self, request):
        data = await request.json()
        agent = self.discovery.register(data)
        return JSONResponse(agent.to_dict(), status_code=201)

    async def _api_heartbeat(self, request):
        data = await request.json()
        agent = self.discovery.heartbeat(data)
        if not agent:
            return JSONResponse({"error": "Agent not registered"}, status_code=404)
        return JSONResponse({"status": agent.status.value, "agent_id": agent.agent_id})

    async def _api_list_agents(self, request):
        status = request.query_params.get("status")
        protocol = request.query_params.get("protocol")
        agents = self.discovery.list_agents(status=status, protocol=protocol)
        return JSONResponse({"agents": [a.to_dict() for a in agents]})

    async def _api_get_agent(self, request):
        agent_id = request.path_params["agent_id"]
        if request.method == "DELETE":
            ok = self.discovery.deregister(agent_id)
            if not ok:
                return JSONResponse({"error": "Agent not found"}, status_code=404)
            return JSONResponse({"status": "deregistered"})

        agent = self.discovery.get_agent(agent_id)
        if not agent:
            return JSONResponse({"error": "Agent not found"}, status_code=404)
        return JSONResponse(agent.to_dict())

    # -----------------------------------------------------------------------
    # API handlers - Feature flags
    # -----------------------------------------------------------------------

    async def _api_flags_item(self, request):
        if request.method == "PUT":
            return await self._api_set_flag(request)
        return await self._api_get_flags(request)

    async def _api_get_flags(self, request):
        agent_id = request.path_params["agent_id"]
        include_global = request.query_params.get("include_global", "true").lower() == "true"
        flags = list(self.flags.get_flags_list(agent_id))
        if include_global and agent_id != "_global":
            seen = {f.name for f in flags}
            for gf in self.flags.get_flags_list("_global"):
                if gf.name not in seen:
                    flags.append(gf)
        return JSONResponse({"flags": [f.to_dict() for f in flags], "agent_id": agent_id})

    async def _api_set_flag(self, request):
        agent_id = request.path_params["agent_id"]
        data = await request.json()
        flag = self.flags.set_flag(
            agent_id=agent_id,
            name=data.get("name", ""),
            enabled=data.get("enabled", False),
            value=data.get("value"),
            description=data.get("description", ""),
        )
        return JSONResponse(flag.to_dict())

    async def _api_delete_flag(self, request):
        flag_id = request.path_params["flag_id"]
        ok = self.flags.delete_flag(flag_id)
        if not ok:
            return JSONResponse({"error": "Flag not found"}, status_code=404)
        return JSONResponse({"status": "deleted"})

    # -----------------------------------------------------------------------
    # API handlers - Parameters
    # -----------------------------------------------------------------------

    async def _api_params_item(self, request):
        if request.method == "PUT":
            return await self._api_set_param(request)
        return await self._api_get_params(request)

    async def _api_get_params(self, request):
        agent_id = request.path_params["agent_id"]
        include_global = request.query_params.get("include_global", "true").lower() == "true"
        params = list(self.flags.get_params_list(agent_id))
        if include_global and agent_id != "_global":
            seen = {p.name for p in params}
            for gp in self.flags.get_params_list("_global"):
                if gp.name not in seen:
                    params.append(gp)
        return JSONResponse({"params": [p.to_dict() for p in params], "agent_id": agent_id})

    async def _api_set_param(self, request):
        agent_id = request.path_params["agent_id"]
        data = await request.json()
        param = self.flags.set_param(
            agent_id=agent_id,
            name=data.get("name", ""),
            value=data.get("value"),
            description=data.get("description", ""),
        )
        return JSONResponse(param.to_dict())

    async def _api_delete_param(self, request):
        param_id = request.path_params["param_id"]
        ok = self.flags.delete_param(param_id)
        if not ok:
            return JSONResponse({"error": "Parameter not found"}, status_code=404)
        return JSONResponse({"status": "deleted"})

    # -----------------------------------------------------------------------
    # UI handlers - HTML pages served via Jinja2-like templates
    # -----------------------------------------------------------------------

    async def _ui_studio(self, request):
        return self._render_page("studio", request)

    async def _ui_index(self, request):
        return self._render_page("index", request)

    async def _ui_traces(self, request):
        return self._render_page("traces", request)

    async def _ui_trace_detail(self, request):
        return self._render_page("trace_detail", request, trace_id=request.path_params["trace_id"])

    async def _ui_prompts(self, request):
        return self._render_page("prompts", request)

    async def _ui_eval(self, request):
        return self._render_page("eval", request)

    async def _ui_discovery(self, request):
        return self._render_page("discovery", request)

    async def _ui_flags(self, request):
        return self._render_page("flags", request)

    async def _ui_chat(self, request):
        return self._render_page("chat", request)

    # -----------------------------------------------------------------------
    # API handlers - Sessions
    # -----------------------------------------------------------------------

    async def _api_sessions_collection(self, request):
        if request.method == "POST":
            data = await request.json()
            session = Session(
                agent_id=data.get("agent_id", ""),
                user_id=data.get("user_id", "user"),
            )
            self.store.save_session(session)
            return JSONResponse(session.to_dict(), status_code=201)
        agent_id = request.query_params.get("agent_id")
        sessions = self.store.list_sessions(agent_id=agent_id)
        return JSONResponse({"sessions": [s.to_dict() for s in sessions]})

    async def _api_session_item(self, request):
        session_id = request.path_params["session_id"]
        if request.method == "DELETE":
            ok = self.store.delete_session(session_id)
            if not ok:
                return JSONResponse({"error": "Session not found"}, status_code=404)
            return JSONResponse({"status": "deleted"})
        session = self.store.get_session(session_id)
        if not session:
            return JSONResponse({"error": "Session not found"}, status_code=404)
        messages = self.store.list_messages(session_id)
        return JSONResponse({
            "session": session.to_dict(),
            "messages": [m.to_dict() for m in messages],
        })

    async def _api_session_messages(self, request):
        session_id = request.path_params["session_id"]
        if request.method == "GET":
            messages = self.store.list_messages(session_id)
            return JSONResponse({"messages": [m.to_dict() for m in messages]})

        session = self.store.get_session(session_id)
        if not session:
            return JSONResponse({"error": "Session not found"}, status_code=404)

        data = await request.json()
        content = data.get("content", "")

        user_msg = SessionMessage(
            session_id=session_id,
            role="user",
            content=content,
        )
        self.store.save_message(user_msg)

        agent = self.discovery.get_agent(session.agent_id)
        if not agent:
            error_msg = SessionMessage(
                session_id=session_id,
                role="error",
                content=f"Agent '{session.agent_id}' not found or unreachable",
            )
            self.store.save_message(error_msg)
            return JSONResponse({"error": "Agent not found"}, status_code=404)

        endpoint = agent.endpoint.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{endpoint}/invocations",
                    json={"prompt": content},
                    headers={"Content-Type": "application/json",
                             "X-Request-Id": user_msg.message_id},
                )
                result = resp.json()

            response_text = result.get("response", json.dumps(result))
            trace_id = user_msg.message_id

            traces = self.store.list_traces(limit=5, agent_id=session.agent_id)
            if traces:
                trace_id = traces[0].trace_id

            assistant_msg = SessionMessage(
                session_id=session_id,
                role="assistant",
                content=response_text,
                trace_id=trace_id,
            )
            self.store.save_message(assistant_msg)

            return JSONResponse({
                "message": assistant_msg.to_dict(),
                "raw": result,
            })

        except Exception as exc:
            error_msg = SessionMessage(
                session_id=session_id,
                role="error",
                content=str(exc),
            )
            self.store.save_message(error_msg)
            return JSONResponse({"error": str(exc)}, status_code=502)

    # -----------------------------------------------------------------------
    # API handlers - Eval Sets
    # -----------------------------------------------------------------------

    async def _api_eval_sets_collection(self, request):
        if request.method == "POST":
            data = await request.json()
            eval_set = EvalSet(
                name=data.get("name", ""),
                agent_id=data.get("agent_id", ""),
            )
            self.store.save_eval_set(eval_set)
            return JSONResponse(eval_set.to_dict(), status_code=201)
        agent_id = request.query_params.get("agent_id")
        sets = self.store.list_eval_sets(agent_id=agent_id)
        return JSONResponse({"eval_sets": [s.to_dict() for s in sets]})

    async def _api_eval_cases(self, request):
        eval_set_id = request.path_params["eval_set_id"]
        if request.method == "POST":
            data = await request.json()
            case = EvalCase(
                eval_set_id=eval_set_id,
                session_id=data.get("session_id", ""),
            )
            self.store.save_eval_case(case)
            return JSONResponse(case.to_dict(), status_code=201)
        cases = self.store.list_eval_cases(eval_set_id)
        return JSONResponse({"cases": [c.to_dict() for c in cases]})

    async def _api_run_eval_set(self, request):
        eval_set_id = request.path_params["eval_set_id"]
        cases = self.store.list_eval_cases(eval_set_id)
        results = []
        for case in cases:
            messages = self.store.list_messages(case.session_id)
            user_msgs = [m for m in messages if m.role == "user"]
            assistant_msgs = [m for m in messages if m.role == "assistant"]
            if not user_msgs:
                continue
            trace_ids = [m.trace_id for m in assistant_msgs if m.trace_id]
            if trace_ids:
                eval_result = self.evaluator.run_evaluation(trace_ids[0])
                case.status = "completed"
                case.result = eval_result.to_dict() if hasattr(eval_result, "to_dict") else {}
            else:
                case.status = "no_trace"
                case.result = {}
            self.store.save_eval_case(case)
            results.append(case.to_dict())
        return JSONResponse({"results": results})

    # -----------------------------------------------------------------------
    # API handlers - Chat proxy
    # -----------------------------------------------------------------------

    async def _api_chat_send(self, request):
        """Proxy a chat message to a discovered agent's /invocations endpoint."""
        agent_id = request.path_params["agent_id"]
        agent = self.discovery.get_agent(agent_id)
        if not agent:
            return JSONResponse({"error": "Agent not found"}, status_code=404)

        data = await request.json()
        endpoint = agent.endpoint.rstrip("/")

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{endpoint}/invocations",
                    json=data,
                    headers={"Content-Type": "application/json"},
                )
                result = resp.json()
                return JSONResponse(result)
        except httpx.ConnectError:
            return JSONResponse(
                {"error": f"Cannot connect to agent at {endpoint}"},
                status_code=502,
            )
        except Exception as exc:
            return JSONResponse(
                {"error": str(exc)},
                status_code=502,
            )

    def _render_page(self, page_name, request, **kwargs):
        """Render an HTML page from templates."""
        from starlette.responses import HTMLResponse

        template_path = _UI_DIR / "templates" / f"{page_name}.html"
        if not template_path.exists():
            template_path = _UI_DIR / "templates" / "base.html"

        if template_path.exists():
            content = template_path.read_text()
            for key, value in kwargs.items():
                content = content.replace(f"{{{{{key}}}}}", str(value))
            v = self._static_version
            content = content.replace("/static/js/studio.js", f"/static/js/studio.js?v={v}")
            content = content.replace("/static/css/studio.css", f"/static/css/studio.css?v={v}")
            return HTMLResponse(content)

        return HTMLResponse(f"<h1>KiboStudio - {page_name}</h1>")
