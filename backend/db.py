"""SQLite engine + session. One file, no server. `init_db()` creates tables on
startup (fine for a young schema; swap in Alembic when it stabilizes)."""
import os
from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings

_url = get_settings().database_url
# Ensure the parent dir for a file-backed sqlite url exists (e.g. data/).
if _url.startswith("sqlite:///"):
    path = _url.replace("sqlite:///", "", 1)
    if path and path != ":memory:":
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

engine = create_engine(_url, connect_args={"check_same_thread": False})


def init_db() -> None:
    # Import models so SQLModel registers every table before create_all.
    from . import models  # noqa: F401

    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
