"""Request and SQL timing logs.

- Every request logs method, path, status and total wall time, plus the number
  of SQL queries it ran and the cumulative time spent in them.
- Every SQL statement logs its own execution time; statements slower than
  SLOW_QUERY_MS are logged at WARNING.
"""
import logging
import os
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass

from fastapi import FastAPI, Request
from sqlalchemy import event
from sqlalchemy.engine import Engine

logger = logging.getLogger("app.timing")
sql_logger = logging.getLogger("app.sql")

SLOW_QUERY_MS = float(os.getenv("SLOW_QUERY_MS", "200"))
SLOW_REQUEST_MS = float(os.getenv("SLOW_REQUEST_MS", "1000"))


@dataclass
class RequestStats:
    request_id: str
    query_count: int = 0
    query_time_ms: float = 0.0


_stats: ContextVar[RequestStats | None] = ContextVar("request_stats", default=None)


def setup_logging() -> None:
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=os.getenv("LOG_LEVEL", "INFO"),
            format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        )
    for name in ("app.timing", "app.sql"):
        logging.getLogger(name).setLevel(os.getenv("LOG_LEVEL", "INFO"))


def _one_line(statement: str, limit: int = 300) -> str:
    s = " ".join(statement.split())
    return s if len(s) <= limit else s[:limit] + "..."


def instrument_engine(engine: Engine) -> None:
    @event.listens_for(engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):
        conn.info.setdefault("query_start", []).append(time.perf_counter())

    @event.listens_for(engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):
        elapsed_ms = (time.perf_counter() - conn.info["query_start"].pop()) * 1000
        stats = _stats.get()
        if stats is not None:
            stats.query_count += 1
            stats.query_time_ms += elapsed_ms
        level = logging.WARNING if elapsed_ms >= SLOW_QUERY_MS else logging.INFO
        sql_logger.log(
            level,
            "%s query took %.2f ms: %s",
            "SLOW" if level == logging.WARNING else "SQL",
            elapsed_ms,
            _one_line(statement),
        )

    @event.listens_for(engine, "handle_error")
    def _error(exc_context):
        # Drop the start time so a failed statement doesn't skew the next one.
        starts = exc_context.connection.info.get("query_start") if exc_context.connection else None
        if starts:
            starts.pop()


def add_request_timing(app: FastAPI) -> None:
    @app.middleware("http")
    async def timing_middleware(request: Request, call_next):
        stats = RequestStats(request_id=uuid.uuid4().hex[:8])
        token = _stats.set(stats)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = stats.request_id
            return response
        finally:
            total_ms = (time.perf_counter() - start) * 1000
            logger.log(
                logging.WARNING if total_ms >= SLOW_REQUEST_MS else logging.INFO,
                "[%s] %s %s -> %d in %.2f ms (db: %d queries, %.2f ms; app: %.2f ms)",
                stats.request_id,
                request.method,
                request.url.path,
                status,
                total_ms,
                stats.query_count,
                stats.query_time_ms,
                total_ms - stats.query_time_ms,
            )
            _stats.reset(token)
