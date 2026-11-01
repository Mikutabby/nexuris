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

## Instalación

### Un comando (recomendado)

```bash
git clone https://github.com/Mikutabby/nexuris.git
cd nexuris
./install.sh
```

El instalador detecta la distro y el gestor de paquetes, verifica Python ≥ 3.10
y el módulo `venv`, crea `.venv`, instala el paquete en modo editable, corre un
smoke test, deja los lanzadores `nexuris` / `nexuris-mcp` en `~/.local/bin` y
registra el MCP en opencode con la ruta real de tu máquina.

Si falta Python o `python3-venv`, te muestra el comando exacto y **pregunta**
antes de usar `sudo`. También podés dejarlo hacerlo solo:

```bash
./install.sh --install-deps -y
```

### Por distro (si preferís a mano)

| Distro | Paquetes |
|---|---|
| Arch / Manjaro / EndeavourOS / CachyOS | `sudo pacman -S --needed python python-pip` |
| Debian / Ubuntu / Mint / Pop!_OS / Kali | `sudo apt install python3 python3-venv python3-pip` |
| Fedora / RHEL / Rocky / Alma | `sudo dnf install python3 python3-pip` |
| openSUSE / SLES | `sudo zypper install python3 python3-pip` |
| Alpine | `sudo apk add python3 py3-pip` |
| Void | `sudo xbps-install -S python3 python3-pip` |
| Gentoo | `sudo emerge dev-lang/python dev-python/pip` |
| Solus | `sudo eopkg install python3 python3-pip` |
| Termux (Android) | `pkg install python` |
| NixOS | `nix-shell -p python3 --run './install.sh'` o agregá `pkgs.python3` a `environment.systemPackages` |

Después, en cualquier distro:

```bash
git clone https://github.com/Mikutabby/nexuris.git
cd nexuris
python3 -m venv .venv
./.venv/bin/pip install -e .
./.venv/bin/nexuris              # CLI
```

### Opciones del instalador

```bash
./install.sh --check          # diagnostica sin tocar nada
./install.sh --no-mcp         # no toca la config de opencode
./install.sh --no-link        # no crea lanzadores en ~/.local/bin
./install.sh --venv /ruta     # virtualenv en otra ruta
./install.sh --recreate       # borra y recrea el venv
./install.sh --uninstall      # quita venv, lanzadores y MCP
./install.sh --uninstall --purge   # además borra la memoria
```

## Configuración

Todo por variables de entorno — no hay que editar código:

| Variable | Para qué | Default |
|---|---|---|
| `OPENROUTER_API_KEY` (o `NEXO_OPENROUTER_KEY`) | API key del cerebro | se lee de `~/.config/opencode/opencode.jsonc` |
| `NEXURIS_MODEL` | modelo de OpenRouter (pisa la config guardada) | `openrouter/free` |
| `NEXURIS_DATA_DIR` | dónde vive la memoria | `~/.local/share/nexuris` (o `nexuris/data` si ya había datos) |
| `NEXURIS_VENV` | ruta del virtualenv | `./.venv` |

Si el modelo configurado desaparece de OpenRouter, el cliente cae solo a
`openrouter/free` en vez de romperse. La elección del modelo también se guarda
en `~/.config/nexuris/config.json` (comando `/modelo` o `nexuris update`).

## Mantenimiento

Nexuris se mantiene al día con las IAs actuales con un comando:

```bash
nexuris update            # actualiza todo
nexuris update --check    # solo muestra qué hay para actualizar
```

O desde el instalador:

```bash
./install.sh --update
./install.sh --check-update
```

`nexuris update` hace, en orden:

1. **Repo**: `git pull --ff-only` si el checkout está limpio (nunca pisa cambios locales).
2. **Dependencias**: reinstala el paquete en modo editable.
3. **Modelo**: consulta OpenRouter, filtra modelos **gratis con tool calling**,
   los ordena por contexto y proveedor, y valida al ganador con una llamada real
   (tiene que saber usar una tool). Si ninguno responde, usa `openrouter/free`.
   El elegido queda en `~/.config/nexuris/config.json`.
4. **Tests**: corre los tests offline; si algo falla, avisa.

Flags: `--no-pull`, `--no-model`, `--no-tests`.

La idea es que cuando salgan modelos nuevos (o retiren los viejos), un
`nexuris update` alcance para quedar al día sin tocar código.

## Modos de uso

### 1. CLI standalone

```bash
nexuris            # o ./.venv/bin/python run.py
```

Comandos: `/salir` (consolida), `/feedback bien|mal`, `/bloques`, `/hechos`, `/modelo <id>`.

### 2. Dentro de opencode (vía MCP)

El instalador ya lo registra. Si querés hacerlo a mano, el bloque en
`~/.config/opencode/opencode.jsonc` es:

```jsonc
"mcp": {
  "nexuris": {
    "type": "local",
    "command": ["/RUTA/A/TU/nexuris/.venv/bin/python", "-m", "nexuris.mcp_server"],
    "enabled": true
  }
}
```

O automático con la ruta correcta:

```bash
python3 scripts/register_mcp.py --python "$PWD/.venv/bin/python"
```

El agente de opencode (`.opencode/agents/nexuris.md`) queda disponible como modo `nexuris`.

### 3. Tests

```bash
./.venv/bin/python tests/test_install.py    # offline, sirve para verificar la instalación
./.venv/bin/python tests/test_update.py     # offline, actualizador y ranking de modelos
./.venv/bin/python tests/test_learning.py   # offline
./.venv/bin/python tests/test_loop.py       # end-to-end (necesita API key)
./.venv/bin/python tests/test_cycle.py      # ciclo de memoria (necesita API key)
```

## Cerebro (LLM)

Un solo cerebro, configurable. Por defecto `openrouter/free`, que soporta tool
calling y no se cae cuando retiran un slug. Para usar Claude:

```bash
NEXURIS_MODEL=anthropic/claude-sonnet-5.5 nexuris
```

La API key se lee de `OPENROUTER_API_KEY`, `NEXO_OPENROUTER_KEY` o del config de opencode.

## Licencia

MIT.
