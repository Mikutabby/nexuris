#!/usr/bin/env bash
# =============================================================================
#  Nexuris — instalador portable
#  Funciona en Arch, Debian/Ubuntu, Fedora/RHEL, openSUSE, Alpine, Void,
#  Gentoo, Solus, NixOS (manual) y Termux. No requiere root salvo que falten
#  paquetes del sistema y lo autorices.
#
#  Uso:
#    ./install.sh                 instala (venv + deps + registro MCP)
#    ./install.sh --check         diagnostica el entorno, no cambia nada
#    ./install.sh --uninstall     quita venv, lanzadores y entrada MCP
#    ./install.sh --help          ayuda completa
# =============================================================================
set -uo pipefail

REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$REPO_DIR/.venv"
MIN_PY="3.10"

MODE="install"
LINK=1
MCP=1
AGENT=1
FORCE_AGENT=0
DEPS=0
ASSUME_YES=0
RECREATE=0

# ---------- salida -----------------------------------------------------------
if [ -t 1 ] && [ "${NO_COLOR:-}" = "" ]; then
  C_RST=$'\033[0m'; C_B=$'\033[1m'; C_G=$'\033[32m'; C_Y=$'\033[33m'; C_R=$'\033[31m'; C_D=$'\033[2m'
else
  C_RST=""; C_B=""; C_G=""; C_Y=""; C_R=""; C_D=""
fi
say()  { printf '%s\n' "$*"; }
ok()   { printf '%s✓%s %s\n' "$C_G" "$C_RST" "$*"; }
warn() { printf '%s!%s %s\n' "$C_Y" "$C_RST" "$*" >&2; }
err()  { printf '%s✗%s %s\n' "$C_R" "$C_RST" "$*" >&2; }
die()  { err "$*"; exit 1; }
hr()   { printf '%s%s%s\n' "$C_D" "------------------------------------------------------------" "$C_RST"; }
step() { printf '\n%s==%s %s\n' "$C_B" "$C_RST" "$*"; }

usage() {
  cat <<EOF
${C_B}Nexuris — instalador portable${C_RST}

  ./install.sh [opciones]

Opciones:
  --venv DIR        ruta del virtualenv (default: ./.venv junto al repo)
  --no-link         no crea lanzadores en ~/.local/bin
  --no-mcp          no registra el servidor MCP en opencode
  --no-agent        no instala el agente de opencode
  --force-agent     sobrescribe el agente si ya existe (hace backup)
  --recreate        borra y recrea el virtualenv
  --install-deps    instala paquetes del sistema sin preguntar (usa sudo)
  -y, --yes         responde "sí" a todas las preguntas
  --check           solo diagnostica; no modifica nada
  --uninstall       desinstala (deja los datos de memoria salvo --purge)
  --purge           con --uninstall: borra también los datos de memoria
  -h, --help        esta ayuda

Variables de entorno:
  NEXURIS_VENV      igual que --venv
  NEXURIS_MODEL     modelo OpenRouter por defecto (ej: openrouter/free)
  OPENROUTER_API_KEY / NEXO_OPENROUTER_KEY   API key (o se lee de opencode)
  NEXURIS_DATA_DIR  dónde guardar memoria (default ~/.local/share/nexuris)
  NO_COLOR=1        sin colores

Ejemplos:
  ./install.sh                          # instalación normal
  ./install.sh --check                  # ver si falta algo
  ./install.sh --install-deps -y        # instala paquetes del sistema solo
  ./install.sh --uninstall              # desinstalar
EOF
}

# ---------- utilidades -------------------------------------------------------
have() { command -v "$1" >/dev/null 2>&1; }

run_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif have sudo; then
    sudo "$@"
  elif have doas; then
    doas "$@"
  elif have pkexec; then
    pkexec "$@"
  else
    return 127
  fi
}

