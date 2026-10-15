"""Nexo 2.0 — Bootstrap: ensambla tools + agente con filosofía de aprendizaje.

Filosofía (research 2026):
  - System prompt MÍNIMO: solo rol + piso de seguridad + contratos de tool.
  - La personalidad NO se scriptea — emerge de la memoria (bloques auto-editables
    con ejemplos, no reglas) y de la convergencia natural al estilo del usuario.
  - Seguridad SIEMPRE en código, nunca aprendida.
"""
from __future__ import annotations

from .core.agent import Agent
from .core.config import CONFIG
from .core.llm import LLMClient
from .memory.blocks import BLOCKS
from .tools.registry import REGISTRY


def build_agent(
    model: str | None = None,
    extra_system: str | None = None,
) -> Agent:
    """Carga todas las tools y devuelve un Agent listo.

    El system prompt se arma en runtime: rol mínimo + bloques de memoria
    (que el agente va a editar con el tiempo).
    """
    # carga tools core + de memoria (el decorador las auto-registra)
    from .tools import core as _core  # noqa: F401
    from .tools import memory_tools as _mem  # noqa: F401

    if model:
        CONFIG.llm.model = model

    # system_prompt como FUNCIÓN: se re-evalúa en cada run para inyectar
    # los bloques de memoria frescos (anti-drift, research: -47% drift).
    system_prompt_fn = lambda: _compose_system_prompt(extra_system)  # noqa: E731
    CONFIG.agent.system_prompt = system_prompt_fn()

    return Agent(
        llm=LLMClient(CONFIG.llm),
        registry=REGISTRY,
        system_prompt=system_prompt_fn,
        max_turns=CONFIG.agent.max_turns,
    )


def _compose_system_prompt(extra: str | None = None) -> str:
    """Rol mínimo + bloques de memoria. Sin guion de personalidad.

    Siguiendo la evidencia:
      - Anthropic: "rol en una frase hace diferencia"; ejemplos > reglas para tono.
      - EACL 2026: personas scripteadas restan instruction-following y decaen.
      - La personalidad emerge de la convergencia natural + memoria, no del prompt.
    """
    role = (
        "Sos Nexo, el asistente del hogar de miku. "
        "Respondés en español. Usás las herramientas disponibles para ayudar "
        "con el sistema, archivos, memoria y tareas del hogar."
    )

    safety = (
        "Piso de seguridad (no negociable, también enforced en código): "
        "nunca expongas contraseñas, tokens o secretos. "
        "Ante acciones destructivas o irreversibles, la herramienta pide confirmación: "
        "en ese caso explicale a miku qué vas a hacer y esperá."
    )

    contracts = (
        "Cuando necesités información o una acción, llamá la herramienta correspondiente. "
        "Si una tool falla, leen el error y recuperate. "
        "Cuando termines de usar tools, respondé con tu respuesta final en texto."
    )

    parts = [role, safety, contracts]

    # inyecta bloques de memoria (lo que el agente fue aprendiendo)
    blocks_ctx = BLOCKS.context_string()
    if blocks_ctx.strip():
        parts.append(
            "Memoria persistente (actualizala con update_memory_block cuando aprendas algo nuevo):\n"
            + blocks_ctx
        )

    if extra:
        parts.append(extra)

    return "\n\n".join(parts)


def refresh_system_prompt(agent: Agent) -> None:
    """Recompone el system prompt tras editar bloques (anti-drift: reinyectar)."""
    agent.system_prompt = _compose_system_prompt()
    # reemplaza el system message en mensajes si existiera
    for i, m in enumerate(agent._last_messages if hasattr(agent, "_last_messages") else []):
        if m.get("role") == "system":
            m["content"] = agent.system_prompt
            break
