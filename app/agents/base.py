"""BaseAgent -- subclass this + drop the module in app/agents/ = new agent.

An agent is: a name, a purpose prompt, a set of LangChain @tool functions,
and a JSON schema for its final answer. The base class runs the standard
tool-calling loop against the cluster (ChatOllama.bind_tools) and yields
AgentEvents as it goes, so every agent streams the same way for free.

The final model turn must be JSON matching the agent's contract; we parse it,
and on garbage we retry once with the error shown to the model, then fall
back to {"message": <raw text>} so callers always get an object.

Concurrency: agents hold no per-run state (run() is a pure async generator),
so one registered instance safely serves many concurrent runs; the cluster's
HAProxy spreads the LLM calls across nodes.
"""
import json
import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, AsyncIterator

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_ollama import ChatOllama

from . import events
from .events import AgentEvent

log = logging.getLogger("agents")

# The cluster endpoint (HAProxy master) + a tool-calling-capable model it
# serves. Env-only (.env / compose) -- no IPs committed.
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:11434").rstrip("/")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen3:4b-instruct")

# System prompts live as markdown next to the agents, one file per prompt, so
# prompt text can be read and edited without touching code.
PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_prompt(name: str) -> str:
    """The prompt text of prompts/<name>.md. Read per call, not cached, so a
    live-mounted file can be tweaked without a restart."""
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


