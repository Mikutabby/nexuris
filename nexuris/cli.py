"""Nexo 2.0 — CLI interactiva.

Charlá con Nexo desde la terminal. Comandos:
  /salir     cierra la sesión y consolida la memoria (sleep-time)
  /feedback  registra feedback sobre la última respuesta (bien/mal)
  /bloques   muestra los bloques de memoria
  /hechos    muestra los últimos hechos guardados
  /ayuda     muestra esta ayuda
  /modelo    cambia el modelo (string de OpenRouter) y lo recuerda

Fuera de la charla:
  nexuris update        actualiza repo, dependencias, modelo y tests
  nexuris update --check   solo muestra qué hay para actualizar
"""
from __future__ import annotations

import sys
from pathlib import Path

# asegura que el paquete sea importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nexuris.bootstrap import build_agent
from nexuris.core.config import CONFIG, save_user_config
from nexuris.learn.feedback import FeedbackKind
from nexuris.memory.blocks import BLOCKS, BlockLabel
from nexuris.memory.store import STORE
from nexuris.session import Session


def _print_blocks() -> None:
    print("\n-- bloques de memoria --")
    for b in BLOCKS.all():
        ro = " [solo lectura]" if b.read_only else ""
        print(f"\n[{b.label.value}]{ro} ({len(b.value)} chars):")
        print(b.value[:400] + ("…" if len(b.value) > 400 else ""))


def _print_facts() -> None:
    print("\n-- últimos hechos --")
    facts = STORE.recent_facts(limit=15)
    if not facts:
        print("(sin hechos aún)")
    for f in facts:
        print(f"  - {f.content}")


def main() -> None:
    argv = sys.argv[1:]
    if argv and argv[0] in ("update", "actualizar"):
        from nexuris.update import cli as update_cli

        raise SystemExit(update_cli(argv[1:]))
    if argv and argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return

    print("=" * 55)
    print("  NEXO 2.0 — aprendizaje sin guion")
    print(f"  cerebro: {CONFIG.llm.model}")
    print("=" * 55)
    print("Escribí para charlar. /ayuda para comandos.\n")

    agent = build_agent()
    session = Session(agent)

    # confirmación para tools ASK
    def confirm(name, args):
        print(f"\n  [permiso] Nexo quiere usar '{name}'({args})")
        resp = input("  ¿Permitir? [s/N] ").strip().lower()
        return resp in ("s", "si", "y", "yes")

    agent.confirm = confirm

    while True:
        try:
            user_input = input("miku> ").strip()
        except (EOFError, KeyboardInterrupt):
            user_input = "/salir"

        if not user_input:
            continue

        # comandos
        if user_input.startswith("/"):
            cmd = user_input.split()[0].lower()
            arg = user_input[len(cmd):].strip()

            if cmd == "/salir":
                print("\nCerrando sesión y consolidando memoria…")
                result = session.close()
                if result:
                    print(f"  facts: {len(result.facts)} nuevos")
                    if result.style_notes:
                        print(f"  estilo: {result.style_notes[:120]}")
                print("Chau. La memoria quedó guardada.\n")
                break
            elif cmd == "/feedback":
                kind = arg or input("  tipo (bien/mal): ").strip().lower()
                mapping = {
                    "bien": FeedbackKind.EXPLICIT_POS,
                    "mal": FeedbackKind.EXPLICIT_NEG,
                    "acepto": FeedbackKind.ACCEPTED,
                    "corrigio": FeedbackKind.CORRECTED,
                    "repitio": FeedbackKind.REPEATED,
                    "ignoro": FeedbackKind.IGNORED,
                }
                fk = mapping.get(kind)
                if fk:
                    print(" ", session.feedback(fk))
                else:
                    print("  Tipos: bien, mal, acepto, corrigio, repitio, ignoro")
            elif cmd == "/bloques":
                _print_blocks()
            elif cmd == "/hechos":
                _print_facts()
            elif cmd == "/modelo":
                if arg:
                    CONFIG.llm.model = arg
                    agent.llm.config.model = arg
                    save_user_config(model=arg)
                    print(f"  Modelo cambiado a: {arg} (guardado en config)")
                else:
                    print(f"  Modelo actual: {CONFIG.llm.model}")
            elif cmd == "/ayuda":
                print(__doc__)
            else:
                print(f"  Comando desconocido: {cmd}. Probá /ayuda.")
            continue

        # turno normal
        try:
            reply = session.ask(user_input)
            print(f"nexuris> {reply}\n")
        except Exception as e:
            print(f"  [error] {type(e).__name__}: {e}\n")


if __name__ == "__main__":
    main()
