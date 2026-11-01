"""Nexo 2.0 — Configuración central."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Base del proyecto (directorio del paquete)
BASE_DIR = Path(__file__).resolve().parent.parent
# Raíz del repo (donde está pyproject.toml) — para compatibilidad de datos viejos
REPO_DIR = BASE_DIR.parent


def _writable(path: Path) -> bool:
    """True si el directorio existe (o se puede crear) y se puede escribir."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.touch()
        probe.unlink()
        return True
    except OSError:
        return False


def _resolve_data_dir() -> Path:
    """Dónde guardar la memoria (hechos, bloques, DB).

    Orden:
      1. $NEXURIS_DATA_DIR (o $NEXO_DATA_DIR) — override explícito.
      2. Datos legacy dentro del repo (nexuris/data o data/) si ya existen,
         para no perder memoria de instalaciones anteriores.
      3. $XDG_DATA_HOME/nexuris (o ~/.local/share/nexuris) — lo correcto
         cuando el paquete se instala fuera del repo, en cualquier distro.
      4. Tempdir — último recurso si nada es escribible.
    """
    for var in ("NEXURIS_DATA_DIR", "NEXO_DATA_DIR"):
        env = os.environ.get(var)
        if env:
            path = Path(env).expanduser()
            if _writable(path):
                return path
            raise SystemExit(f"{var}={env} no es escribible")

    for legacy in (BASE_DIR / "data", REPO_DIR / "data"):
        if (legacy / "nexuris.db").exists() or (legacy / "blocks.json").exists():
            return legacy

    xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    candidate = Path(xdg) / "nexuris"
    if _writable(candidate):
        return candidate

    import tempfile

    fallback = Path(tempfile.gettempdir()) / "nexuris"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


DATA_DIR = _resolve_data_dir()

# Modelo al que se cae si el configurado ya no existe en OpenRouter
FALLBACK_MODEL = "openrouter/free"

# Ruta al opencode.jsonc actual para extraer la API key de OpenRouter
# (sin imprimirla jamás)
_OPENCODE_CONFIG = Path.home() / ".config" / "opencode" / "opencode.jsonc"


def _load_openrouter_key() -> str | None:
    """Lee la API key de OpenRouter desde el config de opencode.

    Nunca retorna ni imprime la key en logs. Solo la devuelve para
    que el cliente LLM la use en memoria.
    """
    env = (
        os.environ.get("NEXURIS_OPENROUTER_KEY")
        or os.environ.get("NEXO_OPENROUTER_KEY")
        or os.environ.get("OPENROUTER_API_KEY")
    )
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
    # Default durable: el router gratuito de OpenRouter (soporta tools).
    # Cambialo con NEXURIS_MODEL o NEXO_MODEL sin tocar código.
    model: str = field(
        default_factory=lambda: os.environ.get("NEXURIS_MODEL")
        or os.environ.get("NEXO_MODEL")
        or FALLBACK_MODEL
    )
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
