"""Protocol definitions for kiboup server and client interfaces."""

import logging
from typing import Protocol, runtime_checkable


@runtime_checkable
class ServerProtocol(Protocol):
    """Common interface for all kiboup servers."""

    logger: logging.Logger

    def run(self, host: str = ..., port: int = ..., **kwargs) -> None: ...


@runtime_checkable
class ClientProtocol(Protocol):
    """Common interface for all kiboup async clients."""

    logger: logging.Logger

    async def __aenter__(self): ...
    async def __aexit__(self, *args): ...
