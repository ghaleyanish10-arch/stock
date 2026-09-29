"""Tests that every service shares one NEPSE client.

The bug: `ArchiveService`, `ReferenceService` and `NepseService` each defaulted
to constructing their own `NepseClientAdapter`, and the post-close scheduler
added a fourth. Every adapter owns a private `nepse_data_api.Client` with its
own rate limiter, so one process was making several sessions' worth of upstream
pressure and only one of them was ever closed.
"""

from __future__ import annotations

import pytest

from app.nepse import registry
from app.nepse.client import NepseClientAdapter


@pytest.fixture(autouse=True)
def _clean_registry():
    registry.reset_adapter()
    yield
    registry.reset_adapter()


class TestSharedAdapter:
    def test_get_adapter_is_a_singleton(self):
        first = registry.get_adapter()
        second = registry.get_adapter()
        assert first is second
        assert isinstance(first, NepseClientAdapter)

    def test_reset_forces_a_new_instance(self):
        first = registry.get_adapter()
        registry.reset_adapter()
        assert registry.get_adapter() is not first

    def test_close_is_safe_when_never_created(self):
        import asyncio

        # Must not raise: shutdown can run before any request arrives.
        asyncio.run(registry.close_adapter())


class TestServicesShareTheAdapter:
    def test_routers_all_hold_one_adapter(self):
        """Legacy API, archive, analytics and reference must share one client.

        These module-level services are built at import time, so this compares
        them against each other rather than against a freshly created adapter.
        """
        from app.analytics import routes as analytics_routes
        from app.api import routes as legacy_routes
        from app.archive import routes as archive_routes
        from app.reference import routes as reference_routes

        clients = [
            legacy_routes.service._client,
            archive_routes._archive._client,
            analytics_routes._archive._client,
            reference_routes._reference._client,
        ]
        first = clients[0]
        for client in clients[1:]:
            assert client is first, (
                "a module built its own NEPSE adapter; the process would open "
                "several upstream sessions with independent rate limiters"
            )

    def test_default_constructed_service_uses_the_registry(self):
        """A service built without an explicit client still shares the adapter."""
        from app.nepse.service import NepseService

        shared = registry.get_adapter()
        assert NepseService()._client is shared

    def test_explicit_client_still_wins(self):
        """Tests pass their own fake, which must not be overridden."""
        from app.nepse.service import NepseService

        sentinel = object()
        assert NepseService(client=sentinel)._client is sentinel

    def test_no_module_constructs_an_adapter_directly(self):
        """Guard against a new module re-introducing a private adapter.

        The registry is the only place allowed to call the constructor.
        """
        from pathlib import Path

        import app

        app_dir = Path(app.__path__[0])
        offenders = []
        for path in app_dir.rglob("*.py"):
            if path.name == "registry.py":
                continue
            if "NepseClientAdapter()" in path.read_text(encoding="utf-8"):
                offenders.append(str(path.relative_to(app_dir.parent)))
        assert offenders == [], (
            f"these modules construct their own adapter: {offenders}"
        )


class TestAppBoot:
    def test_app_imports_and_exposes_every_area(self):
        from app.main import app

        # The OpenAPI schema is the reliable way to enumerate paths; this
        # FastAPI version stores included routers as opaque objects.
        paths = set(app.openapi()["paths"])
        for expected in (
            "/api/nepse/status",
            "/api/auth/login",
            "/api/archive/coverage",
            "/api/analytics/indicators/{symbol}",
            "/api/reference/securities",
        ):
            assert expected in paths, f"{expected} is not registered"