confirm() {
  [ "$ASSUME_YES" -eq 1 ] && return 0
  printf '%s [s/N] ' "$1"
  local ans=""
  read -r ans || true
  case "$ans" in s|S|si|sí|y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

# ---------- detección --------------------------------------------------------
detect_pm() {
  if [ -n "${TERMUX_VERSION:-}" ] || [ "${PREFIX:-}" = "/data/data/com.termux/files/usr" ]; then
    echo termux; return
  fi
  if [ -f /etc/NIXOS ]; then echo nix; return; fi
  for pm in pacman apt-get dnf zypper apk xbps-install eopkg yum; do
    if have "$pm"; then echo "$pm"; return; fi
  done
  echo none
}

pm_packages() {
  case "$1" in
    pacman)       echo "python python-pip" ;;
    apt-get)      echo "python3 python3-venv python3-pip" ;;
    dnf|yum)      echo "python3 python3-pip" ;;
    zypper)       echo "python3 python3-pip" ;;
    apk)          echo "python3 py3-pip" ;;
    xbps-install) echo "python3 python3-pip" ;;
    eopkg)        echo "python3 python3-pip" ;;
    termux)       echo "python" ;;
    *)            echo "" ;;
  esac
}

pm_install() {
  local pm="$1"; shift
  local pkgs="$*"
  [ -z "$pkgs" ] && return 1
  case "$pm" in
    pacman)       run_root pacman -Sy --needed --noconfirm $pkgs ;;
    apt-get)      run_root apt-get update && run_root apt-get install -y $pkgs ;;
    dnf)          run_root dnf install -y $pkgs ;;
    yum)          run_root yum install -y $pkgs ;;
    zypper)       run_root zypper --non-interactive install $pkgs ;;
    apk)          run_root apk add --no-cache $pkgs ;;
    xbps-install) run_root xbps-install -Sy $pkgs ;;
    eopkg)        run_root eopkg install -y $pkgs ;;
    termux)       pkg install -y $pkgs ;;
    *)            return 1 ;;
  esac
}

py_version_ok() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 10) else 1)' 2>/dev/null
}

find_python() {
  local c
  for c in python3.14 python3.13 python3.12 python3.11 python3.10 python3 python; do
    if have "$c" && py_version_ok "$c"; then echo "$c"; return 0; fi
  done
  return 1
}

venv_ok() {
  "$1" -c 'import venv, ensurepip' >/dev/null 2>&1
}

ensure_system_deps() {
  local pm; pm="$(detect_pm)"
  local pkgs; pkgs="$(pm_packages "$pm")"
  local reason="$1"

  warn "$reason"
  if [ "$pm" = "nix" ]; then
    say ""
    say "  NixOS no se instala sobre la marcha. Opciones:"
    say "    nix-shell -p python3 --run './install.sh'"
    say "    # o en configuration.nix: environment.systemPackages = [ pkgs.python3 pkgs.python3Packages.pip ];"
    die "instalá python3 y volvé a correr ./install.sh"
  fi
  if [ "$pm" = "none" ] || [ -z "$pkgs" ]; then
    die "no reconozco el gestor de paquetes. Instalá python3 (>= $MIN_PY) con soporte de venv y reintentá."
  fi

  local sudo_hint=""
  [ "$(id -u)" -ne 0 ] && have sudo && sudo_hint="sudo "
  say "  se necesitan: ${C_B}${pkgs}${C_RST}   (${sudo_hint}${pm})"

  if [ "$DEPS" -ne 1 ]; then
    if ! confirm "¿Instalo esos paquetes ahora?"; then
      die "faltan dependencias. Reintentá con --install-deps o instalalas a mano."
    fi
  fi
  pm_install "$pm" "$pkgs" || die "falló la instalación de paquetes del sistema."
  ok "paquetes del sistema instalados"
}

# ---------- chequeos ---------------------------------------------------------
check_python() {
  local py=""
  if [ -x "$VENV_DIR/bin/python" ] && py_version_ok "$VENV_DIR/bin/python"; then
    echo "$VENV_DIR/bin/python"; return 0
  fi
  if py="$(find_python)"; then echo "$py"; return 0; fi
  echo ""; return 1
}

resolve_data_dir() {
  if [ -x "$VENV_DIR/bin/python" ]; then
    "$VENV_DIR/bin/python" -c 'from nexuris.core.config import DATA_DIR; print(DATA_DIR)' 2>/dev/null && return 0
  fi
  echo "${NEXURIS_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/nexuris}"
}

