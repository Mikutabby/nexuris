"""Nexo 2.0 — Sesión: agrupa turnos, registra historial, consolida al cerrar.

Envuelve al Agent para:
  - mantener historial en memoria durante la sesión
  - inyectar lecciones de feedback en el system prompt
  - al cerrar, disparar la consolidación (sleep-time)
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from .core.agent import Agent
from .learn.consolidate import consolidate, ConsolidationResult
from .learn.feedback import FeedbackEvent, FeedbackKind, record_feedback, feedback_context_block

log = logging.getLogger("nexuris.session")


class Session:
    """Sesión de conversación con un Agent Nexo."""

    def __init__(self, agent: Agent) -> None:
        self.agent = agent
        self.history: list[dict[str, Any]] = []
        # envuelve el system prompt para inyectar lecciones de feedback
        self._base_prompt_fn = agent._system_prompt_source
        agent._system_prompt_source = self._prompt_with_lessons

    def _prompt_with_lessons(self) -> str:
        base = (
            self._base_prompt_fn()
            if callable(self._base_prompt_fn)
            else self.agent.system_prompt
        )
        lessons = feedback_context_block()
        if lessons:
            return base + "\n\n" + lessons
        return base

    def ask(self, user_input: str) -> str:
        """Un turno. Guarda historial para consolidación posterior."""
        reply = self.agent.run(user_input, history=self.history)
        # registra en historial
        self.history.append({"role": "user", "content": user_input})
        self.history.append({"role": "assistant", "content": reply})
        return reply

    def feedback(self, kind: FeedbackKind | str, context: str = "", detail: str = "") -> str:
        """Registra feedback del usuario sobre la última respuesta."""
        if isinstance(kind, str):
            kind = FeedbackKind(kind)
        if not context and self.history:
            context = self.history[-1].get("content", "")[:200]
        return record_feedback(FeedbackEvent(kind=kind, context=context, detail=detail))

    def close(self, llm=None) -> ConsolidationResult | None:
        """Cierra la sesión y dispara la consolidación (sleep-time)."""
        if len(self.history) < 2:
            return None
        try:
            result = consolidate(self.history, llm=llm)
            log.info(
                "Consolidación: %d facts, style=%d chars",
                len(result.facts),
                len(result.style_notes),
            )
            return result
        except Exception:
            log.exception("Error en consolidación")
            return None
