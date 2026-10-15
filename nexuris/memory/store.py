"""Nexo 2.0 — Memoria unificada (SQLite).

Un solo store, 4 capas (patrón research 2026):
  L0  identidad/preferencias siempre en contexto (bloque fijo)
  L1  hilos de conversación (persistencia por thread)
  L2  hechos a largo plazo (extracción estilo Mem0, ADD-only)
  L3  procesamiento en segundo plano (dedup, resumen diario)

Hoy implemento L1 + L2 + búsqueda híbrida (keyword + embeddings si hay).
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.config import CONFIG


@dataclass
class MemoryNode:
    id: str
    kind: str          # "fact" | "conversation" | "summary"
    content: str
    data: dict[str, Any]
    created_at: float
    access_count: int = 0


class MemoryStore:
    """Store unificado en SQLite. Sin dependencias externas."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or CONFIG.memory.db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    data TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    access_count INTEGER NOT NULL DEFAULT 0,
                    embedding BLOB
                );
                CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories(kind);
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                    USING fts5(content, content='memories', content_rowid='rowid');
                """
            )

    # ---------- L2: hechos a largo plazo ----------

    def add_fact(self, content: str, data: dict[str, Any] | None = None) -> str:
        """Agrega un hecho (ADD-only, nunca reescribe historia)."""
        mid = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO memories (id, kind, content, data, created_at) "
                "VALUES (?, 'fact', ?, ?, ?)",
                (mid, content, json.dumps(data or {}, ensure_ascii=False), time.time()),
            )
            conn.execute(
                "INSERT INTO memories_fts(rowid, content) "
                "VALUES ((SELECT rowid FROM memories WHERE id=?), ?)",
                (mid, content),
            )
        return mid

    def search(self, query: str, limit: int = 8) -> list[MemoryNode]:
        """Búsqueda híbrida: keyword (FTS) con fallback LIKE."""
        results: list[MemoryNode] = []
        with self._connect() as conn:
            try:
                rows = conn.execute(
                    "SELECT m.* FROM memories_fts f "
                    "JOIN memories m ON m.rowid = f.rowid "
                    "WHERE memories_fts MATCH ? ORDER BY rank LIMIT ?",
                    (query, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            if not rows:
                rows = conn.execute(
                    "SELECT * FROM memories WHERE content LIKE ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (f"%{query}%", limit),
                ).fetchall()
            for r in rows:
                results.append(self._row_to_node(r))
                # bump access
                conn.execute(
                    "UPDATE memories SET access_count = access_count + 1 WHERE id=?",
                    (r["id"],),
                )
        return results

    def recent_facts(self, limit: int = 20) -> list[MemoryNode]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memories WHERE kind='fact' "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_node(r) for r in rows]

    def count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    @staticmethod
    def _row_to_node(row: sqlite3.Row) -> MemoryNode:
        try:
            data = json.loads(row["data"])
        except json.JSONDecodeError:
            data = {}
        return MemoryNode(
            id=row["id"],
            kind=row["kind"],
            content=row["content"],
            data=data,
            created_at=row["created_at"],
            access_count=row["access_count"],
        )


# Singleton cómodo
STORE = MemoryStore()
