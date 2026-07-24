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

    # --- Reddit ---
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "storefront-ai/0.1 (niche research)"

    # --- Page reader (Reddit grounding) ---
    # Firecrawl reads Reddit server-side with rotating IPs (reliable despite the
    # IP block). Free tier: 1,000 credits/mo, no card. Empty -> keyless Jina.
    firecrawl_api_key: str = ""
    jina_reader_base: str = "https://r.jina.ai"

    # --- Supply counts for MEASURED saturation (all optional; degrade to the
    #     model's estimate when unset) ---
    # CJdropshipping: # of dropship products per keyword (the most relevant supply
    # signal) AND the Feature 2 product source. Free account, no card.
    cj_email: str = ""
    cj_api_key: str = ""
    # eBay Browse API: # of listings per keyword (broad-market supply). Free dev
    # account -> an application (client id/secret) for the client-credentials token.
    ebay_client_id: str = ""
    ebay_client_secret: str = ""

    @property
    def has_cj(self) -> bool:
        return bool(self.cj_email and self.cj_api_key)

    @property
    def has_ebay(self) -> bool:
        return bool(self.ebay_client_id and self.ebay_client_secret)

    @property
    def reddit_has_api(self) -> bool:
        return bool(self.reddit_client_id and self.reddit_client_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()
