"""A2A protocol types re-exported from the a2a-sdk.

Provides all Pydantic models from ``a2a.types`` under the
``kiboup.a2a.types`` namespace so users never need to import
from the underlying SDK directly.

Example::

    from kiboup.a2a.types import AgentCard, AgentSkill, Message
"""

from a2a.types import *  # noqa: F401, F403
