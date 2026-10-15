"""Nexo 2.0 — Cliente LLM (Claude vía OpenRouter, formato OpenAI-compatible).

Un único cerebro: Claude. El cliente es deliberadamente fino — el loop
del agente (agent.py) orquesta, esto solo habla con la API.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

from .config import CONFIG, LLMConfig


@dataclass
class ToolCall:
    """Una llamada a herramienta pedida por el modelo."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """Respuesta del modelo para un turno."""

    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw_message: dict[str, Any] = field(default_factory=dict)
    stop_reason: str | None = None


class LLMClient:
    """Cliente fino sobre OpenAI-compatible (OpenRouter)."""

    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or CONFIG.llm
        if not self.config.api_key:
            raise RuntimeError(
                "No hay API key de OpenRouter. "
                "Setea NEXO_OPENROUTER_KEY o OPENROUTER_API_KEY."
            )
        self._client = OpenAI(
            base_url=self.config.base_url,
            api_key=self.config.api_key,
        )

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Un turno del modelo. Si pide tool_calls, viene en la respuesta."""
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        resp = self._client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        msg = choice.message

        text = msg.content or ""
        tool_calls: list[ToolCall] = []
        if getattr(msg, "tool_calls", None):
            import json

            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {"_raw": tc.function.arguments}
                tool_calls.append(
                    ToolCall(id=tc.id, name=tc.function.name, arguments=args)
                )

        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            raw_message={
                "role": "assistant",
                "content": msg.content,
                **(
                    {"tool_calls": msg.tool_calls}
                    if getattr(msg, "tool_calls", None)
                    else {}
                ),
            },
            stop_reason=choice.finish_reason,
        )
