"""Authentication endpoints: login, verify-totp, logout, refresh."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.services.auth_service import (
    authenticate,
    authenticate_totp,
    create_token,
    verify_token,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Request / Response models ────────────────────────────────────────────────


class LoginRequest(BaseModel):
    username: str
    password: str


class TOTPRequest(BaseModel):
    username: str
    code: str


class AuthResponse(BaseModel):
    model_config = {"populate_by_name": True}

    token: str
    user: dict
    totp_required: bool = Field(default=False, alias="totpRequired")


class TokenRefreshResponse(BaseModel):
    token: str


# ── Dependency: extract current user from Authorization header ───────────────


def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    """Dependency that extracts and validates JWT from Authorization header."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    token = authorization.split(" ", 1)[1]
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/auth/login", response_model=AuthResponse)
async def login(req: LoginRequest):
    """Step 1: Verify username/password. If TOTP enabled, returns totpRequired=True."""
    user = authenticate(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if user.get("totp_enabled"):
        # Don't issue full token yet — require TOTP step
        temp_token = create_token(req.username, role="totp_pending")
        return AuthResponse(
            token=temp_token,
            user={"username": user["username"], "role": user["role"]},
            totpRequired=True,
        )

    # No TOTP — issue full token
    token = create_token(req.username, role=user["role"])
    logger.info(f"User {req.username} logged in (no TOTP)")
    return AuthResponse(
        token=token,
        user={"username": user["username"], "role": user["role"]},
        totpRequired=False,
    )


@router.post("/auth/verify-totp", response_model=AuthResponse)
async def verify_totp_endpoint(req: TOTPRequest):
    """Step 2: Verify TOTP code and issue full JWT."""
    if not authenticate_totp(req.username, req.code):
        raise HTTPException(status_code=401, detail="Invalid TOTP code")

    token = create_token(req.username)
    logger.info(f"User {req.username} passed TOTP verification")
    return AuthResponse(
        token=token,
        user={"username": req.username, "role": "admin"},
        totpRequired=False,
    )


@router.post("/auth/logout")
async def logout(user: dict = Depends(get_current_user)):
    """Logout — client should discard the token."""
    logger.info(f"User {user.get('sub')} logged out")
    return {"status": "logged_out"}


@router.post("/auth/refresh", response_model=TokenRefreshResponse)
async def refresh(user: dict = Depends(get_current_user)):
    """Refresh JWT token."""
    new_token = create_token(user["sub"], role=user.get("role", "admin"))
    return TokenRefreshResponse(token=new_token)
