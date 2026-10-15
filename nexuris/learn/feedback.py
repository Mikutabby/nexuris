"""Nexo 2.0 — Loop de feedback (señales → lecciones).

Patrón (IEvoAgent ACL 2026 + Reflexion): el feedback del usuario —
explícito o implícito — se convierte en lecciones verbales que se
inyectan en próximas sesiones. Sin reentrenar el modelo.

Señales implícitas que instrumentamos:
  - repitió la instrucción  → la respuesta anterior falló
  - pidió cambio/rehacer    → no le gustó
  - aceptó y siguió         → funcionó
  - ignoró/cambió de tema   → puede haber fallado

Cada señal se guarda como fact con tag [feedback]. Periódicamente
(unas N sesiones) se puede reflexionar sobre ellas (GEPA-lite).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum

from ..memory.store import STORE


class FeedbackKind(str, Enum):
    ACCEPTED = "accepted"      # le gustó / siguió la sugerencia
    CORRECTED = "corrected"    # pidió cambio / rehizo
    REPEATED = "repeated"      # repitió la instrucción (falló)
    IGNORED = "ignored"        # ignoró / cambió de tema
    EXPLICIT_POS = "explicit_pos"   # dijo que estuvo bien
    EXPLICIT_NEG = "explicit_neg"   # dijo que estuvo mal


@dataclass
class FeedbackEvent:
    kind: FeedbackKind
    context: str          # qué pasó (respuesta de nexuris o situación)
    detail: str = ""      # detalle extra
    timestamp: float = 0.0


def record_feedback(event: FeedbackEvent) -> str:
    """Registra un evento de feedback como fact."""
    if event.timestamp == 0.0:
        event.timestamp = time.time()
    content = f"[feedback:{event.kind.value}] {event.context}"
    if event.detail:
        content += f" — {event.detail}"
    STORE.add_fact(content, {"kind": "feedback", "feedback_kind": event.kind.value})
    return f"Feedback registrado: {event.kind.value}"


def recent_lessons(limit: int = 10) -> list[str]:
    """Últimas lecciones de feedback para inyectar en contexto."""
    hits = STORE.search("feedback", limit=limit * 2)
    lessons = [h.content for h in hits if h.content.startswith("[feedback:")]
    return lessons[:limit]


def feedback_context_block() -> str:
    """Bloque compacto de lecciones para inyectar en el system prompt."""
    lessons = recent_lessons(limit=8)
    if not lessons:
        return ""
    joined = "\n".join(f"- {l}" for l in lessons)
    return (
        "Lecciones de interacciones anteriores (aprendé de esto, no son reglas):\n"
        + joined
    )
