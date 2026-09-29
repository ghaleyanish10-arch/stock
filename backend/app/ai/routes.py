"""AI API routes."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.auth.deps import CurrentUser, DbSession
from app.ai.service import (
    AIService,
    FakeAIClient,
    get_ai_settings,
    GroundingContext,
    create_ai_client,
)

router = APIRouter(prefix="/api/ai", tags=["ai"])

# Global AI service instance (reused across requests)
_ai_service: Optional[AIService] = None


def get_ai_service() -> AIService:
    global _ai_service
    if _ai_service is None:
        _ai_service = AIService()
    return _ai_service


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    symbols: list[str] = Field(default_factory=list)
    data_sources: list[str] = Field(default_factory=list)
    privacy_consent: bool = False


class AskResponse(BaseModel):
    answer: str
    grounded: bool
    rate_limit_remaining: int


@router.post("/ask", summary="Ask a grounded question")
async def ask(
    request: AskRequest,
    session: DbSession,
    user: CurrentUser,
    ai_service: AIService = Depends(get_ai_service),
) -> AskResponse:
    """Ask a question and get a grounded answer based on NEPSE data."""
    grounding = GroundingContext(
        symbols=[s.upper() for s in request.symbols],
        data_sources=request.data_sources,
    )

    answer = await ai_service.ask(
        user_id=user.id,
        question=request.question,
        grounding=grounding,
        privacy_consent=request.privacy_consent,
    )

    return AskResponse(
        answer=answer,
        grounded=True,
        rate_limit_remaining=19,  # TODO: expose from rate limiter
    )


@router.post("/stream", summary="Stream a grounded answer")
async def stream_ask(
    request: AskRequest,
    session: DbSession,
    user: CurrentUser,
    ai_service: AIService = Depends(get_ai_service),
) -> StreamingResponse:
    """Stream a grounded answer token by token."""
    grounding = GroundingContext(
        symbols=[s.upper() for s in request.symbols],
        data_sources=request.data_sources,
    )

    async def generate():
        async for chunk in ai_service.stream_ask(
            user_id=user.id,
            question=request.question,
            grounding=grounding,
            privacy_consent=request.privacy_consent,
        ):
            yield f"data: {json.dumps({'chunk': chunk})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/status", summary="Get AI service status")
async def status(
    user: CurrentUser,
    ai_service: AIService = Depends(get_ai_service),
) -> dict[str, Any]:
    """Get AI service configuration status (for UI)."""
    settings = get_ai_settings()
    return {
        "configured": settings.provider != "fake" and bool(settings.api_key),
        "provider": settings.provider,
        "model": settings.model,
        "rate_limit_per_minute": 20,
        "daily_limit": 50,
        "privacy_consent_required": True,
    }


@router.get("/status/public", summary="Get AI service status (public)")
async def status_public(
    ai_service: AIService = Depends(get_ai_service),
) -> dict[str, Any]:
    """Get AI service configuration status (public, no auth required)."""
    settings = get_ai_settings()
    return {
        "configured": settings.provider != "fake" and bool(settings.api_key),
        "provider": settings.provider,
        "model": settings.model,
        "rate_limit_per_minute": 20,
        "daily_limit": 50,
        "privacy_consent_required": True,
    }


@router.post("/test", summary="Test AI with a simple question (dev only)")
async def test_ai(
    request: AskRequest,
    user: CurrentUser,
    ai_service: AIService = Depends(get_ai_service),
) -> dict[str, Any]:
    """Test endpoint for development."""
    if not user.is_admin:
        raise HTTPException(403, "Admin only")
    grounding = GroundingContext(symbols=[], data_sources=[])
    answer = await ai_service.ask(
        user_id=user.id,
        question=request.question,
        grounding=grounding,
        privacy_consent=True,
    )
    return {"question": request.question, "answer": answer}


import json