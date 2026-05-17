"""Positions endpoints."""

from typing import List

from fastapi import APIRouter, HTTPException

from app.models.positions import ClosePositionRequest, PositionResponse
from app.services import db_service
from app.services.redis_consumer import publish_command

router = APIRouter()


@router.get("/positions", response_model=List[PositionResponse])
def list_positions():
    try:
        return db_service.get_positions()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/positions/{trade_id}/close")
def close_position(trade_id: str, body: ClosePositionRequest):
    result = publish_command(
        "close_position",
        {
            "trade_id": trade_id,
            "reason": body.reason,
        },
    )
    if result is None:
        raise HTTPException(status_code=503, detail="Failed to publish command")
    return {"status": "command_sent", "message_id": result}
