"""The domain, kept small on purpose.

A **storefront** is a store built around one agent-determined category/audience.
A **niche** is a research finding -- a slice of demand with a saturation rating
-- that may or may not get promoted into a storefront. A **product** is a CJ
item matched to a niche (Feature 2 fills these in). A **research run** is one
invocation of the agent, kept so the UI can show history.

JSON-ish lists (images, keywords, sources) are stored as JSON columns to keep
the schema flat while the shape is still moving.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Storefront(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    slug: str = Field(index=True, unique=True)
    name: str
    category: str = ""
    audience: str = ""
    description: str = ""
    status: str = "draft"  # draft | active | archived
    created_at: datetime = Field(default_factory=_now)


class Niche(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    storefront_id: Optional[int] = Field(default=None, foreign_key="storefront.id", index=True)
    research_run_id: Optional[int] = Field(default=None, foreign_key="researchrun.id", index=True)
    name: str
    audience: str = ""
    rationale: str = ""
    # Honest proxies, 0-100. demand from Reddit/keyword breadth; saturation
    # reasoned by the model. Higher demand + lower saturation = better.
    demand: int = 0
    saturation: int = 0
    saturation_reasoning: str = ""
    example_products: list = Field(default_factory=list, sa_column=Column(JSON))
    keywords: list = Field(default_factory=list, sa_column=Column(JSON))
    sources: list = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)


class Product(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    storefront_id: Optional[int] = Field(default=None, foreign_key="storefront.id", index=True)
    niche_id: Optional[int] = Field(default=None, foreign_key="niche.id", index=True)
    title: str
    description: str = ""
    cj_product_id: str = ""  # filled by the CJ matcher (Feature 2)
    price: Optional[float] = None
    images: list = Field(default_factory=list, sa_column=Column(JSON))
    videos: list = Field(default_factory=list, sa_column=Column(JSON))
    source: str = ""  # e.g. "cjdropshipping"
    status: str = "candidate"  # candidate | approved | published
    created_at: datetime = Field(default_factory=_now)


class ResearchRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    prompt: str
    audience: str = ""
    model: str = ""
    # Full agent output snapshot (candidates, threads sampled, keywords).
    result: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)
