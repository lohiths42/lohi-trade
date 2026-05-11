"""Verification API router — PAN, KYC, and DMAT endpoints.

All endpoints require authenticated user with TRADER or ADMIN role.
Prefix: /api/v2/verify

Requirements: 1-3 (all)
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.middleware.rbac import require_role
from app.routers.auth_v2 import get_current_user_id
from app.services.verification_service import (
    DMATService,
    DMATStatus,
    KYCDocuments,
    KYCService,
    KYCStatus,
    PANStatus,
    PANVerificationService,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Request / Response models ────────────────────────────────────────────────


class PANSubmitRequest(BaseModel):
    pan: str = Field(..., description="PAN number (10 alphanumeric characters)")


class PANStatusResponse(BaseModel):
    status: str
    pan_masked: Optional[str] = None
    holder_name: Optional[str] = None
    rejection_reason: Optional[str] = None
    verified_at: Optional[str] = None


class PANSubmitResponse(BaseModel):
    status: str
    pan_masked: Optional[str] = None
    holder_name: Optional[str] = None
    rejection_reason: Optional[str] = None
    message: str


class KYCStatusResponse(BaseModel):
    status: str
    verification_ref: Optional[str] = None
    rejection_reason: Optional[str] = None


class KYCSubmitResponse(BaseModel):
    status: str
    verification_ref: Optional[str] = None
    rejection_reason: Optional[str] = None
    queued_for_retry: bool = False
    message: str


class DMATLinkRequest(BaseModel):
    account_number: str = Field(..., description="DMAT account number (CDSL 16-digit or NSDL IN+14)")


class DMATLinkResponse(BaseModel):
    status: str
    dmat_id: Optional[str] = None
    depository: Optional[str] = None
    dp_name: Optional[str] = None
    rejection_reason: Optional[str] = None
    message: str


class DMATAccountItem(BaseModel):
    dmat_id: str
    depository: str
    dp_name: Optional[str] = None
    status: str
    linked_at: Optional[str] = None


class DMATListResponse(BaseModel):
    accounts: list[DMATAccountItem]
    count: int


class DMATUnlinkResponse(BaseModel):
    success: bool
    message: str


class MessageResponse(BaseModel):
    message: str


# ── Service dependencies ─────────────────────────────────────────────────────

_pan_service: Optional[PANVerificationService] = None
_kyc_service: Optional[KYCService] = None
_dmat_service: Optional[DMATService] = None


def set_verification_services(
    pan: PANVerificationService,
    kyc: KYCService,
    dmat: DMATService,
) -> None:
    """Called at app startup to inject verification service instances."""
    global _pan_service, _kyc_service, _dmat_service
    _pan_service = pan
    _kyc_service = kyc
    _dmat_service = dmat


def get_pan_service() -> PANVerificationService:
    if _pan_service is None:
        raise HTTPException(status_code=503, detail="PAN verification service not initialized")
    return _pan_service


def get_kyc_service() -> KYCService:
    if _kyc_service is None:
        raise HTTPException(status_code=503, detail="KYC verification service not initialized")
    return _kyc_service


def get_dmat_service() -> DMATService:
    if _dmat_service is None:
        raise HTTPException(status_code=503, detail="DMAT service not initialized")
    return _dmat_service


# ── PAN Endpoints ────────────────────────────────────────────────────────────


@router.post("/verify/pan", response_model=PANSubmitResponse)
async def submit_pan(
    req: PANSubmitRequest,
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    svc: PANVerificationService = Depends(get_pan_service),
):
    """Submit PAN for verification against NSDL/UTI API.

    Requirements: 1.1-1.7
    """
    try:
        result = await svc.verify_pan(user_id, req.pan)
        logger.info(
            "VERIFY_EVENT pan_submit user=%s status=%s",
            user_id, result.status.value,
        )
        return PANSubmitResponse(
            status=result.status.value,
            pan_masked=result.pan_masked,
            holder_name=result.holder_name,
            rejection_reason=result.rejection_reason,
            message="PAN verified successfully" if result.status == PANStatus.VERIFIED
            else f"PAN verification failed: {result.rejection_reason}",
        )
    except Exception as exc:
        logger.exception("PAN verification error for user %s", user_id)
        raise HTTPException(status_code=500, detail="PAN verification failed unexpectedly")


@router.get("/verify/pan/status", response_model=PANStatusResponse)
async def get_pan_status(
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    svc: PANVerificationService = Depends(get_pan_service),
):
    """Get current PAN verification status for the authenticated user.

    Requirements: 1.3
    """
    if svc.db_pool is None:
        return PANStatusResponse(status=PANStatus.PENDING.value)

    try:
        async with svc.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT status, pan_masked, holder_name, rejection_reason, verified_at
                   FROM pan_verifications WHERE user_id = $1
                   ORDER BY created_at DESC LIMIT 1""",
                user_id,
            )
        if row is None:
            return PANStatusResponse(status="NOT_SUBMITTED")
        return PANStatusResponse(
            status=row["status"],
            pan_masked=row["pan_masked"],
            holder_name=row["holder_name"],
            rejection_reason=row["rejection_reason"],
            verified_at=row["verified_at"].isoformat() if row["verified_at"] else None,
        )
    except Exception:
        logger.exception("Failed to fetch PAN status for user %s", user_id)
        raise HTTPException(status_code=500, detail="Failed to retrieve PAN status")


