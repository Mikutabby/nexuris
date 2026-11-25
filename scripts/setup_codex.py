#!/usr/bin/env python3
"""Configura Codex para usar Nexuris como modelo, de forma idempotente.

Uso:
  python3 scripts/setup_codex.py           # instalar/actualizar
  python3 scripts/setup_codex.py --remove  # deshacer lo que agregó este script
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HOME = Path.home()
REPO = Path(__file__).resolve().parent.parent
CODEX = HOME / ".codex"
PROXY = REPO / "codex_proxy.py"
SERVICE = HOME / ".config/systemd/user/nexuris-codex-proxy.service"
CATALOG = CODEX / "nexuris-models.json"
PROFILE = CODEX / "nexuris.config.toml"
AGENTS = HOME / "AGENTS.md"
CONFIG = CODEX / "config.toml"
PORT = 4205

MODEL_TEMPLATE = {
    "slug": "nexuris",
    "display_name": "Nexuris",
    "description": "Nexuris (asistente del hogar) via opencode",
    "base_instructions": "Sos Nexuris, un asistente del hogar. Respondé en español, breve y directo.",
    "supported_reasoning_levels": [{"effort": "medium", "description": "Equilibrado"}],
    "shell_type": "unified_exec",
    "visibility": "list",
    "supported_in_api": True,
    "priority": 0,
    "support_verbosity": False,
    "default_reasoning_summary": "none",
    "default_verbosity": None,
    "apply_patch_tool_type": "freeform",
    "web_search_tool_type": "text_and_image",
    "truncation_policy": {"mode": "tokens", "limit": 10000},
    "supports_image_detail_original": False,
    "context_window": 200000,
    "experimental_supported_tools": [],
    "input_modalities": ["text", "image"],
    "supports_search_tool": False,
    "supports_experimental_context": False,
    "use_responses_lite": False,
    "supports_reasoning_effort_updates": False,
    "node_repl_auto_review_required": False,
    "node_repl_disabled": False,
    "multi_agent_version": "v1",
    "available_access_programs": {"cyber": ["standard"]},
    "supports_parallel_tool_calls": False,
    "supports_reasoning_summaries": True,
    "availability_nux": None,
    "upgrade": None,
}

AGENTS_TEXT = """# Instrucciones fijas