class BaseAgent(ABC):
    """One agent = name + description + purpose prompt + tools."""

    name: str = ""
    description: str = ""
    max_steps: int = 8      # model round-trips per run
    tool_budget: int = 6    # executed tool calls per run

    def system_prompt(self) -> str:
        """prompts/<name>.md by default (raises if the file is missing --
        every tool-loop agent needs one). Override only when the prompt
        must be composed dynamically or the agent overrides run()."""
        return load_prompt(self.name)

    @abstractmethod
    def tools(self) -> list[BaseTool]: ...

    def validate_output(self, output: dict) -> str | None:
        """Return an error string if `output` violates this agent's contract,
        None when it's fine. The base loop retries once with the error shown
        to the model."""
        return None

    def build_output(self, model_json: dict, raw_text: str,
                     trace: list[dict]) -> dict:
        """Assemble the final API output. `trace` is the ground truth of what
        the agent actually did ({tool, args, result} per call); agents should
        derive the guaranteed fields from it and take only prose from the
        model -- code, not the model, keeps the JSON contract consistent."""
        return model_json if model_json else {"message": raw_text}

    async def act_on_output(self, output: dict, trace: list[dict],
                            input_text: str) -> AsyncIterator[AgentEvent]:
        """Deterministic actuation AFTER the model has decided: agents that
        must translate a decision in the final JSON into device commands do
        it here, in code -- small models reason fine but wire tool args
        badly, so the decision->actuation step should not be theirs. May
        mutate `output` (e.g. append to its actions) and yield tool events."""
        return
        yield  # pragma: no cover -- makes this an (empty) async generator

    def llm(self) -> ChatOllama:
        # The default model is the non-thinking qwen3 instruct: hybrid-thinking
        # builds burn thinking tokens every tool-loop step (too slow on edge
        # hardware), and their "think off" switch leaks the monologue into
        # content on current Ollama. Don't send a reasoning flag — non-thinking
        # models can reject it.
        return ChatOllama(base_url=LLM_BASE_URL, model=LLM_MODEL,
                          temperature=0)

    async def run(self, input_text: str) -> AsyncIterator[AgentEvent]:
        """Drive the tool loop, yielding events; the last event is final/error."""
        yield events.start(self.name, input_text)

        tools = self.tools()
        by_name = {t.name: t for t in tools}
        llm = self.llm().bind_tools(tools) if tools else self.llm()
        trace: list[dict] = []  # every executed tool call, the run's ground truth

        messages: list[BaseMessage] = [
            SystemMessage(self.system_prompt()),
            HumanMessage(input_text),
        ]

        try:
            for step in range(self.max_steps):
                ai: AIMessage = await llm.ainvoke(messages)
                messages.append(ai)

                calls = list(ai.tool_calls)
                if not calls:
                    # Small models sometimes emit a tool call as plain JSON
                    # text instead of a structured call -- honor the intent.
                    stray = _textual_tool_call(str(ai.content), by_name)
                    if stray is not None:
                        stray["id"] = f"stray-{step}"
                        calls = [stray]

                if not calls:
                    async for ev in self._finalize(ai, messages, llm, by_name,
                                                   trace, input_text):
                        yield ev
                    return

                if ai.content and ai.tool_calls:
                    yield events.thinking(str(ai.content))
                for call in calls:
                    yield events.tool_call(call["name"], call["args"])
                    result = await self._run_tool(by_name, call)
                    trace.append({"tool": call["name"], "args": call["args"],
                                  "result": result})
                    yield events.tool_result(call["name"], result)
                    if call["id"].startswith("stray-"):
                        messages.append(HumanMessage(
                            f"Result of {call['name']}: {json.dumps(result)}. "
                            "Now reply with ONLY the final JSON object from "
                            "your instructions."))
                    else:
                        messages.append(ToolMessage(
                            content=json.dumps(result), tool_call_id=call["id"]))

                if len(trace) >= self.tool_budget:
                    break  # a run-away tool loop; force the final answer

            # Budget exhausted: one tool-free turn so the run still ends with
            # the agent's JSON (and its decision) instead of an error.
            messages.append(HumanMessage(
                "Stop using tools. Reply with ONLY the final JSON object "
                "from your instructions."))
            final_ai: AIMessage = await self.llm().ainvoke(messages)
            messages.append(final_ai)
            async for ev in self._finalize(final_ai, messages, llm, by_name,
                                           trace, input_text):
                yield ev
        except Exception as e:  # surface cluster/device failures to the stream
            log.exception("agent %s failed", self.name)
            yield events.error(str(e))

    async def _run_tool(self, by_name: dict[str, BaseTool], call: dict) -> Any:
        tool = by_name.get(call["name"])
        if tool is None:
            return {"error": f"unknown tool {call['name']}"}
        try:
            return await tool.ainvoke(call["args"])
        except Exception as e:
            return {"error": str(e)}

    async def _finalize(self, ai: AIMessage, messages: list[BaseMessage],
                        llm, by_name: dict[str, BaseTool], trace: list[dict],
                        input_text: str) -> AsyncIterator[AgentEvent]:
        """Parse + validate the final turn as JSON. Retries once with the
        problem shown to the model; if a retry turns out to be yet another
        tool call written as text, execute it and ask again. Whatever the
        model manages, build_output() guarantees the contract from the trace."""
        text = str(ai.content).strip()
        output = _extract_json(text)
        problem = ("not valid JSON" if output is None
                   else self.validate_output(output))
        for _ in range(2):  # at most: one stray-tool round + one plain retry
            if problem is None:
                break
            stray = _textual_tool_call(text, by_name)
            if stray is not None:
                yield events.tool_call(stray["name"], stray["args"])
                result = await self._run_tool(by_name, stray)
                trace.append({"tool": stray["name"], "args": stray["args"],
                              "result": result})
                yield events.tool_result(stray["name"], result)
                messages.append(HumanMessage(
                    f"Result of {stray['name']}: {json.dumps(result)}. Now "
                    "reply with ONLY the final JSON object from your "
                    "instructions."))
            else:
                messages.append(HumanMessage(
                    f"Your last reply was {problem}. Reply with ONLY the JSON "
                    "object described in your instructions, no prose."))
            # Retry with NO tools bound: the model must produce text now --
            # small models otherwise keep emitting tool calls forever.
            retry: AIMessage = await self.llm().ainvoke(messages)
            messages.append(retry)
            text = str(retry.content).strip()
            output = _extract_json(text)
            problem = ("not valid JSON" if output is None
                       else self.validate_output(output))
        built = self.build_output(output or {}, text, trace)
        async for ev in self.act_on_output(built, trace, input_text):
            yield ev
        yield events.final(built)


def _textual_tool_call(text: str, by_name: dict[str, BaseTool]) -> dict | None:
    """Detect a tool call the model wrote as prose JSON, e.g.
    {"name": "answer_with_leds", "arguments": {"answer": true}}."""
    obj = _extract_json(text)
    if not obj:
        return None
    name = obj.get("name") or obj.get("tool")
    args = obj.get("arguments") if isinstance(obj.get("arguments"), dict) \
        else obj.get("args") if isinstance(obj.get("args"), dict) else None
    if name in by_name and args is not None:
        return {"name": name, "args": args}
    return None


def _extract_json(text: str) -> dict | None:
    """Parse a JSON object out of model text (tolerates ```json fences and
    leaked special tokens like mistral's [TOOL_CALLS])."""
    s = text.replace("[TOOL_CALLS]", " ").strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.startswith("json"):
            s = s[4:]
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(s[start:end + 1])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None
