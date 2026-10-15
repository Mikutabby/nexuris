"""Nexo 2.0 — Configuración central."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Base del proyecto
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Ruta al opencode.jsonc actual para extraer la API key de OpenRouter
# (sin imprimirla jamás)
_OPENCODE_CONFIG = Path.home() / ".config" / "opencode" / "opencode.jsonc"


def _load_openrouter_key() -> str | None:
    """Lee la API key de OpenRouter desde el config de opencode.

    Nunca retorna ni imprime la key en logs. Solo la devuelve para
    que el cliente LLM la use en memoria.
    """
    env = os.environ.get("NEXO_OPENROUTER_KEY") or os.environ.get("OPENROUTER_API_KEY")
    if env:
        return env
    try:
        import json
        import re

        raw = _OPENCODE_CONFIG.read_text()
        # opencode.jsonc puede tener comentarios — los removemos de forma simple
        raw = re.sub(r"^\s*//.*$", "", raw, flags=re.MULTILINE)
        raw = re.sub(r",\s*([}\]])", r"\1", raw)  # trailing commas
        data = json.loads(raw)
        key = (
            data.get("provider", {})
            .get("openrouter", {})
            .get("options", {})
            .get("apiKey")
        )
        if isinstance(key, str) and key.strip():
            return key.strip()
    except Exception:
        pass
    return None


@dataclass
class LLMConfig:
    """Configuración del cerebro (Claude vía OpenRouter)."""

    base_url: str = "https://openrouter.ai/api/v1"
    # Modelo actual. Cambiar a Claude cuando haya créditos en OpenRouter:
    #   "anthropic/claude-sonnet-5.5"  (mejor calidad/costo)
    #   "anthropic/claude-opus-5.5"    (tope)
    # Gratis mientras tanto (soporta tools):
    model: str = "nvidia/nemotron-3-super-120b-a12b:free"
    max_tokens: int = 4096
    temperature: float = 0.7
    api_key: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.api_key is None:
            self.api_key = _load_openrouter_key()


@dataclass
class AgentConfig:
    """Configuración del loop del agente."""

    max_turns: int = 8          # corte duro por consulta (estilo Claude Agent SDK)
    tool_timeout: float = 15.0  # segundos por tool
    system_prompt: str = ""     # se llena en runtime con identidad


@dataclass
class MemoryConfig:
    """Configuración de memoria."""

    db_path: Path = DATA_DIR / "nexuris.db"
    max_context_tokens: int = 8000  # presupuesto duro de retrieval
    facts_extraction: bool = True


@dataclass
class Config:
    llm: LLMConfig = field(default_factory=LLMConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    user_name: str = "miku"
    assistant_name: str = "Nexuris"


CONFIG = Config()
