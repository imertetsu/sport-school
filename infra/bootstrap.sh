#!/usr/bin/env bash
#
# bootstrap.sh — provisioning / base-setup de un servidor Ubuntu NUEVO para LATINOSPORT.
#
# Deja un servidor Ubuntu recién creado con el stack corriendo, desde cero:
# instala prerequisitos + Docker, clona/actualiza el repo, genera un `.env` de
# PRODUCCIÓN con secretos aleatorios (solo si aún no existe) y despliega vía
# `infra/deploy.sh`. Despliegue por IP:puerto (sin dominio, sin HTTPS por ahora).
#
# Es IDEMPOTENTE: correrlo de nuevo NO regenera secretos (reutiliza el `.env`
# existente) ni reinstala Docker; solo actualiza el repo y redespliega.
#
# Dos formas de ejecutarlo (siempre como root o con sudo):
#
#   1) Dentro del repo ya clonado:
#        sudo bash infra/bootstrap.sh
#
#   2) Auto-bootstrap vía stdin desde tu máquina local (el repo aún NO existe en
#      el servidor; este script lo clona en $DEPLOY_PATH):
#        ssh -p PORT user@host "sudo SERVER_IP=<host> bash -s" < infra/bootstrap.sh
#
#   Como se puede correr por stdin (`bash -s`), el script NUNCA depende de su
#   propia ubicación en disco para hallar el repo: usa $DEPLOY_PATH.
#
# Variables de entorno (todas con defaults sanos):
#   REPO_URL     URL del repo a clonar      (default: GitHub de LATINOSPORT)
#   REPO_TOKEN   PAT de solo-lectura para repo privado (default: vacio)
#   DEPLOY_PATH  ruta del repo en el server (default: /opt/latinosport)
#   SERVER_IP    IP/host público            (default: autodetectar)
#   API_PORT     puerto del API             (default: 8000)
#   WEB_PORT     puerto de la SPA           (default: 5173)
#   DB_PORT      puerto de Postgres (host)  (default: 5432)
#   REDIS_PORT   puerto de Redis (host)     (default: 6379)
#
set -euo pipefail

# ---------------------------------------------------------------------------
# 1) Privilegios: este script instala paquetes y arranca Docker; necesita root.
# ---------------------------------------------------------------------------
if [ "$(id -u)" -ne 0 ]; then
  if command -v sudo >/dev/null 2>&1; then
    echo "[bootstrap] no root: reintentando con sudo…"
    # Re-ejecuta preservando las variables de entorno relevantes.
    exec sudo -E bash "$0" "$@"
  fi
  echo "[bootstrap] ERROR: requiere root (o sudo). Corre: sudo bash infra/bootstrap.sh" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Inputs con defaults.
# ---------------------------------------------------------------------------
REPO_URL="${REPO_URL:-https://github.com/imertetsu/sport-school.git}"
# Token de GitHub (PAT de solo-lectura) para clonar repos privados. Si el repo
# es publico, dejalo vacio. Acepta REPO_TOKEN o GITHUB_TOKEN.
REPO_TOKEN="${REPO_TOKEN:-${GITHUB_TOKEN:-}}"
DEPLOY_PATH="${DEPLOY_PATH:-/opt/latinosport}"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"
DB_PORT="${DB_PORT:-5432}"
REDIS_PORT="${REDIS_PORT:-6379}"

export DEBIAN_FRONTEND=noninteractive

# ---------------------------------------------------------------------------
# SERVER_IP: si no se pasó, autodetectar la IP pública (con fallbacks).
# ---------------------------------------------------------------------------
if [ -z "${SERVER_IP:-}" ]; then
  echo "[bootstrap] SERVER_IP no provista; autodetectando IP pública…"
  SERVER_IP="$(curl -fsS --max-time 5 https://ifconfig.me 2>/dev/null || true)"
  if [ -z "$SERVER_IP" ]; then
    SERVER_IP="$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || true)"
  fi
  if [ -z "$SERVER_IP" ]; then
    SERVER_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  fi
  if [ -z "$SERVER_IP" ]; then
    echo "[bootstrap] ERROR: no pude autodetectar SERVER_IP. Pásala explícita:" >&2
    echo "[bootstrap]   sudo SERVER_IP=1.2.3.4 bash infra/bootstrap.sh" >&2
    exit 1
  fi
fi
echo "[bootstrap] SERVER_IP = ${SERVER_IP}"
echo "[bootstrap] DEPLOY_PATH = ${DEPLOY_PATH}"
echo "[bootstrap] puertos: API=${API_PORT} WEB=${WEB_PORT} DB=${DB_PORT} REDIS=${REDIS_PORT}"

# ---------------------------------------------------------------------------
# 2) Prerequisitos vía apt.
# ---------------------------------------------------------------------------
echo "[bootstrap] instalando prerequisitos (ca-certificates, curl, git, openssl)…"
apt-get update -y
apt-get install -y --no-install-recommends ca-certificates curl git openssl

# ---------------------------------------------------------------------------
# 3) Docker Engine + plugin compose v2 (solo si docker no está instalado).
# ---------------------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  echo "[bootstrap] Docker no encontrado; instalando vía script oficial…"
  curl -fsSL https://get.docker.com | sh
else
  echo "[bootstrap] Docker ya presente: $(docker --version)"
fi

echo "[bootstrap] habilitando y arrancando el servicio docker…"
systemctl enable --now docker

# Exigir el plugin compose v2 (`docker compose`), NO el binario viejo `docker-compose`.
if ! docker compose version >/dev/null 2>&1; then
  echo "[bootstrap] ERROR: 'docker compose' (plugin v2) no disponible." >&2
  echo "[bootstrap]   El stack usa 'docker compose', no el binario 'docker-compose'." >&2
  exit 1
fi
echo "[bootstrap] $(docker compose version)"

# ---------------------------------------------------------------------------
# 4) Asegurar el repo en $DEPLOY_PATH (clone o fetch+reset a origin/main).
# ---------------------------------------------------------------------------
if [ -d "$DEPLOY_PATH/.git" ]; then
  echo "[bootstrap] repo ya presente en ${DEPLOY_PATH}; actualizando a origin/main…"
  git -C "$DEPLOY_PATH" fetch --all --prune
  git -C "$DEPLOY_PATH" reset --hard origin/main
else
  echo "[bootstrap] clonando ${REPO_URL} en ${DEPLOY_PATH}…"
  mkdir -p "$(dirname "$DEPLOY_PATH")"
  CLONE_URL="$REPO_URL"
  if [ -n "$REPO_TOKEN" ]; then
    case "$REPO_URL" in
      https://github.com/*)
        # Token inyectado para repos privados. Queda persistido en .git/config del
        # servidor, lo que permite que el `git fetch/reset --hard origin/main` del
        # redeploy (deploy.sh / CI) siga funcionando sin re-autenticar.
        CLONE_URL="https://x-access-token:${REPO_TOKEN}@github.com/${REPO_URL#https://github.com/}"
        ;;
      *)
        echo "[bootstrap] aviso: REPO_TOKEN provisto pero REPO_URL no es https://github.com/* ; clonando sin token." >&2
        ;;
    esac
  fi
  git clone "$CLONE_URL" "$DEPLOY_PATH"
fi

# ---------------------------------------------------------------------------
# 5) Generar $DEPLOY_PATH/.env SOLO si NO existe.
#    Idempotencia crítica: en re-runs NUNCA regeneramos secretos (la BD ya
#    inicializó su volumen con el password actual; regenerarlo rompería el login
#    de latinosport_app y el guard de prod no es el problema, sino el desajuste de
#    credenciales contra el volumen de Postgres existente).
# ---------------------------------------------------------------------------
ENV_FILE="$DEPLOY_PATH/.env"
if [ -f "$ENV_FILE" ]; then
  echo "[bootstrap] reutilizando .env existente en ${ENV_FILE} (no se regeneran secretos)."
else
  echo "[bootstrap] generando ${ENV_FILE} con secretos aleatorios…"
  # Passwords fuertes (48 hex chars) y JWT (64 hex chars >= 32 que exige el guard).
  PG_PASS="$(openssl rand -hex 24)"
  APP_DB_PASS="$(openssl rand -hex 24)"
  JWT="$(openssl rand -hex 32)"

  # El password de latinosport_app DENTRO de DATABASE_URL DEBE ser el mismo que
  # APP_DB_PASSWORD (la migración crea el rol con ese valor). De ahí $APP_DB_PASS
  # interpolado en ambos lugares. Y NO contiene 'devpass' ni 'postgres:postgres@'.
  cat > "$ENV_FILE" <<EOF
