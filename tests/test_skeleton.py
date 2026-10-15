"""Test rápido del esqueleto: imports, registro de tools, schemas."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nexuris.bootstrap import build_agent
from nexuris.tools.registry import REGISTRY


def main() -> None:
    print("== Nexo 2.0 — test esqueleto ==\n")

    # 1. Construir agente (esto carga las tools core)
    agent = build_agent()
    print(f"Tools registradas ({len(REGISTRY.names())}):")
    for name in REGISTRY.names():
        t = REGISTRY.get(name)
        print(f"  - {name:15} perm={t.permission.value:5} tags={t.tags}")

    # 2. Ver specs JSON que ve Claude
    specs = REGISTRY.specs()
    print(f"\nSpecs JSON generados: {len(specs)}")
    import json
    print(json.dumps(specs[0], indent=2, ensure_ascii=False)[:400])

    # 3. Probar una tool directamente (sin LLM)
    print("\n-- probando system_info() --")
    info = REGISTRY.invoke("system_info", {})
    print(info)

    # 4. Probar memoria
    print("\n-- probando remember/recall --")
    REGISTRY.invoke("remember", {"fact": "miku prefiere Claude como cerebro de Nexo 2.0"})
    hits = REGISTRY.invoke("recall", {"query": "cerebro"})
    print("recall('cerebro') ->", hits)

    print("\n✅ Esqueleto OK. Loop LLM se prueba aparte con API key.")


if __name__ == "__main__":
    main()
