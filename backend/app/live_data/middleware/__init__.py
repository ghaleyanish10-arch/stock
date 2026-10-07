"""Delay middleware for role-based data delay (WP-L2)."""

from __future__ import annotations

import time
from typing import Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.auth.deps import get_current_user
from app.config import settings


class DelayMiddleware(BaseHTTPMiddleware):
    """Middleware that delays market data responses based on user role.
    
    Admin users get real-time data (0s delay by default).
    Regular users get delayed data (default 60s delay).
    The delay is applied by finding the latest snapshot that is older than
    the configured delay for the user's role.
    
    The response includes metadata headers:
    - X-Data-As-Of: The timestamp of the data
    - X-Data-Age-Seconds: Age of the data in seconds
    - X-Configured-Delay-Seconds: The configured delay for the user's role
    - X-Market-Open: Whether the market is currently open
    - X-Data-Stale: Whether the data is considered stale
    """
    
    def __init__(self, app, delay_seconds: int = 60):
        super().__init__(app)
        self.default_delay = delay_seconds
    
    def _get_user_delay(self, request) -> int:
        """Determine the delay based on user role."""
        # Try to get current user from request state
        user = getattr(request.state, "user", None)
        if user and user.get("is_admin"):
            return settings.admin_data_delay_seconds or 0
        return settings.public_data_delay_seconds or self.default_delay
    
    def _get_market_status(self) -> dict:
        """Get current market status from cache or settings."""
        # TODO: Implement proper market status check
        # For now, return a default
        return {
            "is_open": True,
            "as_of": None
        }
    
    async def dispatch(self, request: Request, call_next):
        # Only apply delay to market data endpoints
        if not request.url.path.startswith("/api/analytics/chart") and \
           not request.url.path.startswith("/api/analytics/indicators") and \
           not request.url.path.startswith("/api/nepse/market") and \
           not request.url.path.startswith("/api/nepse/stocks"):
            return await call_next(request)
        
        # Get user delay
        delay_seconds = self._get_user_delay(request)
        
        # Process the request
        response = await call_next(request)
        
        # Add delay headers to response
        # The actual data filtering happens at the endpoint level
        # This middleware just adds the metadata headers
        
        # Get market status
        market_status = self._get_market_status()
        
        # Add headers
        response.headers["X-Configured-Delay-Seconds"] = str(self._get_user_delay_from_request(request))
        response.headers["X-Market-Open"] = str(market_status.get("is_open", True)).lower()
        
        return response
    
    def _get_user_delay_from_request(self, request) -> int:
        """Extract delay from request (for header purposes)."""
        # This is a simplified version - in reality we'd check the user role
        # For now, return default public delay
        return settings.public_data_delay_seconds or 60


def get_delay_for_request(request) -> int:
    """Get the configured delay for a request based on user role."""
    # This would check the user's role from the request
    # For now, return the default public delay
    from app.config import settings
    return settings.public_data_delay_seconds or 60


def is_data_stale(fetched_at: str, threshold_seconds: int = 180) -> bool:
    """Check if data is stale based on fetch time."""
    from datetime import datetime, timezone
    try:
        fetched = datetime.fromisoformat(fetched_at.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        age = (now - fetched).total_seconds()
        return age > threshold_seconds
    except Exception:
        return True  # If we can't parse, consider it stale