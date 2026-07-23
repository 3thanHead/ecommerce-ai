"""Chat + model picker -- the smallest thing that proves the fleet connection.

`GET /api/models` lists what's pulled on the edge-ai box; `POST /api/chat`
runs one turn against a chosen model. This is how you sanity-check OLLAMA_BASE_URL
before trusting the research agent.
"""
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import get_settings
from ..llm import get_llm

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    model: str | None = None
    temperature: float = 0.7


@router.get("/models")
async def models():
    llm = get_llm()
    try:
        names = await llm.list_models()
    except Exception as e:
        # Fleet unreachable -- report it plainly so the UI can show a banner.
        raise HTTPException(status_code=502, detail=f"Cannot reach Ollama at {llm.base_url}: {e}")
    return {"default": llm.default_model, "models": names, "base_url": llm.base_url}


@router.post("/chat")
async def chat(req: ChatRequest):
    llm = get_llm()
    try:
        reply = await llm.chat(
            [m.model_dump() for m in req.messages],
            model=req.model,
            temperature=req.temperature,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM error: {e}")
    return {"reply": reply, "model": req.model or get_settings().ollama_model}
