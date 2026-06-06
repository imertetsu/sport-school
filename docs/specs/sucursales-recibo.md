# Epic: Sucursales/Categorías (CRUD) + Recibo por WhatsApp (Sesión C)

> Spec efímera. Se BORRA en el commit que cierra el epic (SSS, pilar 1). No crear `docs/archive/`.
> Rama `epic/sucursales-recibo`. Base `origin/main`. **SIN migración** (db-dev NO participa).

## Objetivo y valor
1. **ADMIN** gestiona sucursales y categorías (hoy solo se listan): alta/edición/baja con borrado protegido.
2. Al **confirmar un pago** (EFECTIVO y QR), el tutor responsable recibe por WhatsApp un **enlace al recibo PDF** (mock-first), reusando el `WhatsAppPort` existente.

## Alcance MVP
- CRUD sucursales/categorías solo ADMIN, dentro del tenant (RLS).
- DELETE protegido (409) si la entidad está en uso. NUNCA borrado en cascada.
- Recibo por WhatsApp para EFECTIVO + QR, enlace tokenizado público **sin expiración**.
- Frontend: pantallas Sucursales y Categorías gateadas a ADMIN.

## Fuera de alcance
- Migraciones / columna `activo` (baja = borrado protegido). SIN esquema nuevo.
- Tocar conciliación de pago (`procesar_webhook`/`crear_pago_qr`/`webhooks/openbcb.py`/FIFO/`conciliacion_pendiente`).
- Tocar `core/tenant.py`/`security.py`/`auth.py` (Sesión A) ni el área de entrenadores (Sesión B).
- UI nueva para el recibo (es server→WhatsApp). Facturación SIN (fase 2).

## Reglas de negocio (RF / SRS §)
- **Multi-tenant (SRS §4.1):** todo CRUD bajo RLS por `org_id`. Sin contexto → 0 filas.
- **Roles (SRS §3):** CRUD = `require_role("ADMIN")`. Tutor passwordless (identidad = teléfono).
- **Cobranza (SRS §7–§8):** recibo solo si `pago.estado == "CONFIRMADO"`. Idempotencia por `transaccion_id` (QR).
- **Adaptadores (SRS §4.2/§4.3):** reusar `WhatsAppPort` + `get_whatsapp_port()`. No duplicar canal.
- **Privacidad (RNF-02):** enlace inadivinable (HMAC); valida bajo RLS, no salta aislamiento.

---

## Contratos compartidos (definir ANTES de paralelizar — Fase C1)

### Schemas (append en `backend/app/schemas/catalogo.py`; ya existen `SucursalOut`/`CategoriaOut`)
- `SucursalCreate { nombre: str, direccion: str | None = None }`
- `SucursalUpdate { nombre: str, direccion: str | None = None }`
- `CategoriaCreate { nombre: str, nivel: str, rango_edad: str | None = None, sucursal_id: uuid.UUID }`
- `CategoriaUpdate { nombre: str, nivel: str, rango_edad: str | None = None }`  *(sucursal_id NO editable)*
- `nivel` validado contra `PRINCIPIANTE | INTERMEDIO | AVANZADO` (igual al CHECK de BD; rechazo 422 si difiere).

### Endpoints CRUD (extender routers existentes; `require_role("ADMIN")`)
- `sucursales.py`: `POST /sucursales` (201, `SucursalOut`) · `PUT /sucursales/{id}` · `DELETE /sucursales/{id}` (204).
- `categorias.py`: `POST /categorias` · `PUT /categorias/{id}` · `DELETE /categorias/{id}` (204).
- **RLS INSERT:** fijar `org_id = uuid.UUID(user.org_id)` explícito (el `WITH CHECK` lo exige; falta/difiere → fail-closed).
- **RLS UPDATE/DELETE:** bajo `USING` → id de otra org se ve como 404.
- **DELETE protegido (409 CONFLICT) ANTES de borrar:**
  - sucursal en uso: tiene categorías **o** alumnos asociados.
  - categoría en uso: tiene alumnos **o** `horario_clase` **o** `sesion` asociados.
  - Mensaje claro: `"La sucursal tiene N categorías / M alumnos asignados"`. NO cascada.

