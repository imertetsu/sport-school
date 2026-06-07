#!/usr/bin/env bash
#
# Limpieza profunda MANUAL de artefactos Docker para LatinoSport.
# Pensado para correr a mano (local o en el servidor), NUNCA en CI.
# Para el pruning ligero automático del despliegue, ver `infra/deploy.sh`.
#
# PRINCIPIO DE SEGURIDAD:
#   - Los volúmenes NUNCA se purgan automáticamente ni en masa. En prod ahí vive
#     la BD (latinosport_db_data). El borrado de un volumen es SIEMPRE explícito,
#     por nombre y con confirmación interactiva.
#
# Uso:
#   bash infra/cleanup.sh                  Modo seguro (local y prod):
#                                            - image prune -f      (dangling)
#                                            - builder prune       (mantiene ~2GB)
#                                            - container prune -f  (parados)
#                                            - imprime `docker system df`
#
#   bash infra/cleanup.sh --images-all     Además: image prune -a -f
#                                            (imágenes tagueadas SIN contenedor,
#                                             p.ej. cantera-api).
#                                            ADVERTENCIA: seguro en un host dedicado
#                                            (prod). En una máquina compartida/local
#                                            BORRA imágenes de OTROS proyectos que no
#                                            tengan un contenedor corriendo.
#
#   bash infra/cleanup.sh --list-volumes   SOLO lista los volúmenes huérfanos
#                                            (dangling), sin borrar nada. Úsalo para
#                                            ver candidatos (p.ej. cantera_db_data).
#
#   bash infra/cleanup.sh --rm-volume NOMBRE
#                                          Borra UN volumen específico por nombre,
#                                            pidiendo confirmación (teclear `si`).
#                                            Nunca borra volúmenes en masa.
#
#   bash infra/cleanup.sh -h | --help      Muestra esta ayuda.
#
# Las flags del modo seguro son combinables, p.ej.:
#   bash infra/cleanup.sh --images-all --list-volumes
set -euo pipefail

KEEP_STORAGE="2GB"

usage() {
  sed -n '2,/^set -euo pipefail$/p' "$0" | sed 's/^#\{0,1\} \{0,1\}//; s/^set -euo pipefail$//'
}

log() {
  echo "[cleanup] $*"
}

# --- Acciones individuales --------------------------------------------------

safe_clean() {
  log "imágenes dangling…"
  docker image prune -f

  log "build cache (mantiene ~${KEEP_STORAGE} reciente)…"
  docker builder prune -f --keep-storage "${KEEP_STORAGE}" || docker builder prune -f

  log "contenedores parados…"
  docker container prune -f
}

images_all() {
  log "imágenes tagueadas SIN contenedor (image prune -a)…"
  docker image prune -a -f
}

list_volumes() {
  log "volúmenes huérfanos (dangling) — SOLO listado, no se borra nada:"
  docker volume ls -f dangling=true
}

rm_volume() {
  local name="$1"
  if [ -z "${name}" ]; then
    log "ERROR: --rm-volume requiere un NOMBRE de volumen." >&2
    exit 2
  fi
  log "vas a BORRAR el volumen: ${name}"
  log "esto es IRREVERSIBLE y puede contener datos (p.ej. BD)."
  printf '[cleanup] teclea "si" para confirmar: '
  local answer=""
  read -r answer || true
  if [ "${answer}" = "si" ]; then
    docker volume rm "${name}"
    log "volumen '${name}' borrado."
  else
    log "abortado: no se borró nada."
  fi
}

system_df() {
  log "uso de disco de Docker:"
  docker system df
}

# --- Parseo de flags --------------------------------------------------------

DO_SAFE=1          # modo seguro por defecto
DO_IMAGES_ALL=0
DO_LIST_VOLUMES=0
DO_RM_VOLUME=0
RM_VOLUME_NAME=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --images-all)
      DO_IMAGES_ALL=1
      shift
      ;;
    --list-volumes)
      DO_LIST_VOLUMES=1
      shift
      ;;
    --rm-volume)
      DO_RM_VOLUME=1
      RM_VOLUME_NAME="${2:-}"
      if [ -z "${RM_VOLUME_NAME}" ]; then
        log "ERROR: --rm-volume requiere un NOMBRE de volumen." >&2
        exit 2
      fi
      shift 2
      ;;
    *)
      log "ERROR: flag desconocida: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

# --rm-volume es una operación enfocada en UN volumen: si se pide, NO ejecutamos
# el barrido de imágenes/cache para evitar efectos colaterales en una llamada cuyo
# único foco es ese volumen. (--list-volumes solo lista, así que se combina con el
# modo seguro sin problema, p.ej. `--images-all --list-volumes`.)
if [ "${DO_RM_VOLUME}" -eq 1 ]; then
  DO_SAFE=0
fi

# --- Ejecución --------------------------------------------------------------

if [ "${DO_SAFE}" -eq 1 ]; then
  safe_clean
  if [ "${DO_IMAGES_ALL}" -eq 1 ]; then
    images_all
  fi
  system_df
fi

if [ "${DO_LIST_VOLUMES}" -eq 1 ]; then
  list_volumes
fi

if [ "${DO_RM_VOLUME}" -eq 1 ]; then
  rm_volume "${RM_VOLUME_NAME}"
fi

log "OK"