- Respondé siempre en español, de forma breve y directa.
- Nunca inventes comandos, flags, rutas, opciones ni nombres de herramientas. Si no estás seguro de que algo existe, decilo y verificá antes de afirmar.
- Si no sabés algo, respondé "no lo sé" en lugar de rellenar con una guess.
- Antes de dar instrucciones para esta máquina, verificá con herramientas de solo lectura (comandos reales, archivos reales).
- Usá rutas y unidades reales del sistema; no asumas valores genéricos.
- Priorizá respuestas cortas salvo que te pidan explícitamente detalle.
"""

START = "# BEGIN nexuris-managed\n"
END = "# END nexuris-managed\n"
PROVIDER_START = "# BEGIN nexuris-provider\n"
PROVIDER_END = "# END nexuris-provider\n"


def run(cmd: list[str], timeout: float = 60) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def opencode_bin() -> str | None:
    found = shutil.which("opencode")
    if found:
        return found
    candidate = HOME / ".opencode/bin/opencode"
    return str(candidate) if candidate.exists() else None


def strip_managed(text: str) -> str:
    """Saca bloques y claves top-level que administra este script."""
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip() == START.strip():
            i += 1
            while i < len(lines) and lines[i].strip() != END.strip():
                i += 1
            i += 1
            continue
        if line.strip() == PROVIDER_START.strip():
            i += 1
            while i < len(lines) and lines[i].strip() != PROVIDER_END.strip():
                i += 1
            i += 1
            continue
        if line.strip().startswith("[model_providers.nexuris]"):
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("["):
                i += 1
            continue
        out.append(line)
        i += 1

    # claves top-level (fuera de cualquier [table]) que este script setea
    result: list[str] = []
    in_table = False
    for line in out:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_table = True
        elif not in_table and any(
            stripped.startswith(k + " ") or stripped.startswith(k + "=")
            for k in ("model", "model_provider", "model_catalog_json", "review_model", "model_auto_compact_token_limit", "tool_output_token_limit")
        ):
            continue
        result.append(line)
    return "\n".join(result).strip("\n") + "\n"


def setup_config() -> None:
    original = CONFIG.read_text(encoding="utf-8") if CONFIG.exists() else ""
    body = strip_managed(original)
    opencode_dir = str(Path(opencode_bin() or "opencode").parent)
    block = (
        START
        + 'model = "nexuris"\n'
        + 'model_provider = "nexuris"\n'
        + f'model_catalog_json = "{CATALOG}"\n'
        + 'review_model = "nexuris"\n'
        + 'model_auto_compact_token_limit = 24000\n'
        + 'tool_output_token_limit = 4000\n'
        + END
    )
    provider = (
        "\n" + PROVIDER_START + "\n[model_providers.nexuris]\n"
        'name = "Nexuris"\n'
        + f'base_url = "http://127.0.0.1:{PORT}/v1"\n'
        + 'wire_api = "responses"\n'
        + 'requires_openai_auth = false\n'
        + PROVIDER_END + "\n"
    )
    CONFIG.write_text(block + "\n" + body.rstrip("\n") + "\n" + provider, encoding="utf-8")
    print("  config.toml: modelo Nexuris configurado")


def setup_catalog() -> None:
    CATALOG.write_text(json.dumps({"models": [MODEL_TEMPLATE]}, ensure_ascii=False), encoding="utf-8")
    print(f"  catálogo: {CATALOG}")


def setup_agents() -> None:
    if AGENTS.exists():
        print("  AGENTS.md: ya existe, no lo toco")
        return
    AGENTS.write_text(AGENTS_TEXT, encoding="utf-8")
    print(f"  AGENTS.md: creado en {AGENTS}")


def setup_service() -> None:
    if not PROXY.exists():
        raise RuntimeError(f"no encontré {PROXY}")
    SERVICE.parent.mkdir(parents=True, exist_ok=True)
    py = shutil.which("python3") or "/usr/bin/python3"
    opencode_dir = str(Path(opencode_bin() or "opencode").parent)
    SERVICE.write_text(
        "[Unit]\n"
        "Description=Nexuris -> Codex proxy\n"
        "After=network.target\n\n"
        "[Service]\n"
        f"Environment=PATH={opencode_dir}:/home/{os.getenv('USER','miku')}/.local/bin:/usr/local/bin:/usr/bin:/bin\n"
        f"ExecStart={py} {PROXY}\n"
        "Restart=always\nRestartSec=2\n\n"
        "[Install]\nWantedBy=default.target\n",
        encoding="utf-8",
    )
    run(["systemctl", "--user", "daemon-reload"])
    run(["systemctl", "--user", "enable", "--now", "nexuris-codex-proxy.service"])
    print("  servicio: nexuris-codex-proxy.service activo")


def smoke_test() -> None:
    url = f"http://127.0.0.1:{PORT}/health"
    for _ in range(20):
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    print("  health: OK")
                    return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("el proxy no respondió en /health")


def remove() -> None:
    run(["systemctl", "--user", "disable", "--now", "nexuris-codex-proxy.service"])
    for path in (SERVICE, CATALOG, PROFILE):
        path.unlink(missing_ok=True)
    if CONFIG.exists():
        CONFIG.write_text(strip_managed(CONFIG.read_text(encoding="utf-8")), encoding="utf-8")
    print("  configuración de Codex removida (AGENTS.md se conserva)")


def main() -> int:
    if "--remove" in sys.argv:
        remove()
        return 0
    oc = opencode_bin()
    if not oc:
        raise RuntimeError("no encontré el binario `opencode` en el PATH")
    print(f"  opencode: {oc}")
    setup_catalog()
    setup_agents()
    setup_config()
    setup_service()
    smoke_test()
    print("Listo. `codex` usa Nexuris; `codex --profile kilo` usa el modelo gratis.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
