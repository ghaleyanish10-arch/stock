"""FastAPI application entrypoint.

Run with:
    python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.analytics import routes as analytics_routes
from app.analytics import chart as chart_routes
from app.analytics import visualize as visualize_routes
from app.analytics.quarterly import routes as quarterly_routes
from app.ai import routes as ai_routes
from app.fundamentals import routes as fundamentals_routes
from app.realtime import routes as realtime_routes
from app.realtime.service import start_realtime_service, stop_realtime_service
from app.reference import company as company_routes
from app.api.responses import fail, nepse_error_response, ok
from app.api.routes import router, service
from app.archive import routes as archive_routes
from app.archive.service import ArchiveService
from app.auth import routes as auth_routes
from app.config import settings
from app.db.session import init_db
from app.jobs.scheduler import job_loop
from app.nepse.exceptions import NepseServiceError
from app.nepse.registry import close_adapter, get_adapter, start_adapter
from app.reference import routes as reference_routes
from app.portfolio import routes as portfolio_routes
from app.watchlist import routes as watchlist_routes
from app.alerts import routes as alerts_routes
from app.calculator import routes as calculator_routes
from app.news import routes as news_routes

logger = logging.getLogger(__name__)

FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Own process-lifetime resources: database, NEPSE client, scheduler."""
    # Refuse to start a misconfigured production deploy rather than serving
    # with a publicly known JWT signing key.
    problems = settings.validate_runtime()
    if problems:
        for problem in problems:
            logger.error("configuration problem: %s", problem)
        raise RuntimeError("Refusing to start: " + "; ".join(problems))

    init_db()
    await start_adapter()
    await service.start()
    await start_realtime_service()

    # Reuses the shared adapter (and therefore the shared rate limiter) rather
    # than opening a second upstream session.
    archive = ArchiveService(get_adapter())
    scheduler = asyncio.create_task(job_loop(archive), name="post-close-snapshot")
    try:
        yield
    finally:
        scheduler.cancel()
        try:
            await scheduler
        except asyncio.CancelledError:
            pass
        await stop_realtime_service()
        await service.close()
        await close_adapter()


app = FastAPI(
    title="Smart Analytics - NEPSE Data Service",
    version="2.0.0",
    description=(
        "Market data, historical archive, technical analytics and reference "
        "data for the Nepal Stock Exchange.\n\n"
        "Every value carries a provenance status so a missing number is never "
        "confused with a zero - see `app.core.provenance`."
    ),
    lifespan=lifespan,
)

# Allow a separately-hosted frontend dev server (vite on :5174) to call the
# API directly; production serving happens from this same origin below.
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        # Content Security Policy - restrictive but allows inline scripts/styles for React
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self' data:; "
            "connect-src 'self' ws: wss:; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        # Other security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        # HSTS - only in production
        if not settings.debug:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
        return response

class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple rate limiting middleware."""
    def __init__(self, app, requests_per_minute: int = 60):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.requests: dict[str, list[float]] = {}
    
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/api/"):
            # Extract client IP
            client_ip = request.client.host if request.client else "unknown"
            # In production, check X-Forwarded-For header
            forwarded_for = request.headers.get("X-Forwarded-For")
            if forwarded_for:
                client_ip = forwarded_for.split(",")[0].strip()
            
            now = time.time()
            minute_ago = now - 60
            
            if client_ip not in self.requests:
                self.requests[client_ip] = []
            
            # Clean old entries
            self.requests[client_ip] = [t for t in self.requests[client_ip] if t > minute_ago]
            
            if len(self.requests[client_ip]) >= self.requests_per_minute:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded. Try again later."},
                    headers={"Retry-After": "60"}
                )
            
            self.requests[client_ip].append(now)
        
        return await call_next(request)

# Allow a separately-hosted frontend dev server (vite on :5174) to call the
# API directly; production serving happens from this same origin below.
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(SecurityHeadersMiddleware)
if not settings.debug:
    app.add_middleware(RateLimitMiddleware, requests_per_minute=60)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5174", "http://127.0.0.1:5174"],
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(auth_routes.router)
app.include_router(archive_routes.router)
app.include_router(analytics_routes.router)
app.include_router(visualize_routes.router)
app.include_router(chart_routes.router)
app.include_router(company_routes.router)
app.include_router(reference_routes.router)
app.include_router(portfolio_routes.router)
app.include_router(watchlist_routes.router)
app.include_router(alerts_routes.router)
app.include_router(calculator_routes.router)
app.include_router(news_routes.router)
app.include_router(quarterly_routes.router)
app.include_router(ai_routes.router)
app.include_router(realtime_routes.router)
app.include_router(fundamentals_routes.router)


@app.get("/", include_in_schema=False)
async def root():
    """Serve the built React dashboard when present, else a JSON pointer."""
    index_html = FRONTEND_DIST / "index.html"
    if index_html.exists():
        return FileResponse(index_html)
    return ok({
        "service": "Smart Analytics",
        "docs": "/docs",
        "health": "/api/nepse/health",
        "coverage": "/api/archive/coverage",
        "example": "/api/nepse/stocks/NABIL",
    })


if FRONTEND_DIST.exists():
    # Serve the built React app's assets (js/css) from the same origin.
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIST / "assets"),
        name="frontend-assets",
    )

    # SPA fallback: any non-/api GET that isn't a static asset returns index.html
    # so client-side routing works on refresh. Unknown /api/* routes remain
    # as JSON 404 (handled by the routers' 404 responses).
    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        if full_path.startswith("api/"):
            # Let the API routers handle 404s for unknown endpoints.
            return JSONResponse(
                status_code=404,
                content={"detail": "Not found"},
            )
        index_html = FRONTEND_DIST / "index.html"
        if index_html.exists():
            return FileResponse(index_html)
        return ok({
            "service": "Smart Analytics",
            "docs": "/docs",
            "health": "/api/nepse/health",
            "coverage": "/api/archive/coverage",
            "example": "/api/nepse/stocks/NABIL",
        })


@app.exception_handler(NepseServiceError)
async def nepse_error_handler(_: Request, exc: NepseServiceError) -> JSONResponse:
    """Safety net: any NEPSE error escaping a route becomes a clean envelope."""
    return nepse_error_response(exc)


@app.exception_handler(Exception)
async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    """Last-resort handler: no stack traces ever reach the frontend."""
    logger.exception("Unhandled error: %r", exc)
    return JSONResponse(
        status_code=500,
        content=fail("INTERNAL_ERROR", "An unexpected error occurred"),
    )


if __name__ == "__main__":
    # Allows `python -m app.main` as an alternative to the uvicorn command.
    # Host/port come from NEPSE_HOST / NEPSE_PORT (see .env.example).
    import os

    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=os.getenv("NEPSE_HOST", "127.0.0.1"),
        port=int(os.getenv("NEPSE_PORT", "8000")),
    )