### Recibo — enlace tokenizado público (sin auth, stateless, sin migración)
- Ruta: `GET /api/v1/recibos/{org_id}/{pago_id}/{token}.pdf`.
- `token = base64url(HMAC_SHA256(key=settings.jwt_secret, msg=f"recibo:{org_id}:{pago_id}"))`. **Sin expiración.**
- Nuevo `backend/app/services/recibo_token.py`:
  - `firmar_recibo(org_id, pago_id) -> str`
  - `token_valido(org_id, pago_id, token) -> bool`  *(compara con `hmac.compare_digest`)*
  - `url_recibo(org_id, pago_id) -> str`  *(usa `settings.public_base_url` + ruta)*
- Nuevo router `backend/app/api/v1/recibos.py` (registrar en `api/v1/__init__.py` — Edit append):
  - Valida token; si OK ejecuta `db.execute(text("SELECT set_config('app.current_org', :org, true)"), {"org": str(org_id)})` (mismo patrón que `set_tenant_context`); consulta el `Pago` bajo RLS normal.
  - Genera PDF reusando `pagos_svc.construir_comprobante_data(db, pago=pago, org=org)` + `get_comprobante_service().render_pdf(data)`; devuelve `Response(content=..., media_type="application/pdf")` (espejo de `cobranza.comprobante_pdf`).
  - **404** si: token inválido, pago inexistente bajo RLS, o `pago.estado != "CONFIRMADO"`. NO salta RLS, NO usa SECURITY DEFINER.

### Recibo — servicio de envío `backend/app/services/recibo_envio.py`
- `enviar_recibo_whatsapp(db, *, pago, port) -> ReciboEnvioResult` (NamedTuple: `enviado: bool`, `provider_message_id: str | None`, `motivo: str`).
- Resuelve tutor responsable reusando el patrón de `recordatorios.py` (cuota→inscripción→alumno→`AlumnoTutor.responsable_pago is True`→`Tutor.telefono`). Sin teléfono → `motivo="sin_telefono"`, no llama al puerto.
- Arma `WhatsAppTemplateMessage(to=telefono, template_name="recibo_pago", lang_code="es", body_params=[nombre_alumno, "Bs {monto}", nombre_escuela, numero_recibo, url_recibo])` y llama `port.send_template(msg)`. Reusa `WhatsAppPort` **SIN modificarlo**.
- `url_recibo` = `recibo_token.url_recibo(pago.org_id, pago.id)`. `numero_recibo` = `pago.numero_recibo`.

### Enganche en el camino de pago (ADITIVO e idempotente)
- En los DOS puntos donde HOY se hace `notifier.send(..., template="comprobante", ...)`:
  - `registrar_pago_efectivo` (`backend/app/services/pagos.py`, tras fijar `comprobante_url`).
  - `_confirmar_y_aplicar` (`backend/app/services/pagos.py`, dentro del `if pago.estado == "CONFIRMADO": return` ya garantiza UNA vez).
- Derivar el envío del recibo vía `get_whatsapp_port()` + `recibo_envio.enviar_recibo_whatsapp(...)`.
- **Idempotencia:** cada uno se dispara UNA vez por confirmación. El webhook QR es idempotente por `transaccion_id` → webhook duplicado NO reenvía recibo (el `return` por `estado=="CONFIRMADO"`/`ya_tx` corta antes).
- **PROHIBIDO** alterar conciliación: idempotencia por `transaccion_id`, FIFO, `conciliacion_pendiente`, `crear_pago_qr`, `webhooks/openbcb.py` quedan INTACTOS. El único cambio en el camino de pago es enganchar el envío en esos dos puntos de notificación ya existentes.

### Env nueva (`backend/app/core/config.py` — Edit append)
- `public_base_url: str = "http://localhost:8014"` (default dev; infra-dev añade `PUBLIC_BASE_URL` a `.env.example`). Construye `url_recibo`.

