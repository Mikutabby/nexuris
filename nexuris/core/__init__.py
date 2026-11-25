"""Nexo 2.0 — core.

Imports LAZY: importar `nexuris.core.config` (o cualquier submódulo)
NO debe cargar `openai`/pydantic, que tardan ~10s en Python 3.14.
Eso hacía que el servidor MCP tardara demasiado en arrancar y opencode
lo diera por muerto en el handshake.

 Los símbolos LLMClient y Agent siguen disponibles con `from nexuris.core import ...`,
 pero solo se importan cuando se usan realmente.
"""
from .config import CONFIG

__all__ = ["CONFIG", "LLMClient", "Agent"]


def __getattr__(name: str):
    if name == "LLMClient":
        from .llm import LLMClient
        return LLMClient
    if name == "Agent":
        from .agent import Agent
        return Agent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
