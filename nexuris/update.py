"""Mantenimiento de Nexuris: repo, dependencias y modelo al día.

    nexuris update              actualiza todo (git pull, pip, modelo, tests)
    nexuris update --check      solo informa qué hay para actualizar
    nexuris update --no-model   no toca el modelo
    nexuris update --no-pull    no hace git pull

El modelo se elige consultando OpenRouter: modelos gratuitos que soporten
tool calling, ordenados por contexto y proveedor, y validados con una llamada
real antes de guardarlos en ~/.config/nexuris/config.json.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .core.config import (
    CONFIG,
    FALLBACK_MODEL,
    REPO_DIR,
    USER_CONFIG_PATH,
    load_user_config,
    save_user_config,
)

MODELS_URL = "https://openrouter.ai/api/v1/models"
MIN_CONTEXT = 32_768
MAX_CANDIDATES = 6

# Preferencia por proveedor (los que suelen respetar mejor las tools)
PROVIDER_BONUS = {
    "anthropic": 6,
    "openai": 6,
    "google": 4,
    "meta-llama": 3,
    "mistralai": 3,
    "qwen": 3,
    "deepseek": 3,
    "nvidia": 2,
    "cohere": 2,
    "x-ai": 2,
    "moonshotai": 2,
    "z-ai": 1,
    "minimax": 1,
}

_SMALL_RE = re.compile(r"\b(\d+(?:\.\d+)?)b\b", re.IGNORECASE)


# --------------------------------------------------------------------------
# Selección de modelo (puro, testeable sin red)
# --------------------------------------------------------------------------
def _price_zero(value) -> bool:
    try:
        return float(value) == 0.0
    except (TypeError, ValueError):
        return False


def is_free(model: dict) -> bool:
    pricing = model.get("pricing") or {}
    return _price_zero(pricing.get("prompt")) and _price_zero(pricing.get("completion"))


def supports_tools(model: dict) -> bool:
    return "tools" in (model.get("supported_parameters") or [])


def score(model: dict) -> float:
    model_id = str(model.get("id", ""))
    name = str(model.get("name", ""))
    provider = model_id.split("/")[0].lower()
    context = int(model.get("context_length") or 0)

    points = math.log2(max(context, 1))
    points += PROVIDER_BONUS.get(provider, 0)

    text = f"{model_id} {name}".lower()
    if any(tag in text for tag in ("preview", "experimental", "beta", "alpha")):
        points -= 3
    if any(tag in text for tag in ("small", "mini", "nano", "tiny", "lite")):
        points -= 2
    for match in _SMALL_RE.finditer(text):
        try:
            if float(match.group(1)) < 20:
                points -= 4
                break
        except ValueError:
            continue
    if model_id == FALLBACK_MODEL:
        points -= 100  # solo como último recurso
    return points


def candidates(models: list[dict], limit: int = MAX_CANDIDATES) -> list[dict]:
    usable = [
        m
        for m in models
        if is_free(m)
        and supports_tools(m)
        and int(m.get("context_length") or 0) >= MIN_CONTEXT
    ]
    usable.sort(key=score, reverse=True)
    return usable[:limit]


# --------------------------------------------------------------------------
# Red
# --------------------------------------------------------------------------
def fetch_models(timeout: float = 25.0) -> list[dict]:
    import httpx

    response = httpx.get(MODELS_URL, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    return data.get("data", []) if isinstance(data, dict) else []


def _tool_call(client, model_id: str, prompt: str, tools: list[dict]):
    """Un turno pidiendo tools. Devuelve los tool_calls o None."""
    resp = client.chat.completions.create(
        model=model_id,
        messages=[{"role": "user", "content": prompt}],
        tools=tools,
        tool_choice="auto",
        max_tokens=120,
    )
    return getattr(resp.choices[0].message, "tool_calls", None)


PING_TOOL = {
    "type": "function",
    "function": {
        "name": "ping",
        "description": "Responde pong. Usala siempre que te lo pidan.",
        "parameters": {"type": "object", "properties": {}},
    },
}

WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Devuelve el clima de una ciudad.",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string", "description": "Ciudad"}},
            "required": ["city"],
        },
    },
}


def validate_model(model_id: str, api_key: str, timeout: float = 30.0) -> tuple[bool, str]:
    """Dos pruebas reales: llamar una tool sin args y otra con args válidos."""
    import json as _json

    from openai import OpenAI

    client = OpenAI(
        base_url=CONFIG.llm.base_url,
        api_key=api_key,
        timeout=timeout,
        max_retries=0,
    )

    try:
        calls = _tool_call(client, model_id, "Usá la tool ping para responderme.", [PING_TOOL])
        if not calls or calls[0].function.name != "ping":
            return False, "no llamó ping"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {str(exc)[:100]}"

    try:
        calls = _tool_call(
            client,
            model_id,
            "¿Qué clima hace en Bogotá? Usá la tool get_weather.",
            [WEATHER_TOOL],
        )
        if not calls or calls[0].function.name != "get_weather":
            return False, "no llamó get_weather"
        try:
            args = _json.loads(calls[0].function.arguments or "{}")
        except _json.JSONDecodeError:
            return False, "argumentos inválidos"
        if not str(args.get("city", "")).strip():
            return False, "get_weather sin ciudad"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {str(exc)[:100]}"

    return True, "tools OK (ping + args)"


# --------------------------------------------------------------------------
# Acciones
# --------------------------------------------------------------------------
def refresh_model(dry_run: bool = False, api_key: str | None = None, verbose: bool = True) -> dict:
    """Elige el mejor modelo gratis con tools y lo persiste."""
    models = fetch_models()
    options = candidates(models)
    if not options:
        raise RuntimeError("no encontré modelos gratuitos con soporte de tools")

    key = api_key or CONFIG.llm.api_key
    chosen: dict | None = None
    reason = ""

    if not key:
        chosen = options[0]
        reason = "sin API key: elegido por ranking, sin validar"
    else:
        for option in options:
            ok, why = validate_model(option["id"], key)
            if verbose:
                mark = "✓" if ok else "✗"
                print(f"    {mark} {option['id']}  ({why})")
            if ok:
                chosen = option
                reason = why
                break
        if chosen is None:
            chosen = {
                "id": FALLBACK_MODEL,
                "name": "Free Models Router",
                "context_length": 200_000,
            }
            reason = "ninguno validó: uso el router gratuito"

    result = {
        "model": chosen["id"],
        "name": chosen.get("name", ""),
        "context": chosen.get("context_length"),
        "reason": reason,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "alternatives": [m["id"] for m in options if m["id"] != chosen["id"]],
    }
    if not dry_run:
        save_user_config(model=chosen["id"], model_info=result)
    return result


def _git(repo: Path, *args: str, timeout: float = 90) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def git_status(repo: Path) -> tuple[bool, str]:
    """(hay_repo, estado) con estado en {'clean','dirty','nogit'}."""
    if not (repo / ".git").exists():
        return False, "nogit"
    try:
        out = _git(repo, "status", "--porcelain", timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return False, "nogit"
    return True, ("dirty" if out.stdout.strip() else "clean")


def pull(repo: Path) -> tuple[bool, str]:
    has_repo, state = git_status(repo)
    if not has_repo:
        return False, "el paquete no es un checkout git (instalación desde PyPI)"
    if state == "dirty":
        return False, "hay cambios locales sin commitear: no hago pull"
    try:
        out = _git(repo, "pull", "--ff-only")
    except subprocess.TimeoutExpired:
        return False, "git pull tardó demasiado"
    if out.returncode != 0:
        return False, (out.stderr or out.stdout).strip().splitlines()[-1] if (out.stderr or out.stdout) else "git pull falló"
    text = (out.stdout or "").strip()
    if "Already up to date" in text or "Ya está actualizado" in text:
        return True, "ya estaba al día"
    return True, text.splitlines()[-1] if text else "actualizado"


def reinstall(repo: Path) -> tuple[bool, str]:
    if not (repo / "pyproject.toml").exists():
        return False, "no encontré pyproject.toml"
    try:
        out = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "-e", str(repo)],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return False, "pip tardó demasiado"
    if out.returncode != 0:
        detail = (out.stderr or out.stdout or "").strip().splitlines()
        return False, detail[-1] if detail else "pip falló"
    return True, "dependencias al día"


def offline_tests(repo: Path) -> tuple[bool, str]:
    tests = [repo / "tests" / name for name in ("test_install.py", "test_learning.py")]
    missing = [t.name for t in tests if not t.exists()]
    for test in tests:
        if not test.exists():
            continue
        out = subprocess.run(
            [sys.executable, str(test)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if out.returncode != 0:
            tail = (out.stderr or out.stdout or "").strip().splitlines()
            return False, f"{test.name}: {tail[-1] if tail else 'falló'}"
    if missing:
        return True, f"tests omitidos: {', '.join(missing)}"
    return True, "tests OK"


def _repo_path() -> Path:
    """Raíz del repo si está disponible (editable); si no, el paquete instalado."""
    return Path(REPO_DIR)


def check() -> int:
    repo = _repo_path()
    print("== Nexuris — chequeo de actualizaciones ==\n")

    has_repo, state = git_status(repo)
    if has_repo:
        try:
            _git(repo, "fetch", "--quiet", timeout=60)
            counts = _git(repo, "rev-list", "--count", "HEAD..@{u}", timeout=20)
            behind = counts.stdout.strip() or "?"
            print(f"repo:   {repo}")
            print(f"git:    {state} · commits nuevos en origin: {behind}")
        except (OSError, subprocess.TimeoutExpired):
            print(f"repo:   {repo}\ngit:    sin red o sin upstream")
    else:
        print(f"repo:   no es un checkout git ({repo})")

    current = CONFIG.llm.model
    print(f"\nmodelo actual: {current}")
    try:
        options = candidates(fetch_models())
    except Exception as exc:  # noqa: BLE001
        print(f"modelos: no pude consultar OpenRouter ({type(exc).__name__})")
        return 1

    print("mejores gratis con tools (ranking; el update los valida con llamadas reales):")
    for i, option in enumerate(options[:5], 1):
        mark = " ← actual" if option["id"] == current else ""
        print(f"  {i}. {option['id']}  ({option.get('context_length')} ctx){mark}")

    top = options[0]["id"] if options else None
    if top and top != current:
        print(f"\n→ hay candidatos nuevos (top del ranking: {top})")
        print("  corré: nexuris update  (los valida con llamadas reales antes de cambiar)")
    else:
        print("\n→ el modelo actual ya es el top del ranking")
    return 0


def run(
    do_pull: bool = True,
    do_model: bool = True,
    do_tests: bool = True,
) -> int:
    repo = _repo_path()
    print("== Nexuris — actualización ==\n")
    failures = 0

    if do_pull:
        ok, detail = pull(repo)
        print(f"{'✓' if ok else '!'} repo: {detail}")

    if (repo / "pyproject.toml").exists():
        ok, detail = reinstall(repo)
        print(f"{'✓' if ok else '✗'} deps: {detail}")
        failures += 0 if ok else 1

    if do_model:
        print("modelo:")
        try:
            picked = refresh_model()
            previous = CONFIG.llm.model
            print(f"  ✓ elegido: {picked['model']}  ({picked['reason']})")
            if picked["model"] != previous:
                print(f"    antes: {previous}")
            print(f"    guardado en {USER_CONFIG_PATH}")
            CONFIG.llm.model = picked["model"]
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  ✗ no pude refrescar el modelo: {type(exc).__name__}: {exc}")

    if do_tests:
        ok, detail = offline_tests(repo)
        print(f"{'✓' if ok else '✗'} tests: {detail}")
        failures += 0 if ok else 1

    print()
    if failures:
        print(f"Terminó con {failures} problema(s).")
        return 1
    print("Todo actualizado. Reiniciá opencode para que tome el MCP nuevo.")
    return 0


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nexuris update",
        description="Actualiza Nexuris: repo, dependencias, modelo y tests.",
    )
    parser.add_argument("--check", action="store_true", help="solo informar, no cambiar nada")
    parser.add_argument("--no-pull", action="store_true", help="no hacer git pull")
    parser.add_argument("--no-model", action="store_true", help="no refrescar el modelo")
    parser.add_argument("--no-tests", action="store_true", help="no correr los tests")
    args = parser.parse_args(argv)

    if args.check:
        return check()
    return run(do_pull=not args.no_pull, do_model=not args.no_model, do_tests=not args.no_tests)


def main() -> None:
    raise SystemExit(cli())


if __name__ == "__main__":
    main()