# ── KYC Endpoints ────────────────────────────────────────────────────────────


@router.post("/verify/kyc", response_model=KYCSubmitResponse)
async def submit_kyc(
    full_name: str = Form(...),
    date_of_birth: str = Form(...),
    address: str = Form(...),
    government_id_photo: UploadFile = File(...),
    aadhaar_number: Optional[str] = Form(None),
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    svc: KYCService = Depends(get_kyc_service),
):
    """Submit KYC documents for verification.

    Accepts multipart form data with government ID photo upload.
    Requires PAN verification to be completed first.

    Requirements: 2.1-2.10
    """
    try:
        photo_bytes = await government_id_photo.read()
        mime_type = government_id_photo.content_type or "image/jpeg"

        documents = KYCDocuments(
            full_name=full_name,
            date_of_birth=date_of_birth,
            address=address,
            government_id_photo=photo_bytes,
            government_id_mime_type=mime_type,
            aadhaar_number=aadhaar_number,
        )

        result = await svc.submit_kyc(user_id, documents)
        logger.info(
            "VERIFY_EVENT kyc_submit user=%s status=%s",
            user_id, result.status.value,
        )

        if result.status == KYCStatus.VERIFIED:
            message = "KYC verification completed successfully"
        elif result.status == KYCStatus.PENDING:
            message = "KYC submission received and is being processed"
        elif result.status == KYCStatus.NOT_STARTED:
            message = result.rejection_reason or "KYC cannot be initiated"
        else:
            message = f"KYC verification failed: {result.rejection_reason}"

        return KYCSubmitResponse(
            status=result.status.value,
            verification_ref=result.verification_ref,
            rejection_reason=result.rejection_reason,
            queued_for_retry=result.queued_for_retry,
            message=message,
        )
    except Exception as exc:
        logger.exception("KYC submission error for user %s", user_id)
        raise HTTPException(status_code=500, detail="KYC submission failed unexpectedly")


