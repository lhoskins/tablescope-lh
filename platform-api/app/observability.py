"""Prometheus metrics + Sentry initialization."""

from __future__ import annotations

import hmac
import logging
import time

from fastapi import FastAPI
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    Counter,
    Histogram,
    generate_latest,
)
from starlette.requests import Request
from starlette.responses import Response

from app.config import get_settings

logger = logging.getLogger(__name__)

request_counter = Counter(
    "platform_api_requests_total",
    "Total number of HTTP requests processed.",
    labelnames=("method", "path", "status"),
)
request_latency = Histogram(
    "platform_api_request_latency_seconds",
    "Latency of HTTP requests in seconds.",
    labelnames=("method", "path"),
)


def setup_sentry() -> None:
    settings = get_settings()
    if not settings.sentry_dsn:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.environment,
            integrations=[StarletteIntegration(), FastApiIntegration()],
            traces_sample_rate=0.05,
        )
        logger.info("Sentry initialized")
    except Exception as exc:
        logger.warning("Sentry initialization failed: %s", exc)


def mount_metrics(app: FastAPI) -> None:
    settings = get_settings()
    if not settings.prometheus_enabled:
        return

    @app.middleware("http")
    async def _record_metrics(request: Request, call_next):
        method = request.method
        start = time.monotonic()
        response = await call_next(request)
        elapsed = time.monotonic() - start
        # Label by the matched ROUTE TEMPLATE (e.g. "/api/projects/{id}"),
        # not the raw resolved path -- the raw path embeds tenant/project/
        # user IDs straight into label values (TS-ISO-018), which both
        # leaks them to anyone who can read /metrics and creates unbounded
        # label cardinality (a new label per distinct ID ever requested).
        # The route is only set on request.scope AFTER routing, i.e. after
        # call_next() above -- so timing must be measured manually here
        # instead of via the usual `with histogram.time():` wrapper.
        route = request.scope.get("route")
        path = getattr(route, "path", None) or "unmatched"
        request_latency.labels(method=method, path=path).observe(elapsed)
        request_counter.labels(method=method, path=path, status=str(response.status_code)).inc()
        return response

    @app.get("/metrics", include_in_schema=False)
    async def metrics(request: Request) -> Response:
        settings = get_settings()
        if settings.metrics_access_token:
            provided = request.headers.get("X-Metrics-Token", "")
            if not hmac.compare_digest(provided, settings.metrics_access_token):
                return Response(status_code=404)
        return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
