"""PostgreSQL + pgvector-backed vector store (shared across laptops).

Embeddings live in the same Postgres database as the relational data, so
search results are identical on every machine. Requires the `vector`
extension (enabled by default on Neon/Supabase free tiers).

Metadata is stored as JSONB and filtered with SQL against `metadata->>'key'`.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import numpy as np
from sqlalchemy import text

from app.core.config import get_settings
from app.db.base import engine
from app.services.vectorstore.base import SearchResult, VectorStore

logger = logging.getLogger(__name__)

TABLE = "vector_rows"
EMBED_DIM = 512  # CLIP ViT-B-32 / OSNet feature dim used across the app


def _where_sql(filters: dict | None) -> tuple[str, dict]:
    """Translate {key: value | {op: value}} (+ $and/$or) into SQL over JSONB.

    Numeric metadata values (ts_epoch, camera_id, ...) are compared as
    float8/text-aware literals; string values compare as text.
    """
    if not filters:
        return "", {}

    clauses: list[str] = []
    params: dict[str, Any] = {}

    def _col(key: str, value) -> str:
        if isinstance(value, bool):
            return f"(metadata->>'{key}')::boolean"
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return f"(metadata->>'{key}')::float8"
        return f"metadata->>'{key}'"

    def walk(node: dict) -> None:
        if not node:
            return
        ands = node.get("$and")
        if isinstance(ands, list):
            for sub in ands:
                walk(sub)
            return
        ors = node.get("$or")
        if isinstance(ors, list):
            group_clauses: list[str] = []
            for i, sub in enumerate(ors):
                saved_len = len(clauses)
                walk(sub)
                group_clauses.append(" AND ".join(clauses[saved_len:]))
                del clauses[saved_len:]
            if group_clauses:
                clauses.append("(" + " OR ".join(f"({c})" for c in group_clauses) + ")")
            return
        for key, cond in node.items():
            ops: list[tuple[str, Any]] = []
            if isinstance(cond, dict) and set(cond) <= {"$eq", "$ne", "$in", "$gt", "$gte", "$lt", "$lte"}:
                for op, val in cond.items():
                    ops.append((op, val))
            else:
                ops.append(("$eq", cond))
            for op, val in ops:
                if val is None:
                    continue
                col = _col(key, val)
                pname = f"{key.replace('.', '_')}_{len(params)}"
                if op == "$in" and isinstance(val, (list, tuple)):
                    if not val:
                        continue
                    col = _col(key, val[0])
                    items = []
                    for j, v in enumerate(val):
                        items.append(f":{pname}_{j}")
                        params[f"{pname}_{j}"] = v
                    clauses.append(f"{col} IN ({', '.join(items)})")
                elif op in ("$eq", "$ne", "$gt", "$gte", "$lt", "$lte"):
                    sql_op = {"$eq": "=", "$ne": "<>", "$gt": ">", "$gte": ">=", "$lt": "<", "$lte": "<="}[op]
                    params[pname] = val
                    clauses.append(f"{col} {sql_op} :{pname}")

    walk(filters)
    if not clauses:
        return "", {}
    return " WHERE " + " AND ".join(f"({c})" for c in clauses), params


class PostgresVectorStore(VectorStore):
    def __init__(self) -> None:
        self._ensure_table()

    def _ensure_table(self) -> None:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(
                text(
                    f"""
                    CREATE TABLE IF NOT EXISTS {TABLE} (
                        id TEXT PRIMARY KEY,
                        embedding vector({EMBED_DIM}),
                        metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                        text TEXT,
                        seq BIGSERIAL
                    )
                    """
                )
            )
            try:
                conn.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS {TABLE}_hnsw ON {TABLE} "
                        "USING hnsw (embedding vector_cosine_ops)"
                    )
                )
            except Exception as exc:  # noqa: BLE001 - index is an optimization
                logger.debug("hnsw index not created: %s", exc)

    def add(self, ids, embeddings, metadatas, texts=None) -> None:
        if not ids:
            return
        rows = []
        for i, eid in enumerate(ids):
            emb = np.asarray(embeddings[i], dtype=np.float32)
            if emb.ndim == 1:
                emb = emb[None, :]
            if emb.shape[1] != EMBED_DIM:
                logger.warning("embedding dim %d != %d; skipping row", emb.shape[1], EMBED_DIM)
                continue
            meta = dict(metadatas[i] or {})
            txt = texts[i] if texts and i < len(texts) else None
            rows.append((str(eid), emb[0].tolist(), meta, txt))
        if not rows:
            return
        with engine.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO {TABLE} (id, embedding, metadata, text) "
                    "VALUES (:id, CAST(:emb AS vector), CAST(:meta AS jsonb), :txt) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                [
                    {"id": r[0], "emb": json.dumps(r[1]), "meta": json.dumps(r[2]), "txt": r[3]}
                    for r in rows
                ],
            )

    def query(self, embedding, top_k: int, filters: dict | None = None) -> list[SearchResult]:
        where, params = _where_sql(filters)
        emb = np.asarray(embedding, dtype=np.float32).reshape(1, -1)
        sql = text(
            f"SELECT id, 1.0 - (embedding <=> CAST(:emb AS vector)) AS score, metadata, text "
            f"FROM {TABLE}{where} "
            f"ORDER BY embedding <=> CAST(:emb AS vector) ASC LIMIT :k"
        )
        params["emb"] = json.dumps(emb[0].tolist())
        params["k"] = int(top_k)
        out = []
        with engine.connect() as conn:
            for row in conn.execute(sql, params):
                out.append(
                    SearchResult(
                        id=row.id,
                        score=float(max(0.0, min(1.0, row.score or 0.0))),
                        metadata=dict(row.metadata or {}),
                        text=row.text or "",
                    )
                )
        return out

    def get(self, filters: dict | None = None, limit: int | None = None) -> list[SearchResult]:
        where, params = _where_sql(filters)
        sql = text(
            f"SELECT id, metadata, text, embedding FROM {TABLE}{where} ORDER BY seq ASC"
            + (" LIMIT :limit" if limit else "")
        )
        if limit:
            params["limit"] = int(limit)
        out = []
        with engine.connect() as conn:
            for row in conn.execute(sql, params):
                emb = None
                if row.embedding is not None:
                    emb = np.asarray(row.embedding, dtype=np.float32)
                out.append(
                    SearchResult(
                        id=row.id,
                        score=0.0,
                        metadata=dict(row.metadata or {}),
                        text=row.text or "",
                        embedding=emb,
                    )
                )
        return out

    def count(self, filters: dict | None = None) -> int:
        where, params = _where_sql(filters)
        sql = text(f"SELECT count(*) FROM {TABLE}{where}")
        with engine.connect() as conn:
            return int(conn.execute(sql, params).scalar() or 0)

    def delete(self, ids=None, filters=None) -> int:
        if not ids and not filters:
            return 0
        where, params = _where_sql(filters)
        if ids:
            ids = [str(i) for i in ids]
            with engine.begin() as conn:
                res = conn.execute(
                    text(f"DELETE FROM {TABLE} WHERE id = ANY(:ids)"), {"ids": ids}
                )
            return res.rowcount or 0
        with engine.begin() as conn:
            res = conn.execute(text(f"DELETE FROM {TABLE}{where}"), params)
        return res.rowcount or 0

    def compact(self) -> dict:
        try:
            with engine.begin() as conn:
                conn.execute(text("VACUUM"))
        except Exception:  # noqa: BLE001 - serverless Postgres may not allow VACUUM
            pass
        return {"backend": "pgvector", "rows": self.count(), "mode": "no-op"}

    def name(self) -> str:
        return "pgvector"
