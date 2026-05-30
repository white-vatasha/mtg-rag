"""
Datadog logging, APM traces, and DogStatsD metrics for MTG-Rag.

Enable with DD_TRACE_ENABLED=true (and a reachable agent) or DD_API_KEY when using
the in-cluster Datadog Agent. Logs are JSON on stdout for agent collection.
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import contextmanager
from typing import Any, Generator, Iterator

_CONFIGURED = False
_statsd = None


def configure_observability() -> None:
    """Idempotent setup: JSON logging, optional ddtrace patches and StatsD."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    from api.config import get_settings

    settings = get_settings()
    _setup_logging(settings)
    if settings.dd_trace_enabled:
        _setup_tracing(settings)
    if settings.dd_metrics_enabled:
        _setup_statsd(settings)


def _setup_logging(settings) -> None:
    root = logging.getLogger()
    if root.handlers:
        return

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    root.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    if settings.dd_logs_json:
        handler.setFormatter(_DatadogJsonFormatter(settings))
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s [%(name)s] %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )
    root.addHandler(handler)

    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logging.getLogger(name).setLevel(level)


class _DatadogJsonFormatter(logging.Formatter):
    """JSON logs compatible with Datadog log pipelines and trace correlation."""

    def __init__(self, settings) -> None:
        super().__init__()
        self._service = settings.dd_service
        self._env = settings.dd_env
        self._version = settings.dd_version

    def format(self, record: logging.LogRecord) -> str:
        import json

        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self._service,
            "dd.env": self._env,
            "dd.version": self._version,
        }
        if record.exc_info:
            payload["error.kind"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            payload["error.message"] = str(record.exc_info[1]) if record.exc_info[1] else None
            payload["error.stack"] = self.formatException(record.exc_info)

        for key, value in record.__dict__.items():
            if key.startswith("dd.") or key.startswith("mtg_rag."):
                payload[key] = value

        # ddtrace log injection adds dd.trace_id / dd.span_id on the record
        trace_id = getattr(record, "dd.trace_id", None)
        span_id = getattr(record, "dd.span_id", None)
        if trace_id:
            payload["dd.trace_id"] = trace_id
        if span_id:
            payload["dd.span_id"] = span_id

        return json.dumps(payload, default=str)


def _setup_tracing(settings) -> None:
    os.environ.setdefault("DD_SERVICE", settings.dd_service)
    os.environ.setdefault("DD_ENV", settings.dd_env)
    os.environ.setdefault("DD_VERSION", settings.dd_version)
    os.environ.setdefault("DD_AGENT_HOST", settings.dd_agent_host)
    os.environ.setdefault("DD_TRACE_AGENT_PORT", str(settings.dd_trace_agent_port))
    if settings.dd_logs_injection:
        os.environ.setdefault("DD_LOGS_INJECTION", "true")

    from ddtrace import config, patch

    config.service = settings.dd_service
    config.env = settings.dd_env
    config.version = settings.dd_version

    patch(
        fastapi=True,
        sqlalchemy=True,
        requests=True,
        httpx=True,
        asyncio=True,
        logging=True,
    )


def _setup_statsd(settings) -> None:
    global _statsd
    try:
        from datadog import initialize, statsd as dogstatsd

        initialize(
            statsd_host=settings.dd_agent_host,
            statsd_port=settings.dd_dogstatsd_port,
            statsd_constant_tags=[
                f"service:{settings.dd_service}",
                f"env:{settings.dd_env}",
            ],
        )
        _statsd = dogstatsd
    except Exception as exc:
        logging.getLogger(__name__).warning("DogStatsD unavailable: %s", exc)
        _statsd = None


def get_logger(name: str) -> logging.Logger:
    configure_observability()
    return logging.getLogger(name)


def emit_bootstrap_event(phase: str, message: str, **fields: Any) -> None:
    """Structured bootstrap log + optional metric and span tag."""
    extra = {
        "mtg_rag.bootstrap.phase": phase,
        **{f"mtg_rag.{k}": v for k, v in fields.items()},
    }
    get_logger("mtg_rag.bootstrap").info(message, extra=extra)
    if _statsd:
        _statsd.gauge("mtg_rag.bootstrap.phase", 1, tags=[f"phase:{phase}"])
    for key in ("card_count", "decks_indexed", "rag_ready"):
        if key in fields and _statsd:
            _statsd.gauge(f"mtg_rag.bootstrap.{key}", float(fields[key]))


@contextmanager
def trace_operation(
    name: str,
    *,
    resource: str | None = None,
    tags: dict[str, Any] | None = None,
) -> Generator[Any, None, None]:
    from api.config import get_settings

    if not get_settings().dd_trace_enabled:
        yield None
        return

    from ddtrace import tracer

    resource_name = resource or name
    with tracer.trace(name, resource=resource_name) as span:
        if tags:
            for key, value in tags.items():
                span.set_tag(key, value)
        yield span


def trace_rag_query(question: str) -> Iterator[Any]:
    preview = question[:120] + ("…" if len(question) > 120 else "")
    return trace_operation(
        "mtg_rag.query",
        resource="commander_qa",
        tags={"query.length": len(question), "query.preview": preview},
    )
