"""Test del ciclo de aprendizaje completo: sesión → feedback → consolidación."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nexuris.bootstrap import build_agent
from nexuris.session import Session
from nexuris.learn.feedback import FeedbackKind
from nexuris.memory.blocks import BLOCKS, BlockLabel


def main() -> None:
    print("== Nexo 2.0 — test ciclo de aprendizaje ==\n")

    agent = build_agent()
    session = Session(agent)

    def confirm(name, args):
        return True

    agent.confirm = confirm

    # 1. Charla
    print("-- sesión --")
    r1 = session.ask("Hola Nexo, estoy probando tu sistema de aprendizaje nuevo.")
    print(f"> miku: Hola Nexo, estoy probando tu sistema de aprendizaje nuevo.")
    print(f"< nexuris: {r1}")

    r2 = session.ask("¿Qué herramientas tenés disponibles?")
    print(f"\n> miku: ¿Qué herramientas tenés disponibles?")
    print(f"< nexuris: {r2}")

    # 2. Feedback explícito positivo
    print("\n-- feedback --")
    msg = session.feedback(FeedbackKind.EXPLICIT_POS, detail="me gustó la respuesta clara")
    print(msg)

    # 3. Consolidación (sleep-time)
    print("\n-- consolidación (sleep-time) --")
    result = session.close()
    if result:
        print(f"facts extraídos: {result.facts}")
        print(f"style_notes: {result.style_notes[:200] if result.style_notes else '(ninguna)'}")
        print(f"human_update: {'sí' if result.human_update else 'no'}")
        print(f"persona_update: {'sí' if result.persona_update else 'no'}")
    else:
        print("(sin consolidación — poca historia)")

    # 4. Verificar que los bloques y hechos se actualizan
    print("\n-- estado de memoria tras consolidar --")
    human = BLOCKS.get(BlockLabel.HUMAN)
    persona = BLOCKS.get(BlockLabel.PERSONA)
    print(f"human ({len(human.value)} chars): {human.value[:150]}")
    print(f"persona ({len(persona.value)} chars): {persona.value[:150]}")

    from nexuris.memory.store import STORE
    print(f"hechos totales en store: {STORE.count()}")

    print("\n✅ Ciclo de aprendizaje OK.")


if __name__ == "__main__":
    main()
