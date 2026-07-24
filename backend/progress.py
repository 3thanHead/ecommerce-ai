"""Server-Sent-Events plumbing so the UI can watch the agent work in real time.

A "job" is `async def job(emit): ...` that calls `await emit(...)` as it goes.
`sse(job)` runs it and turns each emit into an SSE frame. Event shapes (the
`type` field drives the UI):

  {"type":"step",    "name": "...", "status": "running"|"done"}
  {"type":"thought", "text": "..."}     # streamed model tokens (the "thinking")
  {"type":"result",  "data": {...}}     # final payload
  {"type":"error",   "message": "..."}

Keeping this generic means scout, drill, and automate all stream the same way.
"""
import asyncio
import json
import logging

log = logging.getLogger(__name__)


async def sse(job):
    """Run an emit-based job and yield SSE frames until it finishes."""
    queue: asyncio.Queue = asyncio.Queue()

    async def emit(**event):
        await queue.put(event)

    async def runner():
        try:
            await job(emit)
        except Exception as e:  # surface the failure to the client, don't hang
            log.exception("streamed job failed")
            await queue.put({"type": "error", "message": str(e)})
        finally:
            await queue.put(None)  # sentinel

    task = asyncio.create_task(runner())
    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            yield f"data: {json.dumps(event)}\n\n"
    finally:
        await task


class Steps:
    """Small helper a job uses to announce named steps. `async with s.step(name)`
    emits running on enter and done on exit (or the job can call s.done(name))."""

    def __init__(self, emit):
        self._emit = emit

    async def running(self, name: str):
        await self._emit(type="step", name=name, status="running")

    async def done(self, name: str):
        await self._emit(type="step", name=name, status="done")

    async def thought(self, text: str):
        await self._emit(type="thought", text=text)