### Frontend (tipar contra OpenAPI; archivos compartidos = Edit append)
- `frontend/src/api/client.ts`, `types.ts`, `components/shell/nav.ts`, `Sidebar.tsx`, `App.tsx`.
- Nueva feature `frontend/src/features/sucursales/*` (y categorías).

---

## Fases

### C1 — Contratos (SERIAL primero; desbloquea C2 y C3)
Definir TODOS los contratos compartidos: schemas Create/Update en `catalogo.py` (Edit append) + firmas de `recibo_token.py`, `recibo_envio.py` y el router `recibos.py` (stubs con la firma exacta). No implementar lógica de C2/C3 aún.
**DoD C1:** schemas y firmas presentes; `ruff`/`mypy` verdes; import-linter verde (servicios en `app.services`, router en `app.api`, dominio no importa adaptadores); `git diff` revisado por main.

### C2 — Backend (PARALELO con C3)
1. CRUD sucursales/categorías (POST/PUT/DELETE, `require_role("ADMIN")`, INSERT con `org_id` explícito, DELETE protegido 409).
2. Recibo: implementar `recibo_token.py`, `recibo_envio.py`, router `recibos.py` (registrar en `__init__.py`), enganche en `pagos.py`, env en `config.py`.
**DoD C2:**
- import-linter verde; `mypy`/`ruff` verdes; `pytest` verde.
- RLS CRUD verificado: alta/edición/baja solo dentro del tenant; sin contexto = 0 filas; id de otra org = 404.
- Test DELETE protegido: borrar sucursal con alumnos → 409 y NADA se borró (verificar que la fila sigue).
- Recibo: smoke con el mock (assert que `body_params` lleva la `url_recibo`); enlace tokenizado responde 200 con token válido y **404** con token inválido / pago no confirmado.
- Idempotencia: webhook QR duplicado ⇒ recibo enviado UNA sola vez; conciliación intacta (diff no toca `procesar_webhook`/`crear_pago_qr`/`webhooks/openbcb.py`).
- `git diff` revisado por main; cobranza/conciliación sin cambios fuera de los 2 puntos de notificación.

### C3 — Frontend (PARALELO con C2)
Pantalla Sucursales (lista + alta/edición/baja) y gestión de Categorías (con `nivel` y `rango_edad`), gateadas a ADMIN. Tipar contra OpenAPI. El recibo-WhatsApp NO requiere UI nueva.
**DoD C3:**
- `npm run typecheck` / `lint` / `build` verdes.
- UX confirmada en navegador: ADMIN ve y opera; no-ADMIN no ve la sección.
- Archivos compartidos editados con Edit append (no Write); `git diff` revisado por main.

---

## Criterios de aceptación (verificables; casos borde de dominio)
- ADMIN crea/edita/borra sucursal y categoría; otros roles → 403.
- INSERT sin `org_id` correcto → fail-closed (RLS `WITH CHECK` rechaza).
- DELETE sucursal con categorías o alumnos → 409 con conteo; entidad NO borrada.
- DELETE categoría con alumnos/`horario_clase`/`sesion` → 409; entidad NO borrada.
- Confirmar pago EFECTIVO → recibo WhatsApp enviado una vez con enlace válido.
- Confirmar pago QR (webhook) → recibo enviado una vez; webhook duplicado → sin reenvío.
- `GET /api/v1/recibos/{org}/{pago}/{token}.pdf` con token válido y pago CONFIRMADO → 200 `application/pdf`; token inválido o pago no confirmado → 404.
- Conciliación de pago (`transaccion_id`/FIFO/`conciliacion_pendiente`) sin cambios de comportamiento.

## Cierre del epic (última fase)
- Borrar `docs/specs/sucursales-recibo.md` en el commit de cierre (lo hace main).
- `docs/HANDOFF.md` lo actualiza main al integrar (no en esta sesión).

## Decisiones de producto pendientes
Ninguna. Decisiones cerradas por el usuario: recibo por WhatsApp para EFECTIVO + QR; enlace **sin expiración**; env `PUBLIC_BASE_URL`. (Si en build surge que el CHECK de `nivel` en BD difiere de `PRINCIPIANTE|INTERMEDIO|AVANZADO`, escalar a main — no inventar valores.)
