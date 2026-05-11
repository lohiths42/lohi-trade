"""Kill switch endpoints."""

from fastapi import APIRouter, HTTPException

from app.services.redis_consumer import get_kill_switch_status, publish_command

router = APIRouter()


@router.get("/kill-switch")
def get_kill_switch():
    return {"active": get_kill_switch_status()}


@router.post("/kill-switch/toggle")
def toggle_kill_switch():
    current = get_kill_switch_status()
    new_state = not current
    result = publish_command("toggle_kill_switch", {"active": new_state})
    if result is None:
        # Redis unavailable — still return the toggled state for UI responsiveness
        return {"active": new_state, "message_id": "offline"}
    return {"active": new_state, "message_id": result}
