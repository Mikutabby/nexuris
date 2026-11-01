#!/usr/bin/env python3
"""Registra (o quita) el servidor MCP de Nexuris en el config de opencode.

Edita `opencode.jsonc` respetando comentarios y formato: no parsea y reescribe
todo el archivo, solo localiza el objeto `"mcp"` y la entrada `"nexuris"`.

Uso:
    python3 scripts/register_mcp.py --python /ruta/.venv/bin/python
    python3 scripts/register_mcp.py --remove
    python3 scripts/register_mcp.py --config ~/.config/opencode/opencode.jsonc --check

Siempre escribe un backup antes de tocar nada. Si algo no cuadra, sale con
código 1 y deja el archivo intacto.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

WS = " \t\r\n"


# --------------------------------------------------------------------------
# Scanner mínimo de JSONC: ubica objetos por clave sin romper comentarios.
# --------------------------------------------------------------------------
class Scanner:
    def __init__(self, text: str) -> None:
        self.t = text

    def skip_ws(self, i: int, end: int) -> int:
        t = self.t
        while i < end:
            if t[i] in WS:
                i += 1
            elif t.startswith("//", i):
                nl = t.find("\n", i)
                i = end if nl == -1 else nl + 1
            elif t.startswith("/*", i):
                close = t.find("*/", i + 2)
                i = end if close == -1 else close + 2
            else:
                break
        return i

    def string_end(self, i: int) -> int:
        """i apunta a la comilla de apertura; devuelve índice tras la de cierre."""
        t = self.t
        i += 1
        while i < len(t):
            c = t[i]
            if c == "\\":
                i += 2
                continue
            if c == '"':
                return i + 1
            i += 1
        raise ValueError("string sin cerrar")

    def value_end(self, i: int, end: int) -> int:
        """Dado el inicio de un valor, devuelve el índice donde termina."""
        t = self.t
        i = self.skip_ws(i, end)
        if i >= end:
            raise ValueError("valor vacío")
        c = t[i]
        if c == '"':
            return self.string_end(i)
        if c == "{":
            return self.matching(i, end, "{", "}")
        if c == "[":
            return self.matching(i, end, "[", "]")
        # número / true / false / null
        j = i
        while j < end and t[j] not in ",}]" + WS:
            j += 1
        return j

    def matching(self, start: int, end: int, open_c: str, close_c: str) -> int:
        t = self.t
        depth = 0
        i = start
        while i < end:
            if t[i] == '"':
                i = self.string_end(i)
                continue
            if t.startswith("//", i):
                nl = t.find("\n", i)
                i = end if nl == -1 else nl + 1
                continue
            if t.startswith("/*", i):
                close = t.find("*/", i + 2)
                i = end if close == -1 else close + 2
                continue
            if t[i] == open_c:
                depth += 1
            elif t[i] == close_c:
                depth -= 1
                if depth == 0:
                    return i + 1
            i += 1
        raise ValueError(f"bloque {open_c}{close_c} sin cerrar")

    def members(self, obj_start: int, obj_end: int) -> list[dict]:
        """Miembros de un objeto. obj_start/obj_end incluyen llaves."""
        t = self.t
        i = obj_start + 1
        stop = obj_end - 1
        out: list[dict] = []
        while True:
            i = self.skip_ws(i, stop)
            if i >= stop:
                break
            if t[i] != '"':
                raise ValueError(f"se esperaba clave en offset {i}")
            key_end = self.string_end(i)
            key = json.loads(t[i:key_end])
            i = self.skip_ws(key_end, stop)
            if i >= stop or t[i] != ":":
                raise ValueError(f"se esperaba ':' tras {key!r}")
            val_start = self.skip_ws(i + 1, stop)
            val_end = self.value_end(val_start, stop)
            out.append(
                {
                    "key": key,
                    "val_start": val_start,
                    "val_end": val_end,
                }
            )
            # busca la coma separadora
            j = self.skip_ws(val_end, stop)
            if j < stop and t[j] == ",":
                i = j + 1
            else:
                i = j
                break
        return out


def find_key(sc: Scanner, obj_start: int, obj_end: int, key: str) -> dict | None:
    for m in sc.members(obj_start, obj_end):
        if m["key"] == key:
            return m
    return None


def line_indent(text: str, pos: int) -> str:
    """Indentación (espacios/tabs) de la línea donde cae `pos`."""
    ls = text.rfind("\n", 0, pos) + 1
    m = re.match(r"[ \t]*", text[ls:])
    return m.group(0) if m else ""


def find_top_mcp(text: str, key: str) -> tuple[int, int, dict] | None:
    sc = Scanner(text)
    # el archivo entero es un objeto
    start = sc.skip_ws(0, len(text))
    if start >= len(text) or text[start] != "{":
        raise ValueError("el config raíz no es un objeto")
    end = sc.matching(start, len(text), "{", "}")
    m = find_key(sc, start, end, key)
    if not m:
        return None
    if text[m["val_start"]] != "{":
        raise ValueError(f'"{key}" no es un objeto')
    vstart = m["val_start"]
    vend = sc.matching(vstart, len(text), "{", "}")
    return vstart, vend, m


def build_entry(indent: str, python_path: str) -> str:
    inner = indent + "  "
    return (
        "{\n"
        f'{inner}"type": "local",\n'
        f'{inner}"command": [{json.dumps(python_path)}, "-m", "nexuris.mcp_server"],\n'
        f'{inner}"enabled": true\n'
        f"{indent}}}"
    )


def edit(text: str, python_path: str) -> str:
    found = find_top_mcp(text, "mcp")
    sc = Scanner(text)

    if found is None:
        raise ValueError('el config no tiene una sección "mcp"')

    mcp_start, mcp_end, _ = found
    existing = find_key(sc, mcp_start, mcp_end, "nexuris")

    if existing:
        indent = line_indent(text, existing["val_start"])
        entry = build_entry(indent, python_path)
        return text[: existing["val_start"]] + entry + text[existing["val_end"] :]

    # insertar como primer miembro
    members = sc.members(mcp_start, mcp_end)
    if members:
        indent = line_indent(text, members[0]["val_start"])
        base = line_indent(text, members[0]["val_start"])
    else:
        base = line_indent(text, mcp_start)
        indent = base + "  "
    entry = f'"nexuris": {build_entry(indent, python_path)}'
    ins = mcp_start + 1
    if members:
        body = "\n" + base + entry + ","
        return text[:ins] + body + text[ins:]
    body = "\n" + indent + entry + "\n" + base
    return text[:ins] + body + text[ins:]


def remove(text: str) -> str:
    found = find_top_mcp(text, "mcp")
    if found is None:
        return text
    mcp_start, mcp_end, _ = found
    sc = Scanner(text)
    members = sc.members(mcp_start, mcp_end)
    idx = next((k for k, m in enumerate(members) if m["key"] == "nexuris"), None)
    if idx is None:
        return text

    target = members[idx]
    # límites: desde el inicio de la línea del miembro hasta el inicio del siguiente
    start = text.rfind("\n", mcp_start, target["val_start"]) + 1
    if idx + 1 < len(members):
        end = text.rfind("\n", mcp_start, members[idx + 1]["val_start"]) + 1
    else:
        # último miembro: buscar la llave de cierre del objeto mcp
        end = text.rfind("\n", 0, mcp_end - 1) + 1
        # si queda una coma colgando en el miembro anterior, la quitamos
        prev = text[:start]
        prev = re.sub(r",[ \t]*\n[ \t]*$", "\n", prev)
        return prev + text[end:]
    return text[:start] + text[end:]


def strip_jsonc(text: str) -> str:
    """Sanitiza para validar con json.loads (solo para verificar)."""
    out = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == '"':
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == '"':
                    j += 1
                    break
                j += 1
            out.append(text[i:j])
            i = j
        elif text.startswith("//", i):
            nl = text.find("\n", i)
            i = n if nl == -1 else nl
        elif text.startswith("/*", i):
            c = text.find("*/", i + 2)
            i = n if c == -1 else c + 2
        else:
            out.append(text[i])
            i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def default_config() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    for name in ("opencode.jsonc", "opencode.json"):
        p = base / "opencode" / name
        if p.exists():
            return p
    return base / "opencode" / "opencode.jsonc"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Registra Nexuris como MCP en opencode")
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument("--python", default=None, help="intérprete del venv de Nexuris")
    ap.add_argument("--remove", action="store_true")
    ap.add_argument("--check", action="store_true", help="solo verificar, no escribir")
    args = ap.parse_args(argv)

    cfg = args.config or default_config()
    if not cfg.exists():
        print(f"no existe el config: {cfg}", file=sys.stderr)
        return 1

    text = cfg.read_text(encoding="utf-8")
    try:
        new = remove(text) if args.remove else edit(text, args.python or sys.executable)
    except ValueError as e:
        print(f"config no tocado: {e}", file=sys.stderr)
        return 1

    if new == text:
        print("sin cambios (ya estaba así)", file=sys.stderr)
        return 0

    try:
        json.loads(strip_jsonc(new))
    except json.JSONDecodeError as e:
        print(f"resultado inválido, no escribo: {e}", file=sys.stderr)
        return 1

    if args.check:
        print("el cambio sería válido", file=sys.stderr)
        return 0

    backup = cfg.with_suffix(
        cfg.suffix + f".bak-nexuris-{datetime.now():%Y%m%d-%H%M%S}"
    )
    shutil.copy2(cfg, backup)
    cfg.write_text(new, encoding="utf-8")
    print(f"config actualizado: {cfg} (backup: {backup.name})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
