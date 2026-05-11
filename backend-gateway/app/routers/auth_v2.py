"""Multi-user authentication endpoints (v2): register, login, social login, refresh, logout.

Provides JWT-based auth with Bearer token middleware for RLS user isolation.
All auth events are logged for security audit (Req 29.7).
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Request
from pydantic import BaseModel, Field

from app.services.account_service import (
    AccountService,
    verify_access_token,
)


def _verify_any_token(token: str) -> Optional[dict]:
    """Verify a JWT against BOTH auth schemes (v2 multi-user, v1 OSS single-user).

    Returns the decoded payload (with at least `sub`) or None if invalid.
    The OSS single-user build only uses v1 tokens; the Pro multi-user build
    uses v2. This bridge lets both coexist in one binary so the frontend
    doesn't need to know which auth scheme is active.
    """
    # v2 first (superset — includes role, email, refresh support)
    payload = verify_access_token(token)
    if payload and "sub" in payload:
        return payload
    # v1 fallback — OSS single-user tokens from /api/auth/login
    try:
        from app.services.auth_service import verify_token as v1_verify

        v1 = v1_verify(token)
        if v1 and "sub" in v1:
            return v1
    except Exception:
        pass
    return None

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Request / Response models ────────────────────────────────────────────────


class RegisterRequest(BaseModel):
    email: str = Field(..., description="User email address")
    password: str = Field(..., description="Password (min 8 chars, 1 upper, 1 lower, 1 digit, 1 special)")
    phone: str = Field(..., description="Indian mobile number (10 digits)")
    name: str = Field(..., description="Full name")


class LoginRequest(BaseModel):
    email: str
    password: str


class GoogleLoginRequest(BaseModel):
    id_token: str = Field(..., description="Google ID token from client-side auth")


class AppleLoginRequest(BaseModel):
    auth_code: str = Field(..., description="Apple authorization code")
    user_name: Optional[str] = Field(None, description="User name (provided on first Apple sign-in)")


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RegisterResponse(BaseModel):
    user_id: str
    email: str
    message: str = "Registration successful. Please verify your email."


class MessageResponse(BaseModel):
    message: str


# ── JWT auth dependency ──────────────────────────────────────────────────────


def get_current_user_id(authorization: Optional[str] = Header(None)) -> str:
    """FastAPI dependency: extract and verify JWT Bearer token.

    Returns the user_id (sub claim) from the token. Raises 401 if missing,
    malformed, or expired. This dependency can be injected into any router
    endpoint that requires authentication.

    Sets request.state.user_id for downstream RLS usage when used with
    the JWT middleware.
    """
    if not authorization or not authorization.startswith("Bearer "):
        logger.warning("Auth failed: missing or malformed Authorization header")
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header",
        )

    token = authorization.split(" ", 1)[1]
    payload = _verify_any_token(token)
    if payload is None:
        logger.warning("Auth failed: invalid or expired access token")
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired access token",
        )

    return payload["sub"]


def get_current_user_payload(authorization: Optional[str] = Header(None)) -> dict:
    """FastAPI dependency: returns the full JWT payload (sub, email, role, etc.).

    Useful when endpoints need role or email in addition to user_id.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header",
        )

    token = authorization.split(" ", 1)[1]
    payload = _verify_any_token(token)
    if payload is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired access token",
        )

    return payload


# ── AccountService dependency ────────────────────────────────────────────────

# The AccountService requires an asyncpg pool. In production this is set up
# at app startup. For now we use a module-level holder that main.py populates.
_account_service: Optional[AccountService] = None


def set_account_service(svc: AccountService) -> None:
    """Called at app startup to inject the AccountService instance."""
    global _account_service
    _account_service = svc


def get_account_service() -> AccountService:
    """FastAPI dependency to retrieve the AccountService."""
    if _account_service is None:
        raise HTTPException(
            status_code=503,
            detail="Account service not initialized",
        )
    return _account_service


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/auth/register", response_model=RegisterResponse, status_code=201)
async def register(
    req: RegisterRequest,
    svc: AccountService = Depends(get_account_service),
):
    """Register a new user with email/password. Sends OTP for email verification."""
    try:
        result = await svc.register_email(req.email, req.password, req.phone, req.name)
        user = result["user"]
        logger.info(
            "AUTH_EVENT register_success email=%s user_id=%s",
            req.email, user.id,
        )
        return RegisterResponse(
            user_id=user.id,
            email=user.email,
        )
    except ValueError as exc:
        logger.warning("AUTH_EVENT register_failed email=%s reason=%s", req.email, str(exc))
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/auth/login", response_model=TokenResponse)
async def login(
    req: LoginRequest,
    svc: AccountService = Depends(get_account_service),
):
    """Login with email/password. Returns access + refresh tokens."""
    try:
        tokens = await svc.login_email(req.email, req.password)
        logger.info("AUTH_EVENT login_success email=%s", req.email)
        return TokenResponse(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
        )
    except ValueError as exc:
        logger.warning("AUTH_EVENT login_failed email=%s reason=%s", req.email, str(exc))
        raise HTTPException(status_code=401, detail=str(exc))


@router.post("/auth/google", response_model=TokenResponse)
async def login_google(
    req: GoogleLoginRequest,
    svc: AccountService = Depends(get_account_service),
):
    """Login or register via Google OAuth. Returns access + refresh tokens."""
    try:
        tokens = await svc.login_google(req.id_token)
        logger.info("AUTH_EVENT google_login_success")
        return TokenResponse(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
        )
    except ValueError as exc:
        logger.warning("AUTH_EVENT google_login_failed reason=%s", str(exc))
        raise HTTPException(status_code=401, detail=str(exc))


@router.post("/auth/apple", response_model=TokenResponse)
async def login_apple(
    req: AppleLoginRequest,
    svc: AccountService = Depends(get_account_service),
):
    """Login or register via Apple Sign-In. Returns access + refresh tokens."""
    try:
        tokens = await svc.login_apple(req.auth_code, user_name=req.user_name)
        logger.info("AUTH_EVENT apple_login_success")
        return TokenResponse(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
        )
    except ValueError as exc:
        logger.warning("AUTH_EVENT apple_login_failed reason=%s", str(exc))
        raise HTTPException(status_code=401, detail=str(exc))


@router.post("/auth/refresh", response_model=TokenResponse)
async def refresh(
    req: RefreshRequest,
    svc: AccountService = Depends(get_account_service),
):
    """Refresh access token using a valid refresh token (token rotation)."""
    try:
        tokens = await svc.refresh_token(req.refresh_token)
        logger.info("AUTH_EVENT token_refresh_success")
        return TokenResponse(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
        )
    except ValueError as exc:
        logger.warning("AUTH_EVENT token_refresh_failed reason=%s", str(exc))
        raise HTTPException(status_code=401, detail=str(exc))


@router.post("/auth/logout", response_model=MessageResponse)
async def logout(
    user_id: str = Depends(get_current_user_id),
):
    """Logout — invalidates the session on the client side.

    The client should discard both access and refresh tokens.
    In a production system, the refresh token would also be revoked server-side.
    """
    logger.info("AUTH_EVENT logout user_id=%s", user_id)
    return MessageResponse(message="Logged out successfully")