check_report() {
  local rc=0
  step "Diagnóstico de Nexuris"

  say "  repo:        $REPO_DIR"
  local pm; pm="$(detect_pm)"
  say "  distro:      $(uname -s) $(uname -m)  (gestor: ${pm})"
  if [ -r /etc/os-release ]; then
    . /etc/os-release 2>/dev/null || true
    say "  sistema:     ${PRETTY_NAME:-desconocido}"
  fi

  local py; py="$(check_python)" || true
  if [ -n "$py" ]; then ok "python: $($py -V 2>&1)  ($py)"; else err "python >= $MIN_PY: no encontrado"; rc=1; fi

  if [ -n "$py" ] && venv_ok "$py"; then ok "venv/ensurepip disponibles"
  else err "venv/ensurepip faltan (Debian/Ubuntu: python3-venv)"; rc=1; fi

  if [ -x "$VENV_DIR/bin/python" ]; then
    ok "virtualenv: $($VENV_DIR/bin/python -V 2>&1)"
    if "$VENV_DIR/bin/python" -c 'import nexuris, openai, httpx' 2>/dev/null; then
      ok "paquete nexuris importable"
    else
      err "paquete nexuris no instalado en el venv"; rc=1
    fi
  else
    err "virtualenv ausente ($VENV_DIR)"; rc=1
  fi

  local data; data="$(resolve_data_dir)"
  if mkdir -p "$data" 2>/dev/null && [ -w "$data" ]; then ok "datos: $data (escribible)"
  else err "datos: $data no es escribible"; rc=1; fi

  if [ -n "${OPENROUTER_API_KEY:-}${NEXO_OPENROUTER_KEY:-}" ]; then
    ok "API key de OpenRouter: en el entorno"
  elif [ -f "${XDG_CONFIG_HOME:-$HOME/.config}/opencode/opencode.jsonc" ]; then
    ok "API key: se leerá del config de opencode"
  else
    warn "API key de OpenRouter: no configurada (exportá OPENROUTER_API_KEY)"
  fi

  local agent="${XDG_CONFIG_HOME:-$HOME/.config}/opencode/agents/nexuris.md"
  if [ -f "$agent" ]; then ok "agente de opencode: $agent"
  else warn "agente de opencode no instalado (./install.sh sin --no-agent)"; fi

  local cfg="${XDG_CONFIG_HOME:-$HOME/.config}/opencode/opencode.jsonc"
  if [ -f "$cfg" ] && grep -q '"nexuris"' "$cfg" 2>/dev/null; then ok "MCP registrado en $cfg"
  else warn "MCP no registrado en opencode (corré ./install.sh sin --no-mcp)"; fi

  if have nexuris; then ok "lanzador 'nexuris' en PATH: $(command -v nexuris)"; else warn "'nexuris' no está en PATH (~/.local/bin?)"; fi

  hr
  [ "$rc" -eq 0 ] && ok "todo en orden" || err "hay cosas para arreglar (corré ./install.sh)"
  return "$rc"
}

# ---------- instalación ------------------------------------------------------
setup_venv() {
  local py="$1"
  if [ "$RECREATE" -eq 1 ] && [ -d "$VENV_DIR" ]; then
    say "borrando venv viejo…"; rm -rf -- "$VENV_DIR"
  fi
  if [ -x "$VENV_DIR/bin/python" ]; then
    ok "venv existente: $VENV_DIR"
  else
    step "Creando virtualenv"
    "$py" -m venv "$VENV_DIR" || die "no pude crear el venv. En Debian/Ubuntu: sudo apt install python3-venv"
    ok "venv creado: $VENV_DIR"
  fi
}

install_package() {
  step "Instalando Nexuris en el venv"
  local pip=("$VENV_DIR/bin/python" -m pip)
  "${pip[@]}" install --quiet --upgrade pip setuptools wheel >/dev/null 2>&1 || warn "no pude actualizar pip (sigo igual)"
  if ! "${pip[@]}" install --quiet -e "$REPO_DIR"; then
    warn "instalación editable falló; probando instalación normal"
    "${pip[@]}" install "$REPO_DIR" || die "pip no pudo instalar el paquete (¿red bloqueada?)"
    ok "paquete instalado (modo normal)"
  else
    ok "paquete instalado (modo editable)"
  fi
}

