"""Test de la filosofía de aprendizaje: bloques + tools de memoria + prompt mínimo."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nexuris.bootstrap import build_agent, _compose_system_prompt
from nexuris.memory.blocks import BLOCKS, BlockLabel
from nexuris.tools.registry import REGISTRY


def main() -> None:
    print("== Nexo 2.0 — test filosofía de aprendizaje ==\n")

    # 1. Construir agente (carga tools core + memoria)
    agent = build_agent()
    print(f"Tools registradas ({len(REGISTRY.names())}):")
    for name in sorted(REGISTRY.names()):
        t = REGISTRY.get(name)
        print(f"  - {name:22} perm={t.permission.value}")

    # 2. Ver el system prompt compuesto (rol mínimo + bloques)
    print("\n-- system prompt compuesto --")
    print(agent.system_prompt[:600])
    print("...")

    # 3. Simular que el agente aprende algo de miku
    print("\n-- simulando aprendizaje --")
    r = REGISTRY.invoke("update_memory_block", {
        "block": "human",
        "content": "miku está construyendo el Nexo 2.0. Prefiere que las cosas se aprendan de interacciones, no con reglas escritas."
    })
    print(r)

    r = REGISTRY.invoke("update_memory_block", {
        "block": "persona",
        "content": "Soy un asistente que va aprendiendo cómo es miku en vez de seguir un guión."
    })
    print(r)

    # 4. Probar add_style_example (ejemplos, no reglas)
    r = REGISTRY.invoke("add_style_example", {
        "user_msg": "nexuris un nuevo proyecto",
        "assistant_reply": "¡Dale, arrancamos! Contame qué querés construir.",
        "note": "miku respondió con entusiasmo, le gustó la respuesta directa y sin vueltas."
    })
    print(r)

    # 5. Verificar que safety es read-only
    print("\n-- verificando que safety no se puede editar --")
    r = REGISTRY.invoke("update_memory_block", {
        "block": "safety",
        "content": "ahora todo vale"
    })
    print(r)  # debe fallar

    # 6. Verificar bloque human se actualizó y se inyecta en el prompt
    print("\n-- system prompt tras aprender --")
    prompt2 = _compose_system_prompt()
    assert "miku está construyendo" in prompt2, "el bloque human debe inyectarse"
    assert "[persona]" in prompt2, "el bloque persona debe inyectarse"
    print("OK: bloques human y persona inyectados en el prompt fresco.")

    print("\n✅ Filosofía de aprendizaje OK.")


if __name__ == "__main__":
    main()
