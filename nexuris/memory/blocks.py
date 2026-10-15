"""Nexo 2.0 — Bloques de memoria auto-editables (patrón Letta/MemGPT).

Filosofía (research 2026): la personalidad no se escribe en el prompt,
se acumula en memoria. El agente tiene bloques que ÉL mismo edita:

  human   → lo que sabe de miku (el agente lo escribe/reescribe)
  persona → auto-concepto del agente (autorregistrado, con límite)
  style   → ejemplos de turnos que funcionaron, NO reglas de tono
  safety  → piso de seguridad (SOLO LECTURA, escrito por código/humano)

El agente los edita con tools (`update_block`). Límite de chars por
bloque para forzar síntesis, no acumulación infinita.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from ..core.config import DATA_DIR


class BlockLabel(str, Enum):
    HUMAN = "human"
    PERSONA = "persona"
    STYLE = "style"
    SAFETY = "safety"  # read-only para el agente


@dataclass
class MemoryBlock:
    label: BlockLabel
    value: str
    read_only: bool = False
    max_chars: int = 2000
    updated_at: float = field(default_factory=time.time)

    def truncated(self) -> str:
        if len(self.value) <= self.max_chars:
            return self.value
        return self.value[: self.max_chars - 20] + "…[truncado]"


class BlockStore:
    """Persiste bloques en un JSON simple (más auditable que DB para esto)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (DATA_DIR / "blocks.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._blocks: dict[str, MemoryBlock] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                for label, info in data.items():
                    self._blocks[label] = MemoryBlock(
                        label=BlockLabel(label),
                        value=info["value"],
                        read_only=info.get("read_only", False),
                        max_chars=info.get("max_chars", 2000),
                        updated_at=info.get("updated_at", time.time()),
                    )
            except Exception:
                pass
        # asegura que existan los defaults
        defaults = {
            BlockLabel.HUMAN: (False, 2000, ""),
            BlockLabel.PERSONA: (False, 1500, ""),
            BlockLabel.STYLE: (False, 3000, ""),
            BlockLabel.SAFETY: (True, 2000, self._default_safety()),
        }
        for label, (ro, mx, val) in defaults.items():
            if label.value not in self._blocks:
                self._blocks[label.value] = MemoryBlock(
                    label=label, value=val, read_only=ro, max_chars=mx
                )

    @staticmethod
    def _default_safety() -> str:
        return (
            "Límites innegociables: nunca filtrar contraseñas, tokens o secretos. "
            "Nunca ejecutar operaciones destructivas (rm -rf, mkfs, dd, reboot) sin confirmación explícita. "
            "Ante duda sobre una acción irreversible, preguntar antes de actuar."
        )

    def get(self, label: BlockLabel | str) -> MemoryBlock | None:
        key = label.value if isinstance(label, BlockLabel) else label
        return self._blocks.get(key)

    def all(self) -> list[MemoryBlock]:
        return list(self._blocks.values())

    def update(self, label: BlockLabel | str, new_value: str, *, force: bool = False) -> tuple[bool, str]:
        """Actualiza un bloque. Falla si es read-only sin force."""
        key = label.value if isinstance(label, BlockLabel) else label
        block = self._blocks.get(key)
        if block is None:
            return False, f"Bloque desconocido: {key}"
        if block.read_only and not force:
            return False, f"Bloque de solo lectura: {key}"
        block.value = new_value
        block.updated_at = time.time()
        self._save()
        return True, f"Bloque '{key}' actualizado ({len(new_value)} chars)."

    def context_string(self) -> str:
        """Serializa los bloques para inyectar en el system prompt."""
        parts = []
        for b in self.all():
            parts.append(f"[{b.label.value}]\n{b.truncated()}")
        return "\n\n".join(parts)

    def _save(self) -> None:
        data = {
            k: {
                "value": b.value,
                "read_only": b.read_only,
                "max_chars": b.max_chars,
                "updated_at": b.updated_at,
            }
            for k, b in self._blocks.items()
        }
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


# Singleton
BLOCKS = BlockStore()
