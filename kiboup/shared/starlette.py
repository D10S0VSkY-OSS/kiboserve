"""Consolidated Starlette re-exports for kiboup.

Provides a single import point for all commonly used Starlette types:
    from kiboup.shared.starlette import JSONResponse, Request, Route, ...
"""

# --- applications ---
from starlette.applications import Starlette

# --- authentication ---
from starlette.authentication import (
    AuthCredentials,
    AuthenticationBackend,
    AuthenticationError,
    BaseUser,
    SimpleUser,
    UnauthenticatedUser,
    has_required_scope,
    requires,
)

# --- background ---
from starlette.background import BackgroundTask, BackgroundTasks

# --- config ---
from starlette.config import Config, Environ, EnvironError

# --- datastructures ---
from starlette.datastructures import (
    URL,
    Address,
    FormData,
    Headers,
    ImmutableMultiDict,
    MultiDict,
    MutableHeaders,
    QueryParams,
    Secret,
    State,
    URLPath,
    UploadFile,
)

# --- endpoints ---
from starlette.endpoints import HTTPEndpoint, WebSocketEndpoint

# --- exceptions ---
from starlette.exceptions import HTTPException, WebSocketException

# --- middleware ---
from starlette.middleware import Middleware

# --- requests ---
from starlette.requests import HTTPConnection, Request

# --- responses ---
from starlette.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)

# --- routing ---
from starlette.routing import BaseRoute, Host, Mount, Route, Router, WebSocketRoute

# --- testclient ---
from starlette.testclient import TestClient

# --- websockets ---
from starlette.websockets import WebSocket, WebSocketClose, WebSocketDisconnect, WebSocketState

__all__ = [
    # applications
    "Starlette",
    # authentication
    "AuthCredentials",
    "AuthenticationBackend",
    "AuthenticationError",
    "BaseUser",
    "SimpleUser",
    "UnauthenticatedUser",
    "has_required_scope",
    "requires",
    # background
    "BackgroundTask",
    "BackgroundTasks",
    # config
    "Config",
    "Environ",
    "EnvironError",
    # datastructures
    "URL",
    "URLPath",
    "Address",
    "Secret",
    "Headers",
    "MutableHeaders",
    "QueryParams",
    "UploadFile",
    "FormData",
    "State",
    "ImmutableMultiDict",
    "MultiDict",
    # endpoints
    "HTTPEndpoint",
    "WebSocketEndpoint",
    # exceptions
    "HTTPException",
    "WebSocketException",
    # middleware
    "Middleware",
    # requests
    "Request",
    "HTTPConnection",
    # responses
    "Response",
    "JSONResponse",
    "HTMLResponse",
    "PlainTextResponse",
    "StreamingResponse",
    "FileResponse",
    "RedirectResponse",
    # routing
    "Route",
    "WebSocketRoute",
    "Mount",
    "Host",
    "Router",
    "BaseRoute",
    # testclient
    "TestClient",
    # websockets
    "WebSocket",
    "WebSocketClose",
    "WebSocketDisconnect",
    "WebSocketState",
]
