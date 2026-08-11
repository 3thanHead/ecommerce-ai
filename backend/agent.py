"""Base classes for talking to an LLM 'agent' whose prompt (and, where it has
one, output schema / tool defs) live in a markdown file under agents/ at the
repo root -- never as a string constant in this codebase. See
agents/README.md for the file format.

Python's job is everything the markdown *doesn't* do: gathering the real data
that goes into the user message, executing whatever tools a ToolAgent
declares, and turning the agent's structured reply back into something the
caller can use (merging verdicts onto real records, clamping scores, deciding
what to do on failure). The agent itself is just "system prompt (+ optional
schema, + optional tools) in, chat completion out" -- an Agent instance is
that plumbing and nothing else.

    _AGENT = Agent("drill")                      # loads agents/drill.md once
    data = await _AGENT.chat(user_message)        # dict if drill.md has a
                                                    # ```json schema, else str
"""
import json
import logging
import re
from pathlib import Path

from .llm import get_heavy_llm, get_llm, parse_json

log = logging.getLogger(__name__)

_AGENTS_DIR = Path(__file__).resolve().parents[1] / "agents"
# Every fenced ```json block in the file, in order. A plain Agent's file has
# at most one (the output schema); a ToolAgent's has two (tool defs, then the
# output schema) -- see _parse_agent_file. Zero blocks -> prompt-only agent
# (e.g. captions), .chat() returns raw text.
_JSON_BLOCK_RE = re.compile(r"```json\s*\n(.*?)\n```", re.S)


def _parse_agent_file(text: str) -> tuple[str, list | None, dict | None]:
    """(system prompt, tool defs or None, output schema or None)."""
    blocks = list(_JSON_BLOCK_RE.finditer(text))
    if not blocks:
        return text.strip(), None, None
    system = text[: blocks[0].start()].strip()
    if len(blocks) == 1:
        return system, None, json.loads(blocks[0].group(1))
    return system, json.loads(blocks[0].group(1)), json.loads(blocks[1].group(1))


class Agent:
    """One LLM agent, defined entirely by agents/<name>.md."""

    def __init__(self, name: str, heavy: bool = False):
        self.name = name
        self.heavy = heavy  # route through the heavy node (get_heavy_llm) or the workhorse
        text = (_AGENTS_DIR / f"{name}.md").read_text()
        self.system, self._declared_tools, self.schema = _parse_agent_file(text)

    def _llm(self):
        return get_heavy_llm() if self.heavy else get_llm()

    def _messages(self, user: str) -> list[dict]:
        return [{"role": "system", "content": self.system}, {"role": "user", "content": user}]

    async def chat(self, user: str, model: str | None = None, temperature: float = 0.4):
        """One turn -> parsed dict if this agent has a schema, else raw text."""
        raw = await self._llm().chat(
            self._messages(user), model=model, temperature=temperature, fmt=self.schema
        )
        return parse_json(raw) if self.schema else raw.strip()

    async def chat_stream(self, user: str, on_chunk=None, model: str | None = None,
                          temperature: float = 0.4):
        """Same result as chat(), but streams chunks through `on_chunk` as they
        arrive (callers pass a progress.Steps.thought for the "thinking" UI
        panel) instead of waiting for the whole reply."""
        raw = ""
        async for chunk in self._llm().chat_stream(
            self._messages(user), model=model, temperature=temperature, fmt=self.schema
        ):
            raw += chunk
            if on_chunk:
                await on_chunk(chunk)
        return parse_json(raw) if self.schema else raw.strip()


class ToolAgent(Agent):
    """An Agent that can call real tools mid-conversation before answering.

    agents/<name>.md needs a SECOND trailing ```json block ahead of the usual
    schema block: the tool definitions, in Ollama/OpenAI function-calling
    shape (see agents/README.md). The tools themselves -- what actually runs
    when the model asks to call one -- are Python, supplied at construction:
    that's real logic (an HTTP call, a DB read, whatever), not agent text.
    """

    def __init__(self, name: str, tools: dict, heavy: bool = False, max_rounds: int = 4):
        super().__init__(name, heavy=heavy)
        if not self._declared_tools:
            raise ValueError(f"agents/{name}.md declares no tools block for a ToolAgent")
        declared_names = {t["function"]["name"] for t in self._declared_tools}
        if declared_names != set(tools):
            raise ValueError(
                f"agents/{name}.md declares tools {sorted(declared_names)}, "
                f"but ToolAgent({name!r}) was constructed with {sorted(tools)}"
            )
        self.tools = tools  # name -> async def(arguments: dict) -> str
        self.max_rounds = max_rounds

    async def run(self, user: str, model: str | None = None, on_chunk=None,
                  temperature: float = 0.4):
        """Let the model call tools until it stops asking (or max_rounds runs
        out), then finalize: one more turn, tools removed, schema-constrained
        if declared -- same guarantee Agent.chat()/chat_stream() give, so
        callers don't need to know this agent used tools at all."""
        llm = self._llm()
        messages = self._messages(user)
        for _ in range(self.max_rounds):
            reply = await llm.chat_tools(messages, tools=self._declared_tools,
                                         model=model, temperature=temperature)
            calls = reply.get("tool_calls") or []
            if not calls:
                break
            messages.append(reply)
            for call in calls:
                fn = call.get("function") or {}
                name, args = fn.get("name"), fn.get("arguments") or {}
                impl = self.tools.get(name)
                result = await impl(args) if impl else f"error: unknown tool {name!r}"
                messages.append({"role": "tool", "tool_name": name, "content": result})
        else:
            log.warning("agents/%s.md: hit max_rounds (%d) still requesting tools",
                       self.name, self.max_rounds)

        messages.append({"role": "user", "content": "Given everything above, give your final answer now."})
        raw = ""
        async for chunk in llm.chat_stream(messages, model=model, temperature=temperature,
                                           fmt=self.schema):
            raw += chunk
            if on_chunk:
                await on_chunk(chunk)
        return parse_json(raw) if self.schema else raw.strip()
