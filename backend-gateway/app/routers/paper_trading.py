"""Paper trading simulation control endpoints.

Provides start/stop/status for the paper trading simulation.
The simulation runs as a background subprocess so the gateway stays responsive.
"""

import logging
import os
import signal
import subprocess
import sys
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Simulation process state ─────────────────────────────────────────────────

_sim_process: Optional[subprocess.Popen] = None
_sim_started_at: Optional[str] = None
_sim_config: Optional[dict] = None


class PaperTradingStartRequest(BaseModel):
    model_config = {"populate_by_name": True}

    capital: float = 200000
    days: int = 5
    speed: float = 50
    use_real_data: bool = Field(default=True, alias="useRealData")  # Default to real data from Yahoo Finance


class PaperTradingStatus(BaseModel):
    model_config = {"populate_by_name": True}

    running: bool
    started_at: Optional[str] = Field(default=None, alias="startedAt")
    capital: Optional[float] = None
    days: Optional[int] = None
    speed: Optional[float] = None
    pid: Optional[int] = None
    use_real_data: Optional[bool] = Field(default=None, alias="useRealData")


@router.get("/paper-trading/status")
def get_status() -> PaperTradingStatus:
    global _sim_process, _sim_started_at, _sim_config
    running = _sim_process is not None and _sim_process.poll() is None
    if not running and _sim_process is not None:
        # Process finished — clean up
        _sim_process = None
    return PaperTradingStatus(
        running=running,
        started_at=_sim_started_at if running else None,
        capital=_sim_config.get("capital") if _sim_config and running else None,
        days=_sim_config.get("days") if _sim_config and running else None,
        speed=_sim_config.get("speed") if _sim_config and running else None,
        pid=_sim_process.pid if _sim_process and running else None,
        use_real_data=_sim_config.get("useRealData") if _sim_config and running else None,
    )


@router.post("/paper-trading/start")
def start_simulation(req: PaperTradingStartRequest) -> PaperTradingStatus:
    global _sim_process, _sim_started_at, _sim_config

    # Check if already running
    if _sim_process is not None and _sim_process.poll() is None:
        raise HTTPException(status_code=409, detail="Simulation already running")

    # Find the simulation script
    # __file__ = backend-gateway/app/routers/paper_trading.py
    # project root = 3 levels up
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    script_path = os.path.join(project_root, "scripts", "paper_simulation.py")

    if not os.path.exists(script_path):
        raise HTTPException(status_code=500, detail=f"Simulation script not found at {script_path}")

    db_path = os.path.join(project_root, "data", "lohi_trade.db")

    cmd = [
        sys.executable,
        script_path,
        "--speed",
        str(req.speed),
        "--days",
        str(req.days),
        "--capital",
        str(req.capital),
        "--db",
        db_path,
    ]
    if req.use_real_data:
        cmd.append("--real-data")

    logger.info(f"Starting paper simulation: {' '.join(cmd)}")

    try:
        _sim_process = subprocess.Popen(
            cmd,
            cwd=project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            preexec_fn=os.setsid,  # Create new process group for clean kill
        )
        _sim_started_at = datetime.now().isoformat()
        _sim_config = {
            "capital": req.capital,
            "days": req.days,
            "speed": req.speed,
            "useRealData": req.use_real_data,
        }

        logger.info(f"Paper simulation started, PID={_sim_process.pid}")

        return PaperTradingStatus(
            running=True,
            started_at=_sim_started_at,
            capital=req.capital,
            days=req.days,
            speed=req.speed,
            pid=_sim_process.pid,
            use_real_data=req.use_real_data,
        )
    except Exception as e:
        logger.error(f"Failed to start simulation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/paper-trading/stop")
def stop_simulation() -> PaperTradingStatus:
    global _sim_process, _sim_started_at, _sim_config

    if _sim_process is None or _sim_process.poll() is not None:
        _sim_process = None
        return PaperTradingStatus(running=False)

    try:
        # Kill the entire process group
        os.killpg(os.getpgid(_sim_process.pid), signal.SIGTERM)
        _sim_process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(_sim_process.pid), signal.SIGKILL)
        _sim_process.wait(timeout=3)
    except Exception as e:
        logger.error(f"Error stopping simulation: {e}")

    _sim_process = None
    logger.info("Paper simulation stopped")

    return PaperTradingStatus(running=False)
