"""Nexo 2.0 — Sesión delegada en opencode (camino A).

Misma interfaz que Session (ask/feedback/close), pero el cerebro vive en
opencode: cada turno va a una sesión con agent=nexuris. La memoria local
(bloques + lecciones de feedback) se pushea como instruction entries
antes de cada turno, así la sesión delegada piensa con la misma memoria
que la CLI standalone.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from .core.config import DATA_DIR, load_user_config
from .core.opencode_backend import (
    CloudTextLLM,
    OpenCodeClient,
    OpenCodeError,
    ensure_available,
)
from .learn.consolidate import ConsolidationResult, consolidate
from .learn.feedback import (
    FeedbackEvent,
    FeedbackKind,
    feedback_context_block,
    record_feedback,
)
from .memory.blocks import BLOCKS

log = logging.getLogger("nexuris.cloud")

# Si la consolidación falla (p. ej. rate limit de modelos gratis), el
# historial queda acá y se reintenta en el próximo arranque.
PENDING_PATH = DATA_DIR / "pending_consolidation.json"


class CloudSession:
    """Sesión de conversación delegada en opencode."""

    def __init__(self, model: str | None = None) -> None:
        ensure_available()
        if model is None:
            # respeta el modelo guardado con /modelo (salvo el legacy de OpenRouter)
            saved = load_user_config().get("model")
            if isinstance(saved, str) and "/" in saved and not saved.startswith("openrouter/"):
                model = saved
        self.client = OpenCodeClient(model)
        self.session_id = self.client.create_session(
            title=f"Nexuris CLI {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        self.history: list[dict[str, str]] = []
        self._pushed_state: tuple[str, str] | None = None  # (bloques, lecciones)
        self.pending_saved = False
        log.info("sesión opencode creada: %s (%s)", self.session_id, self.client.model)
        self._retry_pending()

    # ---- memoria → instruction entries ----

    def _memory_entries(self) -> dict[str, str]:
        entries = {"nexuris.memory": BLOCKS.context_string()}
        lessons = feedback_context_block()
        if lessons.strip():
            entries["nexuris.lessons"] = lessons
        return entries

    def sync_memory(self, force: bool = False) -> bool:
        """Empuja la memoria a la sesión si cambió desde el último push."""
        entries = self._memory_entries()
        state = (
            entries.get("nexuris.memory", ""),
            entries.get("nexuris.lessons", ""),
        )
        if not force and state == self._pushed_state:
            return False
        self.client.put_instructions(self.session_id, entries)
        self._pushed_state = state
        return True

    # ---- interfaz estándar ----

    def ask(self, user_input: str) -> str:
        """Un turno. Sincroniza memoria y delega en opencode."""
        try:
            self.sync_memory()
        except OpenCodeError as exc:
            # sin memoria fresca el turno igual puede salir — se avisa en log
            log.warning("no pude sincronizar memoria: %s", exc)
        reply = self.client.run_turn(self.session_id, user_input)
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

    def set_model(self, spec: str) -> str:
        """Cambia el modelo de la sesión delegada."""
        return self.client.set_model(self.session_id, spec)

    @property
    def model(self) -> str:
        return self.client.model

    def close(self, llm=None) -> ConsolidationResult | None:
        """Cierra la sesión y dispara la consolidación (sleep-time).

        Si falla (p. ej. rate limit), el historial queda en un archivo
        pendiente que se reintenta en el próximo arranque — no se pierde
        el sueño de la sesión.
        """
        if len(self.history) < 2:
            return None
        try:
            result = consolidate(self.history, llm=llm or CloudTextLLM(self.client))
        except Exception as exc:  # noqa: BLE001 — sin traceback al usuario
            reason = "rate limit de modelos gratis" if "rate_limit" in str(exc) else str(exc)[:120]
            log.warning("consolidación falló (%s) — quedó pendiente", reason)
            self._save_pending()
            self.pending_saved = True
            return None
        self._clear_pending()
        log.info(
            "Consolidación: %d facts, style=%d chars",
            len(result.facts),
            len(result.style_notes),
        )
        return result

    # ---- consolidación pendiente ----

    def _save_pending(self) -> None:
        """Acumula el historial sin consolidar (merge con un pendiente previo)."""
        try:
            old: list[dict[str, str]] = []
            if PENDING_PATH.exists():
                old = json.loads(PENDING_PATH.read_text(encoding="utf-8")).get("history", [])
            merged = old + self.history
            PENDING_PATH.write_text(
                json.dumps({"history": merged[-200:]}, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("no pude guardar consolidación pendiente: %s", exc)

    def _clear_pending(self) -> None:
        try:
            PENDING_PATH.unlink(missing_ok=True)
        except OSError:
            pass

    def _retry_pending(self) -> None:
        """Reintenta consolidar lo que quedó pendiente del arranque anterior."""
        if not PENDING_PATH.exists():
            return
        try:
            data = json.loads(PENDING_PATH.read_text(encoding="utf-8"))
            history = data.get("history", [])
        except (OSError, ValueError):
            self._clear_pending()
            return
        if len(history) < 2:
            self._clear_pending()
            return
        try:
            result = consolidate(history, llm=CloudTextLLM(self.client))
            self._clear_pending()
            log.info("consolidación pendiente completada: %d facts", len(result.facts))
        except Exception as exc:  # noqa: BLE001
            reason = "rate limit" if "rate_limit" in str(exc) else str(exc)[:80]
            log.info("consolidación pendiente sigue en espera (%s)", reason)
