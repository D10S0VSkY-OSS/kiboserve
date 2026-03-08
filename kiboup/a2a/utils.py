"""A2A utility re-exports for kiboup.

Provides all utility functions and constants from ``a2a.utils`` under the
``kiboup.a2a.utils`` namespace so that user code always imports from
``kiboup.a2a.utils`` instead of ``a2a.utils`` directly.

Example::

    from kiboup.a2a.utils import new_agent_text_message, new_text_artifact
"""

from a2a.utils import *  # noqa: F401, F403
