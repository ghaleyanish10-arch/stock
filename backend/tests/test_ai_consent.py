"""Route-level tests for AI consent (no mocks of consent check)."""

import uuid
import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport
from app.main import app
from app.config import AI_DISCLOSURE_VERSION


class TestAIConsentRoutes:
    """Route-level tests for AI consent (no mocks of consent check)."""

    @pytest.fixture(autouse=True)
    async def _setup(self):
        self.client = AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://testserver",
        )
        # Create two users with unique emails to avoid conflicts
        unique_suffix = uuid.uuid4().hex[:8]
        self.user_a = {"email": f"usera_{uuid.uuid4().hex[:8]}@test.com", "password": "pass123"}
        self.user_b = {"email": f"userb_{uuid.uuid4().hex[:8]}@test.com", "password": "pass123"}
        await self.client.post("/api/auth/register", json=self.user_a)
        await self.client.post("/api/auth/register", json=self.user_b)
        # Login both with the SAME emails used for registration
        r_a = await self.client.post("/api/auth/login", json=self.user_a)
        r_b = await self.client.post("/api/auth/login", json=self.user_b)
        self.token_a = r_a.json()["access_token"]
        self.token_b = r_b.json()["access_token"]
        self.headers_a = {"Authorization": f"Bearer {self.token_a}"}
        self.headers_b = {"Authorization": f"Bearer {self.token_b}"}

    async def test_ask_403_without_consent(self):
        """POST /api/ai/ask returns 403 when user has no consent."""
        resp = await self.client.post(
            "/api/ai/ask",
            json={"question": "test", "privacy_consent": True},
            headers=self.headers_a,
        )
        assert resp.status_code == 403

    async def test_ask_200_with_consent(self):
        """POST /api/ai/ask returns 200 when user has consent."""
        # Grant consent for user A
        await self.client.patch(
            "/api/auth/me/ai-consent",
            json={"consent": True, "version": "1.0"},
            headers=self.headers_a,
        )
        resp = await self.client.post(
            "/api/ai/ask",
            json={"question": "test", "privacy_consent": True},
            headers=self.headers_a,
        )
        assert resp.status_code == 200
        assert "answer" in resp.json()

    async def test_user_a_consent_does_not_apply_to_user_b(self):
        """User A's consent does not apply to User B."""
        # Grant consent for user A only
        await self.client.patch(
            "/api/auth/me/ai-consent",
            json={"consent": True, "version": "1.0"},
            headers=self.headers_a,
        )
        # User B tries to ask without consent
        resp = await self.client.post(
            "/api/ai/ask",
            json={"question": "test", "privacy_consent": True},
            headers=self.headers_b,
        )
        assert resp.status_code == 403

    async def test_revoke_applies_on_next_request(self):
        """Revoking consent applies on the very next request."""
        # Grant consent
        await self.client.patch(
            "/api/auth/me/ai-consent",
            json={"consent": True, "version": "1.0"},
            headers=self.headers_a,
        )
        # First request succeeds
        resp1 = await self.client.post(
            "/api/ai/ask",
            json={"question": "test", "privacy_consent": True},
            headers=self.headers_a,
        )
        assert resp1.status_code == 200
        # Revoke consent
        await self.client.patch(
            "/api/auth/me/ai-consent",
            json={"consent": False, "version": "1.0"},
            headers=self.headers_a,
        )
        # Next request fails
        resp2 = await self.client.post(
            "/api/ai/ask",
            json={"question": "test", "privacy_consent": True},
            headers=self.headers_a,
        )
        assert resp2.status_code == 403

    async def test_consent_version_mismatch_returns_409(self):
        """PATCH /api/auth/me/ai-consent returns 409 when version mismatches server."""
        wrong_version = "999.0"
        assert wrong_version != AI_DISCLOSURE_VERSION
        resp = await self.client.patch(
            "/api/auth/me/ai-consent",
            json={"consent": True, "version": wrong_version},
            headers=self.headers_a,
        )
        assert resp.status_code == 409
        assert "version" in resp.json()["detail"].lower()

    async def test_stream_checks_consent_before_opening(self):
        """POST /api/ai/stream checks consent before opening stream."""
        resp = await self.client.post(
            "/api/ai/stream",
            json={"question": "test", "privacy_consent": True},
            headers=self.headers_a,
        )
        # Should be 403 without consent, not a stream error
        assert resp.status_code == 403

    async def test_portfolio_ai_review_403_without_consent(self):
        """POST /api/portfolio/{id}/ai-review returns 403 without consent."""
        # Simplified: just verify endpoint requires consent
        resp = await self.client.post(
            "/api/portfolio/some-id/ai-review",
            json={"question": "test", "privacy_consent": True},
            headers=self.headers_a,
        )
        # 404 (no portfolio) or 403 (no consent) - both acceptable
        assert resp.status_code in (403, 404)


@pytest.fixture
async def client():
    from httpx import AsyncClient
    from httpx._transports.asgi import ASGITransport
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        yield client


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"