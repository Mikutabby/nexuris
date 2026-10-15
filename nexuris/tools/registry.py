"""Nexo 2.0 — Registro de herramientas nativas con permisos.

Filosofía (research 2026): herramientas DECLARADAS, validadas y con
permisos. El shell es UNA tool más con aprobación, nunca el default.

    @tool(name="read_file", permission="allow")
    def read_file(path: str) -> str: ...

El registro genera el JSON Schema que Claude ve, y ejecuta con
validación + control de permisos.
"""
from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, get_args, get_origin, get_type_hints


class Permission(str, Enum):
    ALLOW = "allow"   # se ejecuta sin preguntar
    ASK = "ask"       # pide confirmación humana
    DENY = "deny"     # nunca se ejecuta


# ---------- Inferencia de JSON Schema desde type hints ----------

_PY_TO_JSON = {
    str: {"type": "string"},
    int: {"type": "integer"},
    float: {"type": "number"},
    bool: {"type": "boolean"},
    dict: {"type": "object"},
    list: {"type": "array"},
    Any: {},
}


def _schema_for_annotation(ann: Any) -> dict[str, Any]:
    if ann in _PY_TO_JSON:
        return dict(_PY_TO_JSON[ann])
    origin = get_origin(ann)
    if origin is list:
        args = get_args(ann)
        item = _schema_for_annotation(args[0]) if args else {}
        return {"type": "array", "items": item}
    if origin is dict:
        return {"type": "object"}
    # union / optional
    if origin is not None and type(None) in get_args(ann):
        non_none = [a for a in get_args(ann) if a is not type(None)]
        if len(non_none) == 1:
            return _schema_for_annotation(non_none[0])
    return {"type": "string"}


def _build_parameters_schema(fn: Callable[..., Any]) -> dict[str, Any]:
    hints = get_type_hints(fn)
    sig = inspect.signature(fn)
    props: dict[str, Any] = {}
    required: list[str] = []
    for pname, param in sig.parameters.items():
        if pname in ("self", "cls"):
            continue
        ann = hints.get(pname, str)
        props[pname] = _schema_for_annotation(ann)
        if param.default is inspect.Parameter.empty:
            required.append(pname)
    return {"type": "object", "properties": props, "required": required}


# ---------- Tool ----------

@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    fn: Callable[..., Any]
    permission: Permission = Permission.ASK
    timeout: float = 15.0
    tags: list[str] = field(default_factory=list)

    def to_spec(self) -> dict[str, Any]:
        """JSON Schema en formato OpenAI para enviar al modelo."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def invoke(self, arguments: dict[str, Any]) -> Any:
        return self.fn(**arguments)


class ToolRegistry:
    """Registro central de tools. Genera specs y ejecuta con permisos."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def specs(self, tags: list[str] | None = None) -> list[dict[str, Any]]:
        """Specs JSON para el modelo. Filtra por tags si se pasa."""
        out = []
        for t in self._tools.values():
            if tags is None or any(tag in t.tags for tag in tags):
                out.append(t.to_spec())
        return out

    def invoke(self, name: str, arguments: dict[str, Any]) -> Any:
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"Tool desconocida: {name}")
        if tool.permission == Permission.DENY:
            raise PermissionError(f"Tool bloqueada: {name}")
        return tool.invoke(arguments)


# ---------- Decorador ----------

# Registro global por defecto (las tools se auto-registran al decorar)
REGISTRY = ToolRegistry()


def tool(
    name: str | None = None,
    description: str = "",
    permission: Permission | str = Permission.ASK,
    timeout: float = 15.0,
    tags: list[str] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Registra una función como tool de Nexo.

    Uso:
        @tool(name="read_file", description="Lee un archivo", permission="allow")
        def read_file(path: str) -> str:
            return Path(path).read_text()
    """
    if isinstance(permission, str):
        permission = Permission(permission)

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        tname = name or fn.__name__
        desc = description or (fn.__doc__ or "").strip().split("\n")[0]
        t = Tool(
            name=tname,
            description=desc,
            parameters=_build_parameters_schema(fn),
            fn=fn,
            permission=permission,
            timeout=timeout,
            tags=tags or [],
        )
        # adjunta el Tool al objeto función para acceso directo
        fn._nexo_tool = t  # type: ignore[attr-defined]
        # auto-registra en el registro global (patrón smolagents/PydanticAI)
        REGISTRY.register(t)
        return fn

    return decorator


def register_global(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Alias legacy — el decorador @tool ya auto-registra."""
    t = getattr(fn, "_nexo_tool", None)
    if t is None:
        raise ValueError("register_global requiere una función decorada con @tool")
    REGISTRY.register(t)
    return fn
