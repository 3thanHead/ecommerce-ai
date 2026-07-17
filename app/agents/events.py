"""The event stream an agent emits while it works.

This is the wire protocol between an agent run and any UI showing it live
(the chat app's activity feed, `wscat`, ...). Every event is one JSON object:

    {"type": "start",       "agent": "led", "input": "..."}
    {"type": "thinking",    "text": "partial model text"}
    {"type": "tool_call",   "tool": "set_led", "args": {...}}
    {"type": "tool_result", "tool": "set_led", "result": {...}}
    {"type": "final",       "output": {...structured agent JSON...}}
    {"type": "error",       "message": "..."}

`final.output` is always a JSON object; each agent documents its own schema.
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentEvent:
    type: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict:
        return {"type": self.type, **self.data}


def start(agent: str, input_text: str) -> AgentEvent:
    return AgentEvent("start", {"agent": agent, "input": input_text})


def thinking(text: str) -> AgentEvent:
    return AgentEvent("thinking", {"text": text})


def tool_call(tool: str, args: dict) -> AgentEvent:
    return AgentEvent("tool_call", {"tool": tool, "args": args})


def tool_result(tool: str, result: Any) -> AgentEvent:
    return AgentEvent("tool_result", {"tool": tool, "result": result})


def final(output: dict) -> AgentEvent:
    return AgentEvent("final", {"output": output})


def error(message: str) -> AgentEvent:
    return AgentEvent("error", {"message": message})
