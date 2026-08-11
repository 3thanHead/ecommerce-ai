"""Social caption generation for staged content review.

Reuses the same Ollama connection as everything else (backend/llm/ollama.py)
-- no new infra, just a prompt aimed at short-form social copy instead of
store branding (which store_gen.py used to write, before the storefront
feature was removed). Prompt: agents/caption.md.
"""
from ..agent import Agent

_agent = Agent("caption")


async def generate_caption(title: str, description: str = "", audience: str = "",
                            model: str | None = None) -> str:
    """One caption for a product. Raises on an LLM/network failure -- callers
    decide how to surface that (same pattern as everything else here; unlike
    images.py this has no "unconfigured" state, since Ollama is required for
    the whole app)."""
    user = (f"PRODUCT: {title}\n"
            + (f"{description}\n" if description.strip() else "")
            + f"AUDIENCE: {audience or '(general online shoppers)'}")
    return await _agent.chat(user, model=model, temperature=0.7)
