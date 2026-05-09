"""Chatbot API router — conversational AI assistant endpoints.

Provides endpoints for sending messages, retrieving conversation history,
and clearing chat sessions. All endpoints require JWT authentication.

Prefix: /api/v2/chatbot
Requirements: 18.1, 18.4
"""

import base64
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.routers.auth_v2 import get_current_user_id
from app.services.chatbot_service import ChatbotService

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Request / Response models ────────────────────────────────────────────────


class ChatMessageRequest(BaseModel):
    message: str = Field(..., description="User message to the chatbot")


class ChatMessageResponse(BaseModel):
    text: str
    chart_data: Optional[str] = Field(None, description="Base64-encoded chart image if present")
    chart_type: Optional[str] = None
    sources: list[str] = []
    response_time_ms: int = 0


class ChatHistoryMessage(BaseModel):
    role: str
    content: str
    timestamp: Optional[str] = None


class ChatHistoryResponse(BaseModel):
    messages: list[ChatHistoryMessage]
    count: int


class ClearSessionResponse(BaseModel):
    success: bool
    message: str


# ── Service dependency ───────────────────────────────────────────────────────

_chatbot_service: Optional[ChatbotService] = None


def set_chatbot_service(svc: ChatbotService) -> None:
    """Called at app startup to inject the ChatbotService instance."""
    global _chatbot_service
    _chatbot_service = svc


def get_chatbot_service() -> ChatbotService:
    """FastAPI dependency to retrieve the ChatbotService."""
    if _chatbot_service is None:
        raise HTTPException(
            status_code=503,
            detail="Chatbot service not initialized",
        )
    return _chatbot_service


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/chatbot/message", response_model=ChatMessageResponse)
async def send_message(
    req: ChatMessageRequest,
    user_id: str = Depends(get_current_user_id),
    svc: ChatbotService = Depends(get_chatbot_service),
):
    """Send a message to the AI chatbot and receive a response.

    The chatbot uses RAG over the user's trading data to provide
    contextual answers. Supports English and Hinglish input.

    Requirements: 18.1, 18.4
    """
    try:
        response = await svc.chat(user_id, req.message)
        logger.info(
            "CHATBOT_EVENT message user=%s response_time_ms=%d",
            user_id, response.response_time_ms,
        )

        # Encode chart_data as base64 if present
        chart_b64 = None
        if response.chart_data:
            chart_b64 = base64.b64encode(response.chart_data).decode("utf-8")

        return ChatMessageResponse(
            text=response.text,
            chart_data=chart_b64,
            chart_type=response.chart_type,
            sources=response.sources,
            response_time_ms=response.response_time_ms,
        )
    except Exception:
        logger.exception("Chatbot message error for user %s", user_id)
        raise HTTPException(status_code=500, detail="Failed to process chatbot message")


@router.get("/chatbot/history", response_model=ChatHistoryResponse)
async def get_history(
    user_id: str = Depends(get_current_user_id),
    svc: ChatbotService = Depends(get_chatbot_service),
):
    """Retrieve conversation history for the authenticated user.

    Returns the current session's message history (up to 20 exchanges).

    Requirements: 18.4
    """
    try:
        history = await svc.get_history(user_id)
        messages = [
            ChatHistoryMessage(
                role=msg.get("role", "user"),
                content=msg.get("content", ""),
                timestamp=msg.get("timestamp"),
            )
            for msg in history
        ]
        return ChatHistoryResponse(messages=messages, count=len(messages))
    except Exception:
        logger.exception("Chatbot history error for user %s", user_id)
        raise HTTPException(status_code=500, detail="Failed to retrieve chat history")


@router.delete("/chatbot/session", response_model=ClearSessionResponse)
async def clear_session(
    user_id: str = Depends(get_current_user_id),
    svc: ChatbotService = Depends(get_chatbot_service),
):
    """Clear the authenticated user's chatbot conversation session.

    Requirements: 18.4
    """
    try:
        success = await svc.clear_session(user_id)
        if success:
            logger.info("CHATBOT_EVENT session_cleared user=%s", user_id)
            return ClearSessionResponse(
                success=True,
                message="Chat session cleared successfully",
            )
        else:
            return ClearSessionResponse(
                success=False,
                message="Failed to clear chat session. Redis may be unavailable.",
            )
    except Exception:
        logger.exception("Chatbot session clear error for user %s", user_id)
        raise HTTPException(status_code=500, detail="Failed to clear chat session")
