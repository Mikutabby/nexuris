"""Nexuris — Servidor MCP.

Expone las tools de Nexuris (memoria, sistema, archivos) como un servidor
MCP para que opencode — u otro cliente MCP — pueda usarlas.

Doble modo:
  - Fuera de opencode: `python -m nexuris.mcp_server` → CLI propia con su agente.
  - Dentro de opencode: se registra como MCP server en opencode.jsonc,
    y el agente de opencode llama estas tools.

Transporte: stdio (JSON-RPC 2.0), el mismo que usa opencode.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# asegura importabilidad
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nexuris.bootstrap import build_agent
from nexuris.core.config import CONFIG
from nexuris.memory.blocks import BLOCKS, BlockLabel
from nexuris.memory.store import STORE
from nexuris.tools.registry import REGISTRY


def _tools_list() -> list[dict]:
    """Lista de tools en formato MCP (JSON Schema)."""
    out = []
    for spec in REGISTRY.specs():
        fn = spec["function"]
        out.append(
            {
                "name": fn["name"],
                "description": fn["description"],
                "inputSchema": fn["parameters"],
            }
        )
    # agrega tools de memoria que no pasan por @tool pero son útiles vía MCP
    out.append(
        {
            "name": "nexuris_blocks",
            "description": "Muestra los bloques de memoria auto-editables (human, persona, style, safety).",
            "inputSchema": {"type": "object", "properties": {}},
        }
    )
    out.append(
        {
            "name": "nexuris_facts",
            "description": "Lista los últimos hechos guardados en la memoria.",
            "inputSchema": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "default": 10}},
            },
        }
    )
    return out


def _tools_call(name: str, arguments: dict) -> str:
    """Ejecuta una tool y retorna texto."""
    try:
        if name == "nexuris_blocks":
            parts = []
            for b in BLOCKS.all():
                ro = " [ro]" if b.read_only else ""
                parts.append(f"[{b.label.value}]{ro}\n{b.value[:500]}")
            return "\n\n".join(parts)

        if name == "nexuris_facts":
            limit = int(arguments.get("limit", 10))
            facts = STORE.recent_facts(limit=limit)
            if not facts:
                return "(sin hechos)"
            return "\n".join(f"- {f.content}" for f in facts)

        # tools registradas con @tool
        result = REGISTRY.invoke(name, arguments)
        return json.dumps(result, ensure_ascii=False, default=str, indent=2)
    except Exception as e:  # noqa: BLE001
        return json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"})


def _handle(req: dict) -> dict | None:
    """Maneja un request JSON-RPC de MCP."""
    method = req.get("method")
    req_id = req.get("id")
    params = req.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "nexuris", "version": "2.0.0"},
            },
        }
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": _tools_list()}}
    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments") or {}
        text = _tools_call(name, args)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"content": [{"type": "text", "text": text}]},
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    # método desconocido
    if req_id is not None:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }
    return None


def main() -> None:
    """Loop stdio de MCP: lee JSON-RPC por stdin, responde por stdout."""
    # precarga tools (el decorador las registra al importar)
    from nexuris.tools import core as _core  # noqa: F401
    from nexuris.tools import memory_tools as _mem  # noqa: F401

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = _handle(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
