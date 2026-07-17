"""GET /health -- liveness + what's registered and where the LLM work goes."""
import os

from fastapi import APIRouter

from .. import agents

router = APIRouter()


@router.get("/health")
async def health():
    return {"ok": True,
            "agents": [a["name"] for a in agents.describe()],
            "llm": os.environ.get("LLM_BASE_URL", "http://localhost:11434"),
            "image": os.environ.get("IMAGE_BASE_URL") or None}
