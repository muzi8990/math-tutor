"""Loguru setup and bounded sanitization for provider error diagnostics."""

import re
import sys
from time import perf_counter
from uuid import uuid4

from loguru import logger


def safe_error(message, *, secrets=(), texts=()):
    value = str(message or "No error message")
    # Replace known inputs before truncation, so truncated secrets never leak.
    for item in sorted({str(v) for v in [*secrets, *texts] if v}, key=len, reverse=True):
        value = value.replace(item, "[REDACTED]")
    value = re.sub(r"AIza[\w-]+", "[REDACTED]", value)
    value = re.sub(r"(?i)(api[_-]?key|key|authorization)(\s*[=:]\s*)[^\s&,;]+", r"\1\2[REDACTED]", value)
    value = re.sub(r"data:image/[^\s]+", "[IMAGE REDACTED]", value)
    return " ".join(value.split())[:2000]


def configure_logging(settings):
    """Add owned sinks; preserve handlers installed by an embedding application."""
    try:
        logger.remove(0)  # Replace only Loguru's default stderr handler.
    except ValueError:
        pass
    options = dict(level=settings.log_level, diagnose=False, backtrace=False)
    handlers = [logger.add(
        sys.stderr,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS ZZ} | {level} | {message} | {extra}",
        **options,
    )]
    if settings.log_file is not None:
        try:
            settings.log_file.parent.mkdir(parents=True, exist_ok=True)
            handlers.append(logger.add(
                settings.log_file, serialize=True, rotation="10 MB", retention="7 days",
                encoding="utf-8", **options,
            ))
        except Exception:
            remove_handlers(handlers)
            raise
    return handlers


def remove_handlers(handlers):
    for handler in handlers:
        logger.remove(handler)


class RequestLoggingMiddleware:
    """Propagate request correlation into threadpool model calls."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        started = perf_counter()
        status = 500

        async def correlated_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message = dict(message)
                message["headers"] = [*message.get("headers", []), (b"x-request-id", request_id.encode())]
            await send(message)

        with logger.contextualize(request_id=request_id):
            try:
                await self.app(scope, receive, correlated_send)
            except Exception as exc:
                # Never log raw exception values: they can contain input payloads.
                logger.bind(event="http.error", exception_type=type(exc).__name__).error("Unhandled request error")
                raise
            finally:
                route = scope.get("route")
                logger.bind(
                    event="http.complete", method=scope["method"],
                    route=getattr(route, "path", "<unmatched>"), status_code=status,
                    duration_ms=round((perf_counter() - started) * 1000, 2),
                ).log("WARNING" if status >= 400 else "INFO", "HTTP request completed")
