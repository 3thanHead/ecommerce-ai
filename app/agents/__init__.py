"""The agents themselves, plus their discovery: any module in this package
exporting AGENT (a BaseAgent instance) is registered under its .name.
Adding an agent = adding a file; nothing else to touch."""
import importlib
import logging
import pkgutil

from .base import BaseAgent

log = logging.getLogger("agents.registry")

_registry: dict[str, BaseAgent] = {}


def load() -> dict[str, BaseAgent]:
    if _registry:
        return _registry
    for mod_info in pkgutil.iter_modules(__path__):
        # base/events are plumbing; prompts/ and shop/ are support packages.
        if mod_info.name in ("base", "events", "prompts", "shop"):
            continue
        mod = importlib.import_module(f"{__name__}.{mod_info.name}")
        agent = getattr(mod, "AGENT", None)
        if isinstance(agent, BaseAgent) and agent.name:
            _registry[agent.name] = agent
            log.info("registered agent '%s' (%s)", agent.name, mod_info.name)
        else:
            log.warning("module %s has no AGENT; skipped", mod_info.name)
    return _registry


def get(name: str) -> BaseAgent | None:
    return load().get(name)


def describe() -> list[dict]:
    return [{"name": a.name, "description": a.description}
            for a in load().values()]
