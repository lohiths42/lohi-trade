"""Health check endpoint."""

import os

from fastapi import APIRouter

from app.config import DB_PATH
from app.services.redis_consumer import redis_ping

router = APIRouter()


@router.get("/health")
def health_check():
    redis_ok = redis_ping()
    db_ok = os.path.exists(DB_PATH)
    healthy = redis_ok and db_ok
    return {
        "status": "healthy" if healthy else "degraded",
        "redis": redis_ok,
        "database": db_ok,
    }
