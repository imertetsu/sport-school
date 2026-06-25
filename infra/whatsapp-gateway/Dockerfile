# syntax=docker/dockerfile:1
#
# Imagen del WhatsApp Gateway de LatinoSport (sidecar Baileys, WebSocket multidevice).
# Build context = infra/whatsapp-gateway (ver docker-compose.yml: whatsapp-gateway.build).
#
# NO usa Puppeteer/Chrome: Baileys habla el protocolo multidevice por WebSocket directo,
# sin navegador headless -> imagen ligera y sin riesgo de OOM por Chromium.
#
# Imagen base: node:22-slim (Debian, misma familia que Dockerfile.api/web). Necesita `git`
# porque Baileys arrastra deps que npm resuelve vía git (si falta → `ENOENT spawn git`).
#
# El auth-state de Baileys NO vive en la imagen: se persiste en SESSIONS_ROOT (un
# subdirectorio por org: ${SESSIONS_ROOT}/${org_id}), montado en un volumen del compose
# (sobrevive a reinicios -> no re-escanear QR). Multi-sesion: un proceso, N orgs.

FROM node:22-slim

# Salida sin buffer para ver los logs (incluido el QR ASCII) en vivo.
ENV NODE_ENV=production \
    NPM_CONFIG_UPDATE_NOTIFIER=false \
    NPM_CONFIG_FUND=false

# CA / proxy TLS del equipo (gotcha del HANDOFF): en ESTA máquina de dev un proxy TLS
# corporativo intercepta registry.npmjs.org y los repos de apt, y npm/apt fallan con
# UNABLE_TO_VERIFY_LEAF_SIGNATURE / "certificate not trusted". Por defecto el build NO
# debilita TLS (CI/prod deben usar una CA/registry confiable). SOLO para el build local
# detrás del proxy se pasa `--build-arg INSECURE_TLS=true`, que desactiva la verificación
# de certificado en apt y npm. Alternativa limpia (recomendada en CI/prod): montar la CA
# corporativa y exportar NODE_EXTRA_CA_CERTS en lugar de usar este flag.
ARG INSECURE_TLS=false

# git para npm; toolchain de build por si alguna dep nativa necesita compilarse.
RUN if [ "$INSECURE_TLS" = "true" ]; then \
        echo 'Acquire::https::Verify-Peer "false";' > /etc/apt/apt.conf.d/99insecure-tls; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* /etc/apt/apt.conf.d/99insecure-tls

WORKDIR /app

# Cache de dependencias: copiamos el manifiesto primero. No hay lockfile aun
# (sidecar nuevo); `npm install` lo resuelve. Si se commitea package-lock.json,
# cambiar a `npm ci` para builds reproducibles.
COPY package.json package-lock.json* ./
RUN if [ "$INSECURE_TLS" = "true" ]; then npm config set strict-ssl false; git config --global http.sslVerify false; fi \
    && npm install --omit=dev \
    && npm config delete strict-ssl 2>/dev/null || true

# Codigo del sidecar.
COPY src ./src

# Raiz por defecto del auth-state multi-sesion (el compose la monta en un volumen).
# Cada org vive en ${SESSIONS_ROOT}/${org_id}. REEMPLAZA al antiguo SESSION_DIR.
ENV SESSIONS_ROOT=/data/sessions
RUN mkdir -p /data/sessions

# Puerto HTTP por defecto (parametrizable por GATEWAY_PORT en runtime).
EXPOSE 3000

CMD ["node", "src/server.js"]