@router.get("/verify/kyc/status", response_model=KYCStatusResponse)
async def get_kyc_status(
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    svc: KYCService = Depends(get_kyc_service),
):
    """Get current KYC verification status for the authenticated user.

    Requirements: 2.5, 2.10
    """
    try:
        status = await svc.check_kyc_status(user_id)

        # Fetch additional details if available
        rejection_reason = None
        verification_ref = None
        if svc.db_pool is not None:
            async with svc.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """SELECT rejection_reason, verification_ref
                       FROM kyc_verifications WHERE user_id = $1
                       ORDER BY created_at DESC LIMIT 1""",
                    user_id,
                )
                if row:
                    rejection_reason = row["rejection_reason"]
                    verification_ref = row["verification_ref"]

        return KYCStatusResponse(
            status=status.value,
            verification_ref=verification_ref,
            rejection_reason=rejection_reason,
        )
    except Exception:
        logger.exception("Failed to fetch KYC status for user %s", user_id)
        raise HTTPException(status_code=500, detail="Failed to retrieve KYC status")


# ── DMAT Endpoints ───────────────────────────────────────────────────────────


@router.post("/verify/dmat", response_model=DMATLinkResponse)
async def link_dmat(
    req: DMATLinkRequest,
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    svc: DMATService = Depends(get_dmat_service),
):
    """Link a DMAT account (CDSL or NSDL).

    Requires KYC to be VERIFIED. Max 3 accounts per user.

    Requirements: 3.1-3.8
    """
    try:
        result = await svc.verify_dmat(user_id, req.account_number)
        logger.info(
            "VERIFY_EVENT dmat_link user=%s status=%s depository=%s",
            user_id, result.status.value, result.depository,
        )
        return DMATLinkResponse(
            status=result.status.value,
            dmat_id=result.dmat_id,
            depository=result.depository,
            dp_name=result.dp_name,
            rejection_reason=result.rejection_reason,
            message="DMAT account linked successfully" if result.status == DMATStatus.LINKED
            else f"DMAT linking failed: {result.rejection_reason}",
        )
    except Exception:
        logger.exception("DMAT linking error for user %s", user_id)
        raise HTTPException(status_code=500, detail="DMAT linking failed unexpectedly")


@router.delete("/verify/dmat/{dmat_id}", response_model=DMATUnlinkResponse)
async def unlink_dmat(
    dmat_id: str,
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    svc: DMATService = Depends(get_dmat_service),
):
    """Unlink a DMAT account. Fails if open positions exist.

    Requirements: 3.7
    """
    try:
        success = await svc.unlink_dmat(user_id, dmat_id)
        if success:
            logger.info("VERIFY_EVENT dmat_unlink user=%s dmat_id=%s", user_id, dmat_id)
            return DMATUnlinkResponse(
                success=True,
                message="DMAT account unlinked successfully",
            )
        else:
            return DMATUnlinkResponse(
                success=False,
                message="Cannot unlink DMAT account. Open positions may exist or account not found.",
            )
    except Exception:
        logger.exception("DMAT unlink error for user %s dmat_id=%s", user_id, dmat_id)
        raise HTTPException(status_code=500, detail="DMAT unlink failed unexpectedly")


@router.get("/verify/dmat/list", response_model=DMATListResponse)
async def list_dmat_accounts(
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    svc: DMATService = Depends(get_dmat_service),
):
    """List all linked DMAT accounts for the authenticated user.

    Requirements: 3.4
    """
    if svc.db_pool is None:
        return DMATListResponse(accounts=[], count=0)

    try:
        async with svc.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, depository, dp_name, status, linked_at
                   FROM dmat_accounts
                   WHERE user_id = $1
                   ORDER BY created_at DESC""",
                user_id,
            )
        accounts = [
            DMATAccountItem(
                dmat_id=str(row["id"]),
                depository=row["depository"] or "",
                dp_name=row["dp_name"],
                status=row["status"],
                linked_at=row["linked_at"].isoformat() if row["linked_at"] else None,
            )
            for row in rows
        ]
        return DMATListResponse(accounts=accounts, count=len(accounts))
    except Exception:
        logger.exception("Failed to list DMAT accounts for user %s", user_id)
        raise HTTPException(status_code=500, detail="Failed to retrieve DMAT accounts")
