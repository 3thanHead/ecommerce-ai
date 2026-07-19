"""The chat console — a streaming shop-focused chat UI on top of the home LLM.

Serves a single self-contained page (static/index.html) and streams tokens
from Ollama (LLM_BASE_URL) to the browser over a WebSocket, exactly like the
iot_ai chat app — but the agents run IN THIS SAME service (app/agents), so a
message can be handed to the `shop` venture agent and its working events
(stage generation, tool calls, the final approval prompt) stream straight
into the UI. No second service, no AGENTS_URL: agents are called in-process.

The one LLM endpoint is LLM_BASE_URL, so the console talks to whatever that
points at — this machine's own Ollama (local/dev) or the home cluster's
HAProxy master — interchangeably, with no code change.

    GET /                 the chat page
    GET /api/models       models available on LLM_BASE_URL (+ which are warm)
    WS  /ws/chat          stream a completion, or run a shop agent turn
"""
import asyncio
import json
import os
from pathlib import Path

import httpx
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from .. import agents

# The single LLM endpoint — this machine's Ollama or the cluster's HAProxy
# master, whichever LLM_BASE_URL names. All plain-chat generation flows here.
OLLAMA_URL = os.environ.get("LLM_BASE_URL", "http://localhost:11434").rstrip("/")
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

router = APIRouter()


@router.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@router.get("/api/models")
async def list_models():
    """Models available on the LLM endpoint, plus which are loaded in memory
    right now (/api/ps) — the UI defaults to a warm model so the first message
    skips the cold load. A down/absent endpoint just yields an empty list."""
    async def _get(client, path):
        try:
            resp = await client.get(f"{OLLAMA_URL}{path}")
            resp.raise_for_status()
            return [m["name"] for m in resp.json().get("models", [])]
        except httpx.HTTPError:
            return []

    async with httpx.AsyncClient(timeout=5) as client:
        available, running = await asyncio.gather(
            _get(client, "/api/tags"), _get(client, "/api/ps"))
    return {"models": sorted(set(available)), "running": sorted(set(running))}


async def _stream_chat(ws: WebSocket, model, messages):
    """Stream one plain completion to the browser, token by token. Cancelling
    this task unwinds the httpx stream, closing the upstream request so Ollama
    stops generating. If LLM_BASE_URL is the cluster LB, HAProxy stamps the
    serving node on X-Served-By — surfaced as a small badge."""
    payload = {"model": model, "messages": messages, "stream": True}
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", f"{OLLAMA_URL}/api/chat", json=payload) as resp:
                resp.raise_for_status()
                served = resp.headers.get("x-served-by")
                if served:
                    await ws.send_json({"type": "node", "name": served})
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    token = chunk.get("message", {}).get("content", "")
                    if token:
                        await ws.send_json({"type": "token", "content": token})
                    if chunk.get("done"):
                        break
        await ws.send_json({"type": "done"})
    except httpx.HTTPError as exc:
        await ws.send_json({"type": "error", "message": f"LLM endpoint error: {exc}"})


async def _stream_agent(ws: WebSocket, name: str, input_text: str):
    """Run one turn of an in-process agent (app/agents), relaying its working
    events (start/thinking/tool_call/tool_result/final/error) to the browser as
    {"type": "agent", "event": {...}}. Cancelling this task stops the run."""
    agent = agents.get(name)
    if agent is None:
        await ws.send_json({"type": "error", "message": f"unknown agent '{name}'"})
        return
    try:
        async for ev in agent.run(input_text):
            await ws.send_json({"type": "agent", "event": ev.to_json()})
            if ev.type in ("final", "error"):
                break
        await ws.send_json({"type": "done"})
    except Exception as exc:  # a broken agent turn shouldn't kill the socket
        await ws.send_json({"type": "error", "message": f"agent error: {exc}"})


async def _cancel(task):
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@router.websocket("/ws/chat")
async def chat(ws: WebSocket):
    """Stream a chat completion or a shop-agent turn, cancellable mid-stream.

    Client sends {"model","messages"} for plain chat, adds "agent" to route the
    last message to that in-process agent instead, or {"type":"cancel"} to stop.
    Server sends {"type": "token"|"node"|"agent"|"done"|"cancelled"|"error"}.
    """
    await ws.accept()
    gen = None
    try:
        while True:
            req = await ws.receive_json()
            if req.get("type") == "cancel":
                if gen and not gen.done():
                    await _cancel(gen)
                    await ws.send_json({"type": "cancelled"})
                continue

            messages = req.get("messages", [])
            agent = req.get("agent")  # optional: route to an in-process agent
            model = req.get("model")

            if agent:
                if not messages:
                    await ws.send_json({"type": "error", "message": "messages are required"})
                    continue
                await _cancel(gen)
                gen = asyncio.create_task(
                    _stream_agent(ws, agent, messages[-1].get("content", "")))
                continue

            if not model or not messages:
                await ws.send_json({"type": "error", "message": "model and messages are required"})
                continue

            await _cancel(gen)  # never run two generations on one socket at once
            gen = asyncio.create_task(_stream_chat(ws, model, messages))
    except WebSocketDisconnect:
        await _cancel(gen)  # tab closed mid-stream -> stop generating upstream
