"""Gateway configuration loaded from environment variables."""

import os
from dotenv import load_dotenv

load_dotenv()

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
DB_PATH = os.getenv("DB_PATH", "../data/lohi_trade.db")
CONFIG_PATH = os.getenv("CONFIG_PATH", "../config/settings.yaml")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:3001,http://localhost:3002,http://localhost:5173").split(",")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
JWT_SECRET = os.getenv("JWT_SECRET", SECRET_KEY)
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

# ── PostgreSQL asyncpg connection pool settings (Requirement 34.6) ───────────
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/lohi_trade")
PG_POOL_MIN_SIZE = int(os.getenv("PG_POOL_MIN_SIZE", "5"))
PG_POOL_MAX_SIZE = int(os.getenv("PG_POOL_MAX_SIZE", "20"))

# ── Redis connection pool settings (Requirement 34.6) ────────────────────────
REDIS_POOL_MIN_CONNECTIONS = int(os.getenv("REDIS_POOL_MIN_CONNECTIONS", "2"))
REDIS_POOL_MAX_CONNECTIONS = int(os.getenv("REDIS_POOL_MAX_CONNECTIONS", "10"))
