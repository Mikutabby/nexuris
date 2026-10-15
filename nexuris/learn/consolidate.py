"""Nexo 2.0 — Consolidación en segundo plano (sleep-time / "sueño").

Patrón Letta/MemGPT: cuando el usuario no está, un pase consolida la
memoria — extrae hechos, escribe notas de estilo, dedupe.

Se dispara al cierre de sesión o por timer. NO corre en el hot path
de la voz.

Hace 3 cosas con UNA llamada LLM barata:
  1. Extrae hechos nuevos del historial (ADD-only, estilo Mem0).
  2. Escribe/actualiza notas de estilo (qué tono, qué funcionó).
  3. Actualiza los bloques human/persona si hubo aprendizaje.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from ..core.llm import LLMClient
from ..core.config import CONFIG
from ..memory.blocks import BLOCKS, BlockLabel
from ..memory.store import STORE

log = logging.getLogger("nexuris.learn")


@dataclass
class ConsolidationResult:
    facts: list[str]
    style_notes: str
    human_update: str | None
    persona_update: str | None


_CONSOLIDATE_PROMPT = """Sos Nexo consolidando tu memoria tras una conversación con miku.

Te doy el historial de la conversación. Extraé y devolvé SOLO un JSON con esta forma exacta:

{
  "facts": ["hecho nuevo 1", "hecho nuevo 2"],
  "style_notes": "observaciones sobre el tono/estilo que usó miku y qué funcionó",
  "human_update": "nueva versión del bloque human (lo que sabés de miku) o null si no cambió",
  "persona_update": "nueva versión del bloque persona (tu auto-concepto) o null si no cambió"
}

Reglas:
- facts: SOLO hechos nuevos, concretos, no repetir lo ya sabido. Máximo 5.
- style_notes: observaciones, NO reglas. Ej: "miku pidió respuestas más cortas hoy" no "siempre ser corto".
- human_update/persona_update: solo si hay algo genuinamente nuevo. Sino null.
- No inventes. Si no hay nada nuevo, devolvé lists vacías y nulls.

Historial:
<<<HISTORY>>>
"""


def consolidate(
    history: list[dict[str, Any]],
    llm: LLMClient | None = None,
) -> ConsolidationResult:
    """Pasa de consolidación sobre una sesión. Returns resultado."""
    llm = llm or LLMClient(CONFIG.llm)

    # serializa historial a texto
    lines = []
    for m in history:
        role = m.get("role", "?")
        if role == "system":
            continue
        content = m.get("content") or ""
        if isinstance(content, str) and content.strip():
            lines.append(f"{role}: {content}")
    history_text = "\n".join(lines[-60:])  # últimos 60 mensajes

    if not history_text.strip():
        return ConsolidationResult([], "", None, None)

    prompt = _CONSOLIDATE_PROMPT.replace("<<<HISTORY>>>", history_text)
    resp = llm.chat([{"role": "user", "content": prompt}])

    try:
        data = _parse_json(resp.text)
    except Exception:
        log.warning("Consolidación: no se pudo parsear JSON, usando texto crudo")
        return ConsolidationResult([], resp.text[:500], None, None)

    facts = [f for f in data.get("facts", []) if isinstance(f, str) and f.strip()]
    style_notes = data.get("style_notes") or ""
    human_update = data.get("human_update")
    persona_update = data.get("persona_update")

    # persiste hechos
    for fact in facts:
        STORE.add_fact(fact, {"source": "consolidation"})

    # actualiza bloques si hay cambio
    if human_update and human_update.strip() and human_update != "null":
        existing = BLOCKS.get(BlockLabel.HUMAN).value.strip()
        if human_update.strip() != existing:
            BLOCKS.update(BlockLabel.HUMAN, human_update.strip())
    if persona_update and persona_update.strip() and persona_update != "null":
        existing = BLOCKS.get(BlockLabel.PERSONA).value.strip()
        if persona_update.strip() != existing:
            BLOCKS.update(BlockLabel.PERSONA, persona_update.strip())

    # agrega notas de estilo al bloque style si hay
    if style_notes.strip():
        block = BLOCKS.get(BlockLabel.STYLE)
        note_entry = f"[nota estilo] {style_notes.strip()}"
        existing = block.value.strip()
        BLOCKS.update(BlockLabel.STYLE, (existing + "\n" + note_entry).strip())

    return ConsolidationResult(facts, style_notes, human_update, persona_update)


def _parse_json(text: str) -> dict[str, Any]:
    """Extrae JSON de la respuesta (puede venir con ```json ... ```)."""
    text = text.strip()
    if text.startswith("```"):
        # quita fence ```json ... ```
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()
    # busca el primer { ... }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    return json.loads(text)
