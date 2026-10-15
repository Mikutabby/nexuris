"""Test end-to-end: loop ReAct real con Claude (filosofía de aprendizaje)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nexuris.bootstrap import build_agent
from nexuris.core.config import CONFIG


def main() -> None:
    print("== Nexo 2.0 — test loop con Claude (aprendizaje) ==\n")
    if not CONFIG.llm.api_key:
        print("❌ No hay API key de OpenRouter. Setea NEXO_OPENROUTER_KEY.")
        sys.exit(1)

    print(f"Cerebro: {CONFIG.llm.model}")
    agent = build_agent()

    def confirm(name, args):
        print(f"   [permiso ASK] {name}({args}) -> auto-aprobado en test")
        return True

    agent.confirm = confirm

    pruebas = [
        "Hola, ¿quién sos?",
        "¿Cómo está el disco de esta PC?",
        "Contame algo sobre mí que hayas aprendido.",
    ]

    for q in pruebas:
        print(f"\n> miku: {q}")
        r = agent.run(q)
        print(f"< nexuris: {r}")

    print("\n✅ Loop end-to-end OK.")


if __name__ == "__main__":
    main()
