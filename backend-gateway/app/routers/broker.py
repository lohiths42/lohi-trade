"""Broker / DMAT account connection endpoints."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.auth_service import verify_token

logger = logging.getLogger(__name__)
router = APIRouter()


class BrokerCredentials(BaseModel):
    api_key: str = ""
    client_id: str = ""
    password: str = ""
    totp_secret: str = ""
    imei: str = ""  # Shoonya-specific


class BrokerConfig(BaseModel):
    shoonya: BrokerCredentials = BrokerCredentials()
    angelone: BrokerCredentials = BrokerCredentials()


class BrokerStatus(BaseModel):
    shoonya: dict
    angelone: dict


# In-memory store (in production, persist to encrypted file or vault)
_broker_config = BrokerConfig()


@router.get("/broker/status", response_model=BrokerStatus)
async def get_broker_status():
    """Get broker connection status (masked credentials)."""
    def mask(cred: BrokerCredentials) -> dict:
        return {
            "configured": bool(cred.api_key and cred.client_id),
            "api_key": f"{'*' * 8}{cred.api_key[-4:]}" if len(cred.api_key) > 4 else "",
            "client_id": cred.client_id,
            "has_password": bool(cred.password),
            "has_totp": bool(cred.totp_secret),
        }

    return BrokerStatus(
        shoonya=mask(_broker_config.shoonya),
        angelone=mask(_broker_config.angelone),
    )


@router.put("/broker/shoonya")
async def update_shoonya(creds: BrokerCredentials):
    """Update Shoonya broker credentials."""
    global _broker_config
    _broker_config.shoonya = creds
    logger.info("Shoonya credentials updated")
    return {"status": "updated", "broker": "shoonya"}


@router.put("/broker/angelone")
async def update_angelone(creds: BrokerCredentials):
    """Update Angel One broker credentials."""
    global _broker_config
    _broker_config.angelone = creds
    logger.info("Angel One credentials updated")
    return {"status": "updated", "broker": "angelone"}


@router.post("/broker/test/{broker_name}")
async def test_broker_connection(broker_name: str):
    """Test broker connection (simulated for paper trading mode)."""
    if broker_name not in ("shoonya", "angelone"):
        raise HTTPException(status_code=400, detail=f"Unknown broker: {broker_name}")

    creds = getattr(_broker_config, broker_name)
    if not creds.api_key or not creds.client_id:
        raise HTTPException(status_code=400, detail=f"{broker_name} credentials not configured")

    # In paper trading mode, we simulate a successful connection
    return {
        "broker": broker_name,
        "status": "connected",
        "message": f"Paper trading mode — {broker_name} connection simulated successfully",
    }
