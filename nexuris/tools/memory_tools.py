"""Nexo 2.0 — Tools de memoria auto-editable (el agente se maneja su memoria).

Patrón Letta: el agente edita sus bloques `human` y `persona` con tools.
`style` guarda EJEMPLOS de turnos, no reglas. `safety` es read-only.
"""
from __future__ import annotations

import time
from typing import Any

from .registry import Permission, tool
from ..memory.blocks import BLOCKS, BlockLabel
from ..memory.store import STORE


@tool(
    name="update_memory_block",
    description=(
        "Edita un bloque de tu memoria persistente. "
        "Usá 'human' para lo que aprendés de miku, 'persona' para tu auto-concepto. "
        "'safety' es de solo lectura. Reemplaza el contenido completo del bloque."
    ),
    permission=Permission.ALLOW,
    tags=["memory"],
)
def update_memory_block(block: str, content: str) -> str:
    """El agente reescribe sus propios bloques de memoria."""
    try:
        label = BlockLabel(block)
    except ValueError:
        return f"Bloque inválido: {block}. Opciones: human, persona, style, safety."
    ok, msg = BLOCKS.update(label, content)
    return msg


@tool(
    name="add_style_example",
    description=(
        "Guarda un EJEMPLO de interacción (no una regla). "
        "Entrada de miku + tu respuesta que funcionó. "
        "El estilo se aprende de muestras, no de instrucciones."
    ),
    permission=Permission.ALLOW,
    tags=["memory", "style"],
)
def add_style_example(user_msg: str, assistant_reply: str, note: str = "") -> str:
    """Agrega un ejemplo de estilo al bloque style."""
    block = BLOCKS.get(BlockLabel.STYLE)
    example = f"---\nUsuario: {user_msg}\nAsistente: {assistant_reply}"
    if note:
        example += f"\nNota: {note}"
    existing = block.value.strip()
    new_value = (existing + "\n" + example).strip()
    # mantener últimos ~15 ejemplos (los más recientes arriba)
    entries = [e for e in new_value.split("\n---\n") if e.strip()]
    entries = entries[-15:]
    BLOCKS.update(BlockLabel.STYLE, "\n---\n".join(entries))
    return f"Ejemplo guardado. Total ejemplos: {len(entries)}"


@tool(
    name="remember_fact",
    description="Guarda un hecho permanente y searchable sobre miku o el mundo.",
    permission=Permission.ALLOW,
    tags=["memory"],
)
def remember_fact(fact: str) -> str:
    """Hecho ADD-only en el store searchable."""
    mid = STORE.add_fact(fact)
    return f"Hecho guardado: {mid[:8]}"


@tool(
    name="recall_facts",
    description="Busca hechos guardados previamente por relevancia.",
    permission=Permission.ALLOW,
    tags=["memory"],
)
def recall_facts(query: str) -> list[dict[str, Any]]:
    """Recupera hechos relevantes."""
    hits = STORE.search(query)
    return [{"content": n.content, "created": n.created_at} for n in hits]


@tool(
    name="observe_user_feedback",
    description=(
        "Registra una observación sobre cómo reaccionó miku a algo "
        "(aceptó, corrigió, ignoró, pidió cambio). Se usa para aprender."
    ),
    permission=Permission.ALLOW,
    tags=["memory", "feedback"],
)
def observe_user_feedback(observation: str) -> str:
    """Feedback implícito → lección guardada."""
    STORE.add_fact(f"[feedback] {observation}", {"kind": "feedback"})
    return "Observación registrada."