APP_NAME=LATINOSPORT
APP_ENV=production
DATABASE_URL=postgresql+psycopg://latinosport_app:${APP_DB_PASS}@db:5432/latinosport
MIGRATION_DATABASE_URL=postgresql+psycopg://postgres:${PG_PASS}@db:5432/latinosport
POSTGRES_PASSWORD=${PG_PASS}
APP_DB_PASSWORD=${APP_DB_PASS}
REDIS_URL=redis://redis:6379/0
JWT_SECRET=${JWT}
JWT_EXPIRE_MINUTES=480
CORS_ORIGINS=http://${SERVER_IP}:${WEB_PORT}
# Vacío = MISMO ORIGEN: la SPA llama a /api y nginx (web) lo proxya a api:8000.
# Solo se expone el puerto WEB; la app no depende de la IP pública horneada.
VITE_API_URL=
OPENBCB_SANDBOX=false
OPENBCB_BASE_URL=
OPENBCB_API_KEY=
WHATSAPP_PROVIDER=noop
# WhatsApp Cloud API (saliente): vacíos. Para envío real, cambiar WHATSAPP_PROVIDER=meta
# y rellenar estas vars con secretos del secret manager (NUNCA hardcodear en el repo).
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_ACCESS_TOKEN=
WHATSAPP_WABA_ID=
WHATSAPP_VERIFY_TOKEN=
WHATSAPP_APP_SECRET=
WHATSAPP_GRAPH_VERSION=v21.0
RECORDATORIO_QR_DIAS_ANTES=3
GENERAR_SESIONES_DIAS=7
RECORDATORIO_CLASE_HORAS=2
DB_PORT=${DB_PORT}
REDIS_PORT=${REDIS_PORT}
API_PORT=${API_PORT}
WEB_PORT=${WEB_PORT}
EOF

  chmod 600 "$ENV_FILE"
  echo "[bootstrap] .env generado (chmod 600). Secretos NO se imprimen por seguridad."
fi

# ---------------------------------------------------------------------------
# 5b) Firewall: si ufw está activo, permitir SOLO el puerto WEB (el único que se
#     expone al exterior; la API viaja por el proxy de nginx en ESE mismo puerto).
#     No se abren 8000/5432/6379: el navegador nunca los toca.
# ---------------------------------------------------------------------------
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  echo "[bootstrap] ufw activo: permitiendo ${WEB_PORT}/tcp (web)…"
  ufw allow "${WEB_PORT}/tcp" || true
fi

# ---------------------------------------------------------------------------
# 6) Desplegar (deploy.sh ya hace: load .env + docker compose up -d --build,
#    y la imagen api aplica las migraciones en el arranque).
# ---------------------------------------------------------------------------
echo "[bootstrap] desplegando vía infra/deploy.sh…"
cd "$DEPLOY_PATH"
bash infra/deploy.sh

# ---------------------------------------------------------------------------
# 7) Resumen final.
# ---------------------------------------------------------------------------
DEPLOYED_COMMIT="$(git -C "$DEPLOY_PATH" rev-parse --short HEAD 2>/dev/null || echo '?')"
echo ""
echo "[bootstrap] ============================================================"
echo "[bootstrap] LISTO. Commit desplegado: ${DEPLOYED_COMMIT}"
echo "[bootstrap] SPA (frontend): http://${SERVER_IP}:${WEB_PORT}"
echo "[bootstrap] API (docs):     http://${SERVER_IP}:${WEB_PORT}/docs   (mismo puerto, vía proxy)"
echo "[bootstrap] Exponer al exterior SOLO el puerto WEB (${WEB_PORT}); NUNCA 8000/5432/6379."
echo "[bootstrap] ------------------------------------------------------------"
echo "[bootstrap] NOTA: el seed NO corre en deploy. La BD arranca vacía (solo"
echo "[bootstrap]       migraciones aplicadas); NO hay usuario admin sembrado."
echo "[bootstrap]       Crea el primer usuario/org por el flujo de la app."
echo "[bootstrap] ============================================================"
