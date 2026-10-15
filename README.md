# Nexuris

**La evolución de Nexo** — un asistente del hogar que aprende de interacciones, sin guion de personalidad.

Nexuris no sigue un script de tono ni muletillas prescritas. Su estilo emerge de la memoria: bloque de hechos sobre el usuario, ejemplos reales de conversaciones que funcionaron, y lecciones de feedback. La personalidad se *acumula*, no se *escribe*.

## Filosofía (research 2024–2026)

La evidencia es clara: los prompts de persona largos **no mejoran** las respuestas, **pelean** contra las instrucciones y **decan** con el tiempo. En cambio:

- **Prompt mínimo de rol** — solo identidad + piso de seguridad + contratos de tool.
- **Estilo por ejemplos, no reglas** — se guardan muestras de turnos que funcionaron (como Claude Styles), no "siempre decí X".
- **Memoria auto-editable** — el agente reescribe sus propios bloques `human` y `persona` (patrón Letta/MemGPT).
- **Consolidación en "sueño"** — al cerrar la sesión, extrae hechos y notas de estilo (patrón sleep-time).
- **Seguridad en código, nunca aprendida** — permisos `allow/ask/deny` por tool, denegaciones duras en el nivel de aplicación.

## Arquitectura

```
nexuris/
├── core/
│   ├── config.py      # config (LLM, agente, memoria)
│   ├── llm.py         # cliente Claude/Nemotron vía OpenRouter
│   └── agent.py       # loop ReAct mínimo (~120 líneas, sin frameworks)
├── tools/
│   ├── registry.py    # @tool decorator + permisos + JSON Schema
│   ├── core.py        # system, archivos, shell (con aprobación)
│   └── memory_tools.py# edición de bloques, estilo, hechos, feedback
├── memory/
│   ├── blocks.py      # bloques auto-editables (human, persona, style, safety)
│   └── store.py       # SQLite: hechos ADD-only + búsqueda híbrida
├── learn/
│   ├── consolidate.py # sleep-time: extrae hechos y reescribe bloques
│   └── feedback.py    # señales del usuario → lecciones
├── session.py         # sesión: historial + feedback + consolidación al cerrar
├── cli.py             # CLI interactiva
└── mcp_server.py      # servidor MCP (para opencode u otro cliente)
```

## Modos de uso

### 1. CLI standalone (fuera de opencode)

```bash
cd nexuris
./.venv/bin/python run.py
```

Comandos: `/salir` (consolida), `/feedback bien|mal`, `/bloques`, `/hechos`, `/modelo <id>`.

### 2. Dentro de opencode (vía MCP)

Registrar en `~/.config/opencode/opencode.jsonc`:

```json
"mcp": {
  "nexuris": {
    "type": "local",
    "command": ["/home/archlinux/nexuris/.venv/bin/python", "-m", "nexuris.mcp_server"],
    "enabled": true
  }
}
```

El agente de opencode (`.opencode/agents/nexuris.md`) queda disponible como modo `nexuris`.

## Cerebro (LLM)

Un solo cerebro, configurable. Por defecto un modelo gratis de OpenRouter que soporta tool calling. Para cambiar a Claude:

```python
# nexuris/core/config.py
model: str = "anthropic/claude-sonnet-5.5"
```

La API key se lee de `NEXO_OPENROUTER_KEY` / `OPENROUTER_API_KEY` o del config de opencode.

## Instalación

```bash
python3 -m venv .venv
./.venv/bin/pip install openai httpx
./.venv/bin/python tests/test_learning.py   # smoke test
```

## Licencia

MIT.
