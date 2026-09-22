"""Structured logging: one JSON object per line, so Logs Insights can query
any field and the error alarm's metric filter can key on ``level``.

Request payloads, Api-Key values and access tokens are never logged.
"""
import json
import logging
import sys

from . import config

_RESERVED = frozenset(
    (
        "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
        "levelname", "levelno", "lineno", "module", "msecs", "message", "msg", "name",
        "pathname", "process", "processName", "relativeCreated", "stack_info",
        "thread", "threadName", "taskName",
    )
)


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            # The formatted traceback stays in the log, never in the response.
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def get_logger(name="announcements"):
    logger = logging.getLogger(name)
    if not getattr(logger, "_json_configured", False):
        # Lambda pre-installs a root handler; replace rather than add, or
        # every line is logged twice.
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.handlers = [handler]
        logger.propagate = False
        logger._json_configured = True
    logger.setLevel(config.log_level())
    return logger
