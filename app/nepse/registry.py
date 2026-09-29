"""One shared NEPSE client for the whole process.

Why this exists: `ArchiveService`, `ReferenceService` and `NepseService` each
default to constructing their own `NepseClientAdapter`, and the post-close
scheduler added a fourth. Every adapter owns a private `nepse_data_api.Client`
session with its own rate limiter, so the app ended up making several
independent sessions' worth of upstream pressure from one process, and only one
of them was ever closed. This module makes the adapter a single shared
resource whose lifetime is owned by the FastAPI lifespan.

Tests can call `reset_adapter()` to drop the singleton between cases.
"""

from __future__ import annotations

import logging
import threading

from app.nepse.client import NepseClientAdapter

logger = logging.getLogger(__name__)

_adapter: NepseClientAdapter | None = None
_lock = threading.Lock()


def get_adapter() -> NepseClientAdapter:
    """Return the process-wide adapter, creating it on first use.

    Safe to call from module import time and from request handlers. The adapter
    starts its underlying client lazily on first request, so merely holding a
    reference does not open a socket.
    """
    global _adapter
    if _adapter is None:
        with _lock:
            if _adapter is None:
                _adapter = NepseClientAdapter()
                logger.info("shared NEPSE adapter created")
    return _adapter


async def start_adapter() -> NepseClientAdapter:
    """Open the shared session up front so health checks and the first request
    do not pay the handshake cost."""
    adapter = get_adapter()
    await adapter.start()
    return adapter


async def close_adapter() -> None:
    """Close and forget the shared adapter. Safe to call when never created."""
    global _adapter
    with _lock:
        adapter, _adapter = _adapter, None
    if adapter is None:
        return
    try:
        await adapter.close()
    except Exception:
        logger.exception("error while closing the shared NEPSE adapter")
    else:
        logger.info("shared NEPSE adapter closed")


def reset_adapter() -> None:
    """Drop the singleton without awaiting I/O. Test helper only."""
    global _adapter
    with _lock:
        _adapter = None
