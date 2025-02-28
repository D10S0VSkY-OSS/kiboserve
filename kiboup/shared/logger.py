"""Structured JSON logging for kiboup."""

import json
import logging
import traceback as tb_module
from datetime import datetime, timezone

from kiboup.shared.entities import LLMUsage


class _JsonFormatter(logging.Formatter):
    """Structured JSON log formatter."""

    def format(self, record):
        entry = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        if getattr(record, "request_id", None):
            entry["request_id"] = record.request_id
        if getattr(record, "session_id", None):
            entry["session_id"] = record.session_id
        if getattr(record, "client_id", None):
            entry["client_id"] = record.client_id
        llm_usage = getattr(record, "llm_usage", None)
        if llm_usage is not None:
            if isinstance(llm_usage, LLMUsage):
                entry["llm_usage"] = llm_usage.to_dict()
            elif isinstance(llm_usage, dict):
                entry["llm_usage"] = llm_usage
        if record.exc_info and record.exc_info[0] is not None:
            entry["error_type"] = record.exc_info[0].__name__
            entry["error_message"] = str(record.exc_info[1])
            entry["stack_trace"] = tb_module.format_exception(*record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def create_logger(name: str, debug: bool = False) -> logging.Logger:
    """Create a structured JSON logger."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(_JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG if debug else logging.INFO)
    return logger
