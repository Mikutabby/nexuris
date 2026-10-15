"""Nexo 2.0 — Loop del agente (ReAct con Claude).

Un solo ciclo, igual que todos los agentes serios del 2026:

    LLM → ¿pide tool_calls? → ejecutar → append resultado → repetir
         → si no pide tools → respuesta final

Diseño: mínimo, composable, sin frameworks pesados (research: OpenAI/
Anthropic/ADK hacen esencialmente lo mismo; los frameworks grandes son
dead weight en 4GB RAM).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from .llm import LLMClient, LLMResponse, ToolCall
from ..tools.registry import REGISTRY, Permission, ToolRegistry

log = logging.getLogger("nexuris.agent")


@dataclass
class AgentState:
    """Estado de una consulta."""

    messages: list[dict[str, Any]] = field(default_factory=list)
    turns: int = 0
    tool_log: list[dict[str, Any]] = field(default_factory=list)


# Callback para pedir confirmación humana (ASK permission).
# Por defecto: auto-aprueba en modo test, en producción lo provee la capa de voz/UI.
ConfirmFn = Callable[[str, dict[str, Any]], bool]


def _default_confirm(tool_name: str, args: dict[str, Any]) -> bool:
    """Confirmación por defecto. En el loop de prueba aprueba; la UI real la overridea."""
    return True


class Agent:
    """Agente Nexo: loop ReAct + tools nativas + permisos.

    El system prompt puede ser un string fijo o una función que se re-evalúa
    en cada run (para inyectar bloques de memoria frescos — anti-drift).
    """

    def __init__(
        self,
        llm: LLMClient | None = None,
        registry: ToolRegistry | None = None,
        system_prompt: str | Callable[[], str] = "",
        max_turns: int = 8,
        confirm: ConfirmFn | None = None,
    ) -> None:
        self.llm = llm or LLMClient()
        self.registry = registry or REGISTRY
        self._system_prompt_source = system_prompt
        self.system_prompt = system_prompt() if callable(system_prompt) else system_prompt
        self.max_turns = max_turns
        self.confirm = confirm or _default_confirm

    def _current_system_prompt(self) -> str:
        if callable(self._system_prompt_source):
            return self._system_prompt_source()
        return self.system_prompt

    def run(self, user_input: str, history: list[dict[str, Any]] | None = None) -> str:
        """Procesa una consulta del usuario. Retorna la respuesta final."""
        messages: list[dict[str, Any]] = []
        sys_prompt = self._current_system_prompt()
        if sys_prompt:
            messages.append({"role": "system", "content": sys_prompt})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_input})

        tools = self.registry.specs()

        for turn in range(self.max_turns):
            resp: LLMResponse = self.llm.chat(messages, tools=tools)

            if not resp.tool_calls:
                # Respuesta final del modelo
                return resp.text

            # Hay tool_calls: primero agregamos el mensaje del asistente
            messages.append(resp.raw_message)

            for tc in resp.tool_calls:
                result = self._execute_tool(tc)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    }
                )

        # Se agotaron los turnos sin respuesta final
        return "[Nexo: se alcanzó el máximo de pasos sin respuesta final]"

    def _execute_tool(self, tc: ToolCall) -> dict[str, Any]:
        """Ejecuta una tool respetando permisos. Siempre retorna un dict."""
        tool = self.registry.get(tc.name)
        if tool is None:
            return {"ok": False, "error": f"Tool desconocida: {tc.name}"}

        if tool.permission == Permission.DENY:
            return {"ok": False, "error": f"Tool bloqueada por permisos: {tc.name}"}

        if tool.permission == Permission.ASK:
            approved = self.confirm(tc.name, tc.arguments)
            if not approved:
                return {"ok": False, "error": "El usuario denegó esta acción."}

        try:
            result = tool.invoke(tc.arguments)
            return {"ok": True, "result": result}
        except Exception as e:  # noqa: BLE001 — el agente debe ver el error y recuperarse
            log.exception("Error ejecutando %s", tc.name)
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
