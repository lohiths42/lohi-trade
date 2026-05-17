"""Gateway configuration loaded from environment variables."""

import os
import subprocess
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))


def _docker_running() -> bool:
    try:
        subprocess.run(["docker", "info"], capture_output=True, timeout=2, check=True)
        return True
    except Exception:
        return False


_project_root = Path(__file__).resolve().parents[2]
_sqlite_path = _project_root / "data" / "lohi_trade.sqlite"
_default_db = "postgresql://localhost:5432/lohi_trade"

if os.getenv("DATABASE_URL"):
    DATABASE_URL = os.getenv("DATABASE_URL")
elif _docker_running():
    DATABASE_URL = _default_db
else:
    _sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    DATABASE_URL = f"sqlite+aiosqlite:///{_sqlite_path}"

PG_POOL_MIN_SIZE = int(os.getenv("PG_POOL_MIN_SIZE", "5"))
PG_POOL_MAX_SIZE = int(os.getenv("PG_POOL_MAX_SIZE", "20"))

# ── Redis connection pool settings (Requirement 34.6) ────────────────────────
REDIS_POOL_MIN_CONNECTIONS = int(os.getenv("REDIS_POOL_MIN_CONNECTIONS", "2"))
REDIS_POOL_MAX_CONNECTIONS = int(os.getenv("REDIS_POOL_MAX_CONNECTIONS", "10"))

# NVIDIA NIM optional integration configuration
NIM_API_KEY = os.getenv("NIM_API_KEY")
NIM_ENDPOINT = os.getenv("NIM_ENDPOINT", "https://integrate.api.nvidia.com/v1")
NIM_MODEL = os.getenv("NIM_MODEL", "meta/llama3.1-8b-instruct")
NIM_CONFIG = (
    {
        "api_key": NIM_API_KEY,
        "endpoint": NIM_ENDPOINT,
        "model": NIM_MODEL,
    }
    if NIM_API_KEY
    else {}
)
