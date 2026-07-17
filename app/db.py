"""A tiny generic JSON document store on SQLite, shared by every agent.

One table, `documents`, holds arbitrary JSON blobs discriminated by a
`collection` name and queryable by their JSON properties (SQLite's json1
`json_extract`). Agents get a schemaless place to accumulate data without a
migration per shape:

    await db.insert("readings", {...}, dedup_key=url)  # False if the key exists
    await db.find("readings", where={"kind": "temperature"},
                  order_by="value", desc=True, limit=20)
    await db.count("readings")

The file lives on a mounted volume (DB_PATH -> /data/agents.db in compose) so
it persists on the cluster master across container restarts. WAL mode lets
background writers work while the API reads.

Queries filter/sort by scalar JSON properties (json_extract on a path like
"$.match_score"); a plain "match_score" is treated as "$.match_score". Array
membership isn't expressible this way -- store scalars for anything you want to
filter on.
"""
import json
import os
from typing import Any

import aiosqlite

DB_PATH = os.environ.get("DB_PATH", "data/agents.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    collection TEXT NOT NULL,
    dedup_key  TEXT,
    data       TEXT NOT NULL,                       -- JSON
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_documents_collection ON documents(collection);
CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_dedup
    ON documents(collection, dedup_key) WHERE dedup_key IS NOT NULL;
"""


def _path(prop: str) -> str:
    """Accept "match_score" or "$.match_score"; return a json1 path."""
    return prop if prop.startswith("$") else f"$.{prop}"


async def init() -> None:
    """Create the file + schema if absent. Safe to call on every startup."""
    directory = os.path.dirname(DB_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.executescript(_SCHEMA)
        await conn.commit()


async def insert(collection: str, data: dict, dedup_key: str | None = None) -> bool:
    """Insert one document. With a dedup_key, a second insert of the same
    (collection, dedup_key) is ignored -- returns True only when a row was
    actually written."""
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute(
            "INSERT OR IGNORE INTO documents(collection, dedup_key, data) "
            "VALUES (?, ?, ?)",
            (collection, dedup_key, json.dumps(data)))
        await conn.commit()
        return cur.rowcount > 0


async def replace(collection: str, dedup_key: str, data: dict) -> bool:
    """Overwrite the document at (collection, dedup_key) with `data`;
    inserts it if absent. Returns True when a row was written."""
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute(
            "UPDATE documents SET data = ? WHERE collection = ? AND dedup_key = ?",
            (json.dumps(data), collection, dedup_key))
        if cur.rowcount == 0:
            cur = await conn.execute(
                "INSERT OR IGNORE INTO documents(collection, dedup_key, data) "
                "VALUES (?, ?, ?)", (collection, dedup_key, json.dumps(data)))
        await conn.commit()
        return cur.rowcount > 0


async def exists(collection: str, dedup_key: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute(
            "SELECT 1 FROM documents WHERE collection = ? AND dedup_key = ? "
            "LIMIT 1", (collection, dedup_key))
        return await cur.fetchone() is not None


async def find(collection: str, where: dict[str, Any] | None = None,
               order_by: str | None = None, desc: bool = True,
               limit: int | None = None) -> list[dict]:
    """Return documents in `collection`, optionally filtered by equality on
    JSON properties and ordered by one. `where`/`order_by` keys are JSON
    property names ("verdict", "match_score")."""
    sql = ["SELECT data FROM documents WHERE collection = ?"]
    params: list[Any] = [collection]
    for prop, value in (where or {}).items():
        sql.append("AND json_extract(data, ?) = ?")
        params += [_path(prop), value]
    if order_by:
        sql.append(f"ORDER BY json_extract(data, ?) {'DESC' if desc else 'ASC'}")
        params.append(_path(order_by))
    if limit is not None:
        sql.append("LIMIT ?")
        params.append(int(limit))
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute(" ".join(sql), params)
        rows = await cur.fetchall()
    return [json.loads(r[0]) for r in rows]


async def count(collection: str, where: dict[str, Any] | None = None) -> int:
    sql = ["SELECT COUNT(*) FROM documents WHERE collection = ?"]
    params: list[Any] = [collection]
    for prop, value in (where or {}).items():
        sql.append("AND json_extract(data, ?) = ?")
        params += [_path(prop), value]
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute(" ".join(sql), params)
        row = await cur.fetchone()
    return row[0] if row else 0
