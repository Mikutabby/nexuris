"""Smoke test de instalación — no necesita red ni API key.

Verifica que el paquete quedó bien instalado en cualquier distro:
  - Python soportado
  - directorio de datos escribible (XDG o legacy)
  - tools registradas y visibles por MCP
  - servidor MCP responde initialize / tools/list / tools/call
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nexuris.bootstrap import build_agent
from nexuris.core.config import CONFIG, DATA_DIR
from nexuris.mcp_server import _handle, _tools_list
from nexuris.tools.registry import REGISTRY

REQUIRED_TOOLS = {
    "system_info",
    "read_file",
    "list_dir",
    "remember_fact",
    "recall_facts",
    "update_memory_block",
}


def fail(msg: str) -> None:
    print(f"❌ {msg}")
    sys.exit(1)


def main() -> None:
    print("== Nexuris — test de instalación ==\n")

    if sys.version_info < (3, 10):
        fail(f"Python {sys.version.split()[0]} es viejo; se necesita >= 3.10")
    print(f"ok python {sys.version.split()[0]}")

    agent = build_agent()
    assert agent is not None
    print(f"ok agente construido (modelo: {CONFIG.llm.model})")

    names = set(REGISTRY.names())
    missing = REQUIRED_TOOLS - names
    if missing:
        fail(f"tools faltantes: {sorted(missing)}")
    print(f"ok tools registradas: {len(names)}")

    if not DATA_DIR.is_dir():
        fail(f"el directorio de datos no existe: {DATA_DIR}")
    try:
        with tempfile.NamedTemporaryFile(dir=DATA_DIR):
            pass
    except OSError as exc:
        fail(f"el directorio de datos no es escribible ({DATA_DIR}): {exc}")
    print(f"ok datos en {DATA_DIR}")

    tools = _tools_list()
    mcp_names = {t["name"] for t in tools}
    for extra in ("nexuris_blocks", "nexuris_facts"):
        if extra not in mcp_names:
            fail(f"tool MCP faltante: {extra}")
    print(f"ok tools MCP: {len(mcp_names)}")

    r = _handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    if r["result"]["serverInfo"]["name"] != "nexuris":
        fail("initialize no devolvió serverInfo")
    print("ok MCP initialize")

    r = _handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    if not r["result"]["tools"]:
        fail("tools/list vacío")
    print("ok MCP tools/list")

    r = _handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "nexuris_facts", "arguments": {"limit": 1}},
        }
    )
    content = r["result"]["content"][0]
    if content["type"] != "text":
        fail("tools/call no devolvió texto")
    print("ok MCP tools/call")

    print("\n✅ Instalación OK.")


if __name__ == "__main__":
    main()
