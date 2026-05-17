"""Logs endpoint."""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from app.models.logs import LogResponse
from app.services import db_service

router = APIRouter()


@router.get("/logs", response_model=List[LogResponse])
def list_logs(
    level: Optional[str] = Query(None),
    component: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    try:
        return db_service.get_logs(level=level, component=component, limit=limit, offset=offset)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
