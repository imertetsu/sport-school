---
name: run-local
description: Aplícala para levantar LATINASPORT en local (backend FastAPI, Postgres con RLS,
  worker Celery y frontend Vite), con los comandos reales del stack. Útil para probar UX o
  un flujo end-to-end.
---
# Levantar LATINASPORT en local

> El repo arranca **vacío**: estos pasos describen el toolchain estándar y se vuelven
> ejecutables tras el **epic de scaffolding**. Mantén `docs/HANDOFF.md` como verdad de los
> comandos reales una vez existan.

## Opción A — todo con Docker (recomendado para end-to-end)
```
# 1. copia el ejemplo de entorno y rellena placeholders (NO commitees secretos)
copy infra\.env.example .env          # PowerShell: Copy-Item infra\.env.example .env
# 2. levanta db + api + worker + beat + frontend
docker compose -f infra/docker-compose.yml up -d --build
# 3. aplica migraciones (crea esquema + políticas RLS)
docker compose -f infra/docker-compose.yml exec api alembic upgrade head
# 4. estado
docker compose -f infra/docker-compose.yml ps
```
- API: http://localhost:8000 (docs OpenAPI en `/docs`).
- Frontend: http://localhost:5173.

## Opción B — procesos sueltos (dev rápido de una capa)
**Postgres** (con Docker, aunque desarrolles el resto a mano):
```
docker compose -f infra/docker-compose.yml up -d db
```
**Backend:**
```
cd backend
python -m venv .venv
.venv\Scripts\activate            # PowerShell
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
```
**Worker (cron de cuotas/recordatorios):**
```
cd backend
celery -A app.workers.celery_app worker --loglevel=info
celery -A app.workers.celery_app beat   --loglevel=info     # en otra terminal
```
**Frontend:**
```
cd frontend
npm install
npm run dev
```

## Notas críticas de este dominio
- **Rol de BD:** la app debe conectarse con el rol de aplicación **no superusuario** (si no,
  RLS queda anulada y se ven datos de otros tenants). La `DATABASE_URL` del `.env` usa ESE
  rol, no el superuser de Postgres.
- **Webhook de OpenBCB:** para probar conciliación de pagos en local, el endpoint debe ser
  alcanzable desde internet → usa un túnel (p.ej. `ngrok http 8000`) y configura la URL en
  el panel/proveedor. Reenvía el mismo `transaccion_id` para validar idempotencia.
- **Notificaciones WhatsApp:** en local usa el adaptador *sandbox/noop* (no gastes mensajes
  reales, RNF-07).
- **Seed:** crea una organización + admin de prueba (target `make seed` cuando exista) para
  poder loguearte; recuerda que el **tutor no tiene login** en MVP.
