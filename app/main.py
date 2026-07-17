"""storefront-ai -- the content-generation service for the storefront.

Everything that CREATES lives in this repo: the approval-gated venture
ladder (niche -> brand -> catalog -> assembly -> marketing), the storefront
template, the static-site builder, and the media tooling. All LLM work goes
to the home cluster (LLM_BASE_URL -> HAProxy master) -- free local
inference, nothing paid. GitHub Actions only renders + ships the approved
content to S3/CloudFront (no LLM, no LAN needed there).

REST
    GET  /health                     liveness + registered agents
    GET  /api/agents                 registered agents
    POST /api/agents/shop/run        {"input": "start <seed>" | "approve" | ...}
    GET  /store/export               the content snapshot (commit to content/)
    GET  /shop, /blog                live LAN preview of the storefront

WS
    /ws/agents/shop                  the live AgentEvent stream
"""
import logging

from fastapi import FastAPI

from . import agents, api, db

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

app = FastAPI(title="storefront-ai", version="0.1.0")
for router in api.routers:
    app.include_router(router)


@app.on_event("startup")
async def startup():
    await db.init()
    agents.load()
