"""Config endpoints — read/write settings.yaml."""

from fastapi import APIRouter, HTTPException
import yaml

from app.config import CONFIG_PATH

router = APIRouter()


@router.get("/config")
def get_config():
    """Read current config from settings.yaml."""
    try:
        with open(CONFIG_PATH, "r") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/config")
def update_config(config: dict):
    """Write updated config to settings.yaml."""
    try:
        with open(CONFIG_PATH, "w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        return {"status": "updated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
