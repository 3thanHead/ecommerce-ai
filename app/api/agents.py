"""Agent handlers -- list, blocking run, and the live WS event stream.

REST
    GET  /api/agents             registered agents
    POST /api/agents/{name}/run  {"input": "..."} -> {"output": ..., "events": [...]}

WS
    /ws/agents/{name}            send {"input": "..."}; receive the live
                                 AgentEvent stream (app/agents/events.py),
                                 ending with a "final" (or "error") event.
                                 The socket stays open for more inputs.
"""
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from .. import agents

router = APIRouter()


@router.get("/api/agents")
async def list_agents():
    return agents.describe()


@router.post("/api/agents/{name}/run")
async def run_agent(name: str, body: dict):
    """Blocking run: collects the whole event stream, returns final output +
    the events that led to it. The WS endpoint is the live version of this."""
    agent = agents.get(name)
    if agent is None:
        return JSONResponse({"error": f"unknown agent '{name}'"}, status_code=404)
    input_text = str(body.get("input", "")).strip()
    if not input_text:
        return JSONResponse({"error": "body must include 'input'"}, status_code=400)

    events = []
    async for ev in agent.run(input_text):
        events.append(ev.to_json())
    last = events[-1]
    return {"agent": name,
            "output": last.get("output") if last["type"] == "final" else None,
            "error": last.get("message") if last["type"] == "error" else None,
            "events": events}


@router.websocket("/ws/agents/{name}")
async def ws_agent(ws: WebSocket, name: str):
    agent = agents.get(name)
    await ws.accept()
    if agent is None:
        await ws.send_json({"type": "error", "message": f"unknown agent '{name}'"})
        await ws.close()
        return
    try:
        while True:
            raw = await ws.receive_text()
            try:
                input_text = str(json.loads(raw).get("input", "")).strip()
            except json.JSONDecodeError:
                input_text = raw.strip()
            if not input_text:
                await ws.send_json({"type": "error", "message": "empty input"})
                continue
            async for ev in agent.run(input_text):
                await ws.send_json(ev.to_json())
    except WebSocketDisconnect:
        pass
