"""FastAPI entry point. Boots the DB, mounts the API, and (in prod) serves the
built React SPA so the whole thing is one container. In dev the SPA runs on the
Vite server (:5173) and talks back here via CORS.
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import chat, opportunities, reddit, saturation, storefronts
from .config import get_settings
from .db import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logging.getLogger(__name__).info("DB ready; Ollama at %s", get_settings().ollama_base_url)
    yield


app = FastAPI(title="storefront-ai", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(opportunities.router)
app.include_router(reddit.router)
app.include_router(saturation.router)
app.include_router(storefronts.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Serve the built SPA if it exists (prod single-container). Mounted last so it
# doesn't shadow /api routes.
_dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="spa")
