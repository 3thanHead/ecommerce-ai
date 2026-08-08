"""One place for every knob, read from the environment (.env in dev).

Nothing here needs a value to import -- the app boots with defaults so you can
run it and *then* point OLLAMA_BASE_URL at the fleet. The CJ supply key is
optional; saturation degrades to the model's estimate when it's blank.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- LLM (edge-ai / Ollama) ---
    # The fast workhorse (nano) -- streamed drills, everything by default.
    ollama_base_url: str = "http://192.168.1.111:11434"
    ollama_model: str = "qwen2.5:7b-instruct"

    # Optional "heavy" node for the knowledge-heavy step (category + subreddit
    # brainstorm): a bigger model on a beefier box (e.g. the 12GB Mac running
    # qwen2.5:14b). Blank -> that step just uses the workhorse above.
    ollama_heavy_base_url: str = ""
    ollama_heavy_model: str = ""

    # --- Datastore ---
    database_url: str = "sqlite:///data/storefront.db"

    # Reddit grounding uses the free Pushshift-successor archives (PullPush +
    # Arctic Shift) directly -- no keys, no page reader -- so there's nothing to
    # configure here. See backend/research/reddit.py.

    # --- Supply counts for MEASURED saturation (optional; degrade to the
    #     model's estimate when unset) ---
    # CJdropshipping: # of dropship products per keyword (the supply signal) AND
    # the Feature 2 product source. Free account, no card. Local + private: this
    # is an OUTBOUND call from your machine, nothing is exposed.
    cj_email: str = ""
    cj_api_key: str = ""

    @property
    def has_cj(self) -> bool:
        return bool(self.cj_email and self.cj_api_key)

    # --- Image generation (edge-ai's image-gen node) ---
    # Points at the fleet's image-role box (see edge-ai/apps/image-gen). Blank
    # -> the feature quietly disables, same degrade pattern as CJ above.
    image_base_url: str = ""
    image_model: str = ""

    @property
    def has_image_gen(self) -> bool:
        return bool(self.image_base_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
