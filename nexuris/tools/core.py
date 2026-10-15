"""Nexo 2.0 — Tools core: system, archivos, shell con aprobación.

Todas declaradas con @tool. Permisos:
  allow → lectura de estado (seguro)
  ask   → escritura / shell (pide confirmación)
  deny  → nada destructivo por ahora (se agrega caso a caso)
"""
from __future__ import annotations

import platform
import subprocess
import time
from pathlib import Path

from .registry import Permission, tool


# ---------- System (allow) ----------

@tool(name="system_info", description="Estado del sistema: CPU, RAM, disco, uptime.", permission=Permission.ALLOW, tags=["system"])
def system_info() -> dict:
    import os
    import shutil

    du = shutil.disk_usage("/")
    load1, load5, load15 = os.getloadavg()
    return {
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "python": platform.python_version(),
        "load_avg": [round(load1, 2), round(load5, 2), round(load15, 2)],
        "disk_total_gb": round(du.total / 1e9, 1),
        "disk_free_gb": round(du.free / 1e9, 1),
        "disk_used_pct": round(100 * (du.total - du.free) / du.total, 1),
    }


@tool(name="list_dir", description="Lista contenido de un directorio.", permission=Permission.ALLOW, tags=["files"])
def list_dir(path: str = ".") -> list[str]:
    p = Path(path).expanduser()
    if not p.exists():
        return [f"NO EXISTE: {path}"]
    return sorted(e.name + ("/" if e.is_dir() else "") for e in p.iterdir())[:200]


# ---------- Files ----------

@tool(name="read_file", description="Lee el contenido de un archivo de texto.", permission=Permission.ALLOW, tags=["files"])
def read_file(path: str, max_bytes: int = 20000) -> str:
    p = Path(path).expanduser()
    if not p.exists():
        return f"NO EXISTE: {path}"
    data = p.read_bytes()[:max_bytes]
    return data.decode("utf-8", errors="replace")


# ---------- Shell (ask) ----------

@tool(name="run_command", description="Ejecuta un comando del sistema. Requiere aprobación.", permission=Permission.ASK, timeout=20.0, tags=["shell"])
def run_command(command: str, timeout: int = 15) -> dict:
    """Ejecuta un comando shell con timeout. El usuario lo aprueba."""
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout[:8000],
            "stderr": proc.stderr[:4000],
        }
    except subprocess.TimeoutExpired:
        return {"error": f"timeout tras {timeout}s"}
