#!/usr/bin/env bash
#
# Despliegue de LatinoSport EN EL SERVIDOR (build-on-server).
# Lo invoca el job `deploy` de CI/CD por SSH tras `git reset --hard origin/main`,
# pero también puedes correrlo a mano en el servidor:  bash infra/deploy.sh
#
# Requisitos en el servidor (ya cumplidos): Docker + Docker Compose, el repo
# clonado, y un archivo `.env` de PRODUCCIÓN en la raíz del repo (NO versionado)
# con APP_ENV=production y secretos reales (ver `.env.example`, bloque PRODUCCIÓN).
set -euo pipefail

# Ir a la raíz del repo (este script vive en infra/).
cd "$(dirname "$0")/.."

# Cargar el .env al entorno para que la interpolación de docker compose (build args
# como VITE_API_URL, y puertos) lo vea. Los contenedores además lo reciben vía env_file.
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
else
  echo "[deploy] FALTA el archivo .env de producción en $(pwd)" >&2
  exit 1
fi

echo "[deploy] commit desplegado: $(git rev-parse --short HEAD)"
echo "[deploy] levantando stack (build + migraciones en el arranque del api)…"
docker compose -f infra/docker-compose.yml up -d --build

echo "[deploy] limpiando imágenes huérfanas…"
docker image prune -f

echo "[deploy] limpiando build cache (mantiene ~2GB reciente)…"
docker builder prune -f --keep-storage 2GB || docker builder prune -f

echo "[deploy] estado:"
docker compose -f infra/docker-compose.yml ps
echo "[deploy] OK"