smoke_test() {
  step "Smoke test"
  local out
  out="$(printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
        | timeout 30 "$VENV_DIR/bin/python" -m nexuris.mcp_server 2>/dev/null || true)"
  if printf '%s' "$out" | grep -q '"tools"'; then ok "servidor MCP responde"; else err "servidor MCP no respondió"; return 1; fi

  if "$VENV_DIR/bin/python" "$REPO_DIR/tests/test_learning.py" >/dev/null 2>&1; then ok "test de aprendizaje"
  else err "test de aprendizaje falló"; return 1; fi

  if [ -f "$REPO_DIR/tests/test_install.py" ]; then
    if "$VENV_DIR/bin/python" "$REPO_DIR/tests/test_install.py" >/dev/null 2>&1; then ok "test de instalación"
    else err "test de instalación falló"; return 1; fi
  fi
  return 0
}

link_launchers() {
  [ "$LINK" -eq 1 ] || return 0
  local bindir="$HOME/.local/bin"
  mkdir -p "$bindir"
  local name target
  for name in nexuris nexuris-mcp; do
    target="$VENV_DIR/bin/$name"
    [ -e "$target" ] || continue
    if [ -e "$bindir/$name" ] && [ ! -L "$bindir/$name" ]; then
      mv -- "$bindir/$name" "$bindir/$name.bak-nexuris-$(date +%Y%m%d-%H%M%S)"
    fi
    ln -sfn "$target" "$bindir/$name" 2>/dev/null || warn "no pude crear $bindir/$name"
  done
  ok "lanzadores en $bindir"
  case ":$PATH:" in
    *":$bindir:"*) ;;
    *) warn "$bindir no está en PATH — agregalo: export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
  esac
}

install_agent() {
  [ "$AGENT" -eq 1 ] || return 0
  local src="$REPO_DIR/.opencode/agents/nexuris.md"
  [ -f "$src" ] || { warn "no encontré el agente en $src"; return 0; }
  local dir="${XDG_CONFIG_HOME:-$HOME/.config}/opencode/agents"
  local dst="$dir/nexuris.md"
  mkdir -p "$dir"
  if [ -f "$dst" ] && [ "$FORCE_AGENT" -ne 1 ]; then
    warn "ya existe $dst (no lo toco; usá --force-agent para reemplazarlo)"
    return 0
  fi
  if [ -f "$dst" ]; then
    cp -- "$dst" "$dst.bak-nexuris-$(date +%Y%m%d-%H%M%S)"
  fi
  cp -- "$src" "$dst"
  ok "agente instalado en $dir"
}

register_mcp() {
  [ "$MCP" -eq 1 ] || return 0
  local cfg="${XDG_CONFIG_HOME:-$HOME/.config}/opencode/opencode.jsonc"
  if [ ! -f "$cfg" ]; then
    warn "no encontré $cfg — salteo registro MCP"
    return 0
  fi
  if "$VENV_DIR/bin/python" "$REPO_DIR/scripts/register_mcp.py" --python "$VENV_DIR/bin/python" --config "$cfg"; then
    ok "MCP registrado en opencode"
  else
    warn "no pude registrar el MCP automáticamente (tu config quedó intacta)"
  fi
}

