"""Nexo 2.0 — CLI interactiva (cerebro delegado en opencode).

Charlá con Nexuris desde la terminal. Los turnos van a una sesión de
opencode con agent=nexuris — mismo modelo, persona y tools que la sesión
interactiva — y la memoria local se inyecta como instruction entries.

Comandos:
  /salir     cierra la sesión y consolida la memoria (sleep-time)
  /feedback  registra feedback sobre la última respuesta (bien/mal)
  /bloques   muestra los bloques de memoria
  /hechos    muestra los últimos hechos guardados
  /modelo    cambia el modelo (provider/model de opencode) y lo recuerda
  /ayuda     muestra esta ayuda

Fuera de la charla:
  nexuris update        actualiza repo, dependencias, modelo y tests
  nexuris update --check   solo muestra qué hay para actualizar
"""
from __future__ import annotations

import sys
from pathlib import Path

# asegura que el paquete sea importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nexuris.cloud_session import CloudSession
from nexuris.core.config import save_user_config
from nexuris.core.opencode_backend import OpenCodeError, OpenCodeUnavailable
from nexuris.learn.feedback import FeedbackKind
from nexuris.memory.blocks import BLOCKS
from nexuris.memory.store import STORE


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
    print("  cerebro: opencode (delegado)")
    print("=" * 55)
    print("Escribí para charlar. /ayuda para comandos.\n")

    try:
        session = CloudSession()
    except OpenCodeUnavailable as e:
        print(f"  [error] {e}\n")
        return
    except OpenCodeError as e:
        print(f"  [error] no pude crear la sesión: {e}\n")
        return
    print(f"  sesión: {session.session_id}  modelo: {session.model}\n")

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
                elif getattr(session, "pending_saved", False):
                    print("  (rate limit de modelos gratis — el sueño queda")
                    print("   pendiente y se consolida en el próximo arranque)")
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
                    try:
                        new_model = session.set_model(arg)
                        save_user_config(model=new_model)
                        print(f"  Modelo cambiado a: {new_model} (guardado en config)")
                    except OpenCodeError as e:
                        print(f"  [error] {e}")
                else:
                    print(f"  Modelo actual: {session.model}")
            elif cmd == "/ayuda":
                print(__doc__)
            else:
                print(f"  Comando desconocido: {cmd}. Probá /ayuda.")
            continue

        # turno normal
        try:
            reply = session.ask(user_input)
            print(f"nexuris> {reply}\n")
        except OpenCodeError as e:
            print(f"  [error] {e}\n")
        except Exception as e:
            print(f"  [error] {type(e).__name__}: {e}\n")


if __name__ == "__main__":
    main()
