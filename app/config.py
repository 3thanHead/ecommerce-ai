"""One place for every knob, read from the environment (.env in dev).

Nothing here needs a value to import -- the app boots with defaults so you can
run it and *then* point OLLAMA_BASE_URL at the fleet. Reddit/CJ keys are
optional; the code degrades to keyless paths when they're blank.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- LLM (edge-ai / Ollama) ---
    ollama_base_url: str = "http://192.168.1.111:11434"
    ollama_model: str = "qwen2.5:7b-instruct"

    # --- Datastore ---
    database_url: str = "sqlite:///data/storefront.db"

    # --- Reddit ---
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "storefront-ai/0.1 (niche research)"

    # --- Page reader (Reddit grounding) ---
    # Firecrawl reads Reddit server-side with rotating IPs (reliable despite the
    # IP block). Free tier: 1,000 credits/mo, no card. Empty -> keyless Jina.
    firecrawl_api_key: str = ""
    jina_reader_base: str = "https://r.jina.ai"

    # --- CJdropshipping (Feature 2) ---
    cj_email: str = ""
    cj_api_key: str = ""

    @property
    def reddit_has_api(self) -> bool:
        return bool(self.reddit_client_id and self.reddit_client_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()
