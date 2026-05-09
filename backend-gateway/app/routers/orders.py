"""Orders endpoints."""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional

from app.models.orders import OrderResponse
from app.services import db_service
from app.services.redis_consumer import publish_command

router = APIRouter()


@router.get("/orders", response_model=List[OrderResponse])
def list_orders(
    status: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    try:
        return db_service.get_orders(status=status, symbol=symbol, limit=limit, offset=offset)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/orders/{order_id}/cancel")
def cancel_order(order_id: str):
    result = publish_command("cancel_order", {"order_id": order_id})
    if result is None:
        raise HTTPException(status_code=503, detail="Failed to publish command")
    return {"status": "command_sent", "message_id": result}