uninstall_all() {
  step "Desinstalando"
  DATA_DIR_RESOLVED="$(resolve_data_dir)"
  [ -d "$VENV_DIR" ] && rm -rf -- "$VENV_DIR" && ok "venv eliminado" || true
  local bindir="$HOME/.local/bin" name
  for name in nexuris nexuris-mcp; do
    if [ -L "$bindir/$name" ]; then rm -f "$bindir/$name"; ok "lanzador $name removido"; fi
  done
  local agent="${XDG_CONFIG_HOME:-$HOME/.config}/opencode/agents/nexuris.md"
  if [ -f "$agent" ]; then rm -f -- "$agent"; ok "agente de opencode removido"; fi

  local cfg="${XDG_CONFIG_HOME:-$HOME/.config}/opencode/opencode.jsonc"
  if [ -f "$cfg" ] && grep -q '"nexuris"' "$cfg" 2>/dev/null; then
    if python3 "$REPO_DIR/scripts/register_mcp.py" --remove --config "$cfg" 2>/dev/null; then
      ok "MCP removido de opencode"
    else
      warn "no pude remover el MCP de $cfg (borralo a mano)"
    fi
  fi
  if [ "$PURGE" -eq 1 ]; then
    if confirm "¿Borrar TODA la memoria en $DATA_DIR_RESOLVED?"; then rm -rf -- "$DATA_DIR_RESOLVED"; ok "datos eliminados"; fi
  else
    say "  (los datos de memoria quedaron; usá --purge para borrarlos)"
  fi
  ok "listo"
}

# ---------- main -------------------------------------------------------------
PURGE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --venv) VENV_DIR="$2"; shift 2 ;;
    --venv=*) VENV_DIR="${1#*=}"; shift ;;
    --no-link) LINK=0; shift ;;
    --no-mcp) MCP=0; shift ;;
    --no-agent) AGENT=0; shift ;;
    --force-agent) FORCE_AGENT=1; shift ;;
    --recreate) RECREATE=1; shift ;;
    --install-deps) DEPS=1; shift ;;
    -y|--yes) ASSUME_YES=1; shift ;;
    --check) MODE="check"; shift ;;
    --uninstall) MODE="uninstall"; shift ;;
    --purge) PURGE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "opción desconocida: $1 (usá --help)" ;;
  esac
done

[ -n "${NEXURIS_VENV:-}" ] && [ "$VENV_DIR" = "$REPO_DIR/.venv" ] && VENV_DIR="$NEXURIS_VENV"

cd "$REPO_DIR" || die "no puedo entrar a $REPO_DIR"

case "$MODE" in
  check)
    check_report; exit $?
    ;;
  uninstall)
    uninstall_all; exit 0
    ;;
esac

step "Instalando Nexuris"
say "  repo: $REPO_DIR"
if [ "$(id -u)" -eq 0 ] && [ -n "${SUDO_USER:-}" ]; then
  warn "estás corriendo como root (sudo). Mejor ejecutalo como $SUDO_USER:"
  warn "  su - $SUDO_USER -c 'cd $REPO_DIR && ./install.sh'"
  confirm "¿Sigo igual como root?" || exit 1
fi

PY="$(check_python)" || true
if [ -z "$PY" ]; then
  ensure_system_deps "No encontré Python >= $MIN_PY."
  PY="$(check_python)" || die "sigue sin aparecer Python >= $MIN_PY"
fi
ok "python: $($PY -V 2>&1) ($PY)"

if ! venv_ok "$PY"; then
  ensure_system_deps "Python no tiene el módulo venv/ensurepip."
  PY="$(check_python)" || die "python sigue incompleto"
  venv_ok "$PY" || die "venv sigue sin funcionar. En Debian/Ubuntu: sudo apt install python3-venv"
fi
ok "venv/ensurepip OK"

setup_venv "$PY"
install_package
smoke_test || die "el smoke test falló — revisá los mensajes de arriba"
link_launchers
install_agent
register_mcp

hr
ok "Nexuris quedó instalado"
say ""
say "  CLI:      ${C_B}nexuris${C_RST}   (o $VENV_DIR/bin/nexuris)"
say "  MCP:      ${C_B}nexuris-mcp${C_RST}  (registrado en opencode: $( [ "$MCP" -eq 1 ] && echo sí || echo no ))"
say "  agente:   $( [ "$AGENT" -eq 1 ] && echo "instalado en ~/.config/opencode/agents" || echo "no instalado" )"
say "  datos:    $(resolve_data_dir)"
say "  modelo:   ${NEXURIS_MODEL:-openrouter/free}  (cambialo con NEXURIS_MODEL)"
say ""
say "  Si 'nexuris' no aparece: export PATH=\"\$HOME/.local/bin:\$PATH\""
say "  Configurar API key:      export OPENROUTER_API_KEY=sk-or-..."
say "  Diagnóstico:             ./install.sh --check"
hr
