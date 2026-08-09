"""Social caption generation for staged content review.

Reuses the same Ollama connection as everything else (backend/llm/ollama.py)
-- no new infra, just a prompt aimed at short-form social copy instead of
store branding (which store_gen.py used to write, before the storefront
feature was removed).
"""
from ..llm import get_llm

_SYS = """You write short, punchy captions for a social media video/image ad
selling a dropshipped product (TikTok / Instagram Reels / YouTube Shorts
style). Given a product and its audience, write ONE caption: a hook line,
1-2 short benefit lines, a clear call to action, then 3-6 relevant hashtags
on their own line. No preamble, no markdown, no emojis unless they genuinely
fit the audience. Keep the whole thing under 120 words."""


async def generate_caption(title: str, description: str = "", audience: str = "",
                            model: str | None = None) -> str:
    """One caption for a product. Raises on an LLM/network failure -- callers
    decide how to surface that (same pattern as everything else here; unlike
    images.py this has no "unconfigured" state, since Ollama is required for
    the whole app)."""
    user = (f"PRODUCT: {title}\n"
            + (f"{description}\n" if description.strip() else "")
            + f"AUDIENCE: {audience or '(general online shoppers)'}")
    text = await get_llm().chat(
        [{"role": "system", "content": _SYS}, {"role": "user", "content": user}],
        model=model, temperature=0.7,
    )
    return text.strip()
