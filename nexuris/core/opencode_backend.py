"""Nexo 2.0 — Backend cloud: la CLI delega sus turnos en opencode (camino A).

Decidido con miku: en vez de correr el loop propio contra OpenRouter
(sin API key hoy), la CLI standalone manda cada turno a una sesión de
opencode con agent=nexuris — mismo modelo, misma persona (agents/nexuris.md)
y mismas tools (MCP nexuris) que la sesión interactiva de la TUI.

La memoria se sincroniza como *instruction entries* de la sesión: opencode
las inyecta al final del system prompt en cada request (docs/instructions).

Todo vía subprocesos de `opencode api` / `opencode run`, que manejan la
autenticación del servicio de fondo. Sin keys, sin HTTP directo.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

log = logging.getLogger("nexuris.opencode")

OPENCODE_BIN = shutil.which("opencode")

# Modelo de la sesión delegada. Importante: el default del servicio es
# "big-pickle", que ignora instruction entries — por eso es explícito.
DEFAULT_CLOUD_MODEL = "opencode/mimo-v2.6-flash-free"


class OpenCodeError(RuntimeError):
    """Error hablando con el servicio de opencode."""


class OpenCodeUnavailable(OpenCodeError):
    """opencode no está instalado o el servicio no responde."""


def parse_model(spec: str) -> tuple[str, str]:
    """'provider/model' o 'model' → (providerID, modelID)."""
    spec = (spec or "").strip()
    if not spec:
        return parse_model(DEFAULT_CLOUD_MODEL)
    if "/" in spec:
        provider, _, model = spec.partition("/")
        return (provider or "opencode"), model
    return "opencode", spec


def _run(args: list[str], timeout: float | None = None) -> subprocess.CompletedProcess:
    """Corre `opencode <args>`. Lanza OpenCodeError si sale con error."""
    if OPENCODE_BIN is None:
        raise OpenCodeUnavailable("no encontré el binario `opencode` en el PATH.")
    try:
        proc = subprocess.run(
            [OPENCODE_BIN, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            # stdin apartado: la CLI usa su propio stdin para input()
            stdin=subprocess.DEVNULL,
            # la sesión vive en el home (asistente del hogar, no del cwd)
            cwd=str(Path.home()),
        )
    except subprocess.TimeoutExpired:
        raise OpenCodeError(f"opencode {' '.join(args[:2])} superó el tiempo límite ({timeout}s)")
    if proc.returncode != 0:
        detail = ((proc.stdout or "") + (proc.stderr or "")).strip()
        raise OpenCodeError(f"opencode falló: {detail[-600:]}")
    return proc


def _api(method: str, path: str, data: dict[str, Any] | None = None, timeout: float = 30.0) -> dict:
    """Llama a la API del servicio: `opencode api <method> <path> [-d json]`."""
    args = ["api", method, path]
    if data is not None:
        args += ["-d", json.dumps(data, ensure_ascii=False)]
    proc = _run(args, timeout=timeout)
    out = (proc.stdout or "").strip()
    if not out:
        return {}
    try:
        body = json.loads(out)
    except json.JSONDecodeError:
        raise OpenCodeError(f"respuesta ilegible de opencode: {out[:300]}")
    if isinstance(body, dict) and body.get("_tag"):
        raise OpenCodeError(str(body.get("message") or body["_tag"]))
    return body if isinstance(body, dict) else {}


def _extract_reply(stream: str) -> str:
    """Última respuesta de un stream `opencode run --format json` (JSONL).

    Los eventos text traen el estado completo del part (snapshot) o un
    delta; se absorbe ambos casos. Cada ronda de tools es un messageID
    nuevo, así que queda la del último mensaje.
    """
    texts: dict[str, str] = {}
    order: list[str] = []
    reason: str | None = None
    for line in stream.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        etype = ev.get("type")
        if etype == "text":
            part = ev.get("part") or {}
            mid = str(part.get("messageID") or "?")
            chunk = part.get("text") or ""
            if mid not in texts:
                order.append(mid)
                texts[mid] = chunk
            else:
                cur = texts[mid]
                texts[mid] = chunk if chunk.startswith(cur) else cur + chunk
        elif etype == "step_finish":
            reason = (ev.get("part") or {}).get("reason") or reason
    if order:
        reply = texts[order[-1]].strip()
        if reply:
            return reply
    raise OpenCodeError(f"sin respuesta (reason={reason})")


def ensure_available() -> None:
    """Garantiza binario + servicio. Intenta arrancar el servicio si hace falta."""
    if OPENCODE_BIN is None:
        raise OpenCodeUnavailable(
            "no encontré el binario `opencode` en el PATH. "
            "La CLI delega su cerebro en opencode (camino A)."
        )
    for attempt in range(5):
        try:
            _run(["api", "get", "/api/info"], timeout=10.0)
            return
        except OpenCodeError as exc:
            if attempt == 0:
                log.info("servicio opencode no responde (%s) — intentando `service start`", exc)
                try:
                    _run(["service", "start"], timeout=20.0)
                except OpenCodeError as start_exc:
                    log.warning("service start: %s", start_exc)
            time.sleep(1.0)
    raise OpenCodeUnavailable(
        "el servicio de opencode no responde. Arrancalo con: `opencode service start`"
    )


class OpenCodeClient:
    """Cliente liviano de la API de opencode para la CLI de Nexuris."""

    def __init__(self, model: str | None = None) -> None:
        self.provider, self.model_id = parse_model(model)

    @property
    def model(self) -> str:
        return f"{self.provider}/{self.model_id}"

    def create_session(self, title: str) -> str:
        """Crea la sesión delegada (agent=nexuris, modelo explícito)."""
        body = {
            "agent": "nexuris",
            "model": {"providerID": self.provider, "id": self.model_id},
            "title": title,
        }
        resp = _api("post", "/api/session", body)
        sid = (resp.get("data") or {}).get("id")
        if not sid:
            raise OpenCodeError(f"respuesta inesperada al crear sesión: {str(resp)[:200]}")
        return str(sid)

    def put_instructions(self, sid: str, entries: dict[str, str]) -> None:
        """Upsert de instruction entries (la memoria entra por acá)."""
        for key, value in entries.items():
            _api(
                "put",
                f"/api/experimental/session/{sid}/instructions/entries/{key}",
                {"value": value},
            )

    def set_model(self, sid: str, spec: str) -> str:
        """Cambia el modelo de la sesión en curso."""
        provider, model_id = parse_model(spec)
        _api(
            "post",
            f"/api/session/{sid}/model",
            {"model": {"providerID": provider, "id": model_id}},
        )
        self.provider, self.model_id = provider, model_id
        return self.model

    def run_turn(self, sid: str, text: str, timeout: float = 300.0) -> str:
        """Un turno completo contra la sesión delegada. Devuelve la respuesta."""
        proc = _run(
            ["run", "--session", sid, "--format", "json", "--", text],
            timeout=timeout,
        )
        for stream in (proc.stdout or "", proc.stderr or ""):
            try:
                return _extract_reply(stream)
            except OpenCodeError:
                continue
        detail = ((proc.stdout or "") + (proc.stderr or "")).strip()
        raise OpenCodeError(f"sin respuesta de opencode: {detail[-400:]}")

    def run_archived(self, prompt: str, timeout: float = 300.0) -> str:
        """Turno en una sesión descartable (fallback de consolidación)."""
        proc = _run(
            [
                "run", "--archived", "--agent", "nexuris",
                "--model", self.model,
                "--title", "nexuris-consolidacion",
                "--format", "json", "--", prompt,
            ],
            timeout=timeout,
        )
        for stream in (proc.stdout or "", proc.stderr or ""):
            try:
                return _extract_reply(stream)
            except OpenCodeError:
                continue
        raise OpenCodeError("sin respuesta de opencode en el fallback")

    def generate_text(self, prompt: str, timeout: float = 120.0) -> str:
        """Texto puro sin tools (para la consolidación sleep-time)."""
        body = _api(
            "post",
            "/api/experimental/generate/text",
            {
                "prompt": prompt,
                "model": {"providerID": self.provider, "id": self.model_id},
            },
            timeout=timeout,
        )
        text = str(((body.get("data") or {}).get("text")) or "").strip()
        if not text:
            raise OpenCodeError("generate/text devolvió vacío")
        return text


class CloudTextLLM:
    """Adaptador con la forma de LLMClient para consolidate().

    Primero intenta generate/text (rápudo, sin sesiones); si el servicio
    lo rechaza (p. ej. rate limit de modelos gratis), cae a un turno en
    una sesión archivada — que durante el rate limit siguió funcionando.
    """

    def __init__(self, client: OpenCodeClient) -> None:
        self._client = client

    def chat(self, messages: list[dict[str, Any]]) -> Any:
        prompt = ""
        for m in messages:
            if m.get("role") == "user" and m.get("content"):
                prompt = str(m["content"])
        if not prompt:
            raise OpenCodeError("consolidación sin prompt")
        try:
            text = self._client.generate_text(prompt)
        except OpenCodeError as exc:
            short = str(exc)
            if "rate_limit" in short:
                short = "límite de uso gratuito (rate limit)"
            log.warning("generate/text no disponible (%s) — fallback vía sesión", short)
            text = self._client.run_archived(prompt)
        return SimpleNamespace(text=text)
