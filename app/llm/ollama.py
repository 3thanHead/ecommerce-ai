"""The entire AI connection: one Ollama endpoint, model chosen per call.

Deliberately thin. There is no router, no tiering, no failover -- you point
OLLAMA_BASE_URL at the edge-ai box (or a local Ollama) and name a model. Any
model pulled on that box works; `list_models()` powers the UI picker.

    llm = get_llm()
    text = await llm.chat([{"role": "user", "content": "hi"}])
    data = await llm.json("You output JSON.", "list 3 fruits as {items:[...]}")
"""
import json
import logging

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)

# Reasoning models (qwen3, etc.) wrap chain-of-thought in <think>...</think>.
# We strip it before returning / parsing so callers see only the answer.
_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"


def _strip_think(text: str) -> str:
    if _THINK_CLOSE in text:
        text = text.split(_THINK_CLOSE, 1)[1]
    return text.strip()


class OllamaClient:
    def __init__(self, base_url: str, default_model: str, timeout: float = 300.0):
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.timeout = timeout

    async def list_models(self) -> list[str]:
        """Model names pulled on the target box (`ollama list`), for the picker."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(f"{self.base_url}/api/tags")
            r.raise_for_status()
            tags = r.json().get("models", [])
        return sorted(m["name"] for m in tags)

    async def chat(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.7,
        fmt: str | None = None,
    ) -> str:
        """One non-streaming chat turn -> assistant text (think blocks stripped).

        `fmt="json"` asks Ollama to constrain output to valid JSON.
        """
        payload = {
            "model": model or self.default_model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if fmt:
            payload["format"] = fmt
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(f"{self.base_url}/api/chat", json=payload)
            r.raise_for_status()
            content = r.json()["message"]["content"]
        return _strip_think(content)

    async def chat_stream(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.7,
    ):
        """Yield assistant text chunks as they generate. Nothing is stripped here
        -- callers that want to SHOW the model working forward every chunk
        (including <think>…</think>); callers that want the answer accumulate the
        chunks and _strip_think() at the end. See parse_json_stream below."""
        payload = {
            "model": model or self.default_model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": temperature},
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    piece = json.loads(line).get("message", {}).get("content", "")
                    if piece:
                        yield piece

    async def json(
        self,
        system: str,
        user: str,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> dict:
        """Chat constrained to JSON, parsed to a dict. Raises on unparseable output."""
        raw = await self.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            model=model,
            temperature=temperature,
            fmt="json",
        )
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Some models fence or prepend prose even in json mode -- salvage the
            # first {...} span before giving up.
            start, end = raw.find("{"), raw.rfind("}")
            if 0 <= start < end:
                return json.loads(raw[start : end + 1])
            log.warning("LLM returned non-JSON: %s", raw[:200])
            raise


def parse_json(raw: str) -> dict:
    """Parse a model's (possibly think-wrapped, possibly fenced) reply into a
    dict. Used by streaming callers that accumulated chunks themselves."""
    text = _strip_think(raw)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if 0 <= start < end:
            return json.loads(text[start : end + 1])
        log.warning("LLM returned non-JSON: %s", text[:200])
        raise


def get_llm() -> OllamaClient:
    s = get_settings()
    return OllamaClient(s.ollama_base_url, s.ollama_model)


def get_heavy_llm() -> OllamaClient:
    """The bigger model on the heavy node for knowledge-critical steps. Falls
    back to the workhorse when no heavy node is configured."""
    s = get_settings()
    if s.ollama_heavy_base_url:
        return OllamaClient(s.ollama_heavy_base_url, s.ollama_heavy_model or s.ollama_model)
    return get_llm()
