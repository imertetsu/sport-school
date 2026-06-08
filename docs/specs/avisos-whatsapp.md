# Epic: avisos-whatsapp

## Objetivo y valor
Cuando un **ADMIN** publica un Aviso del muro, opcionalmente **envía un WhatsApp** a
ENTRENADORES y/o TUTORES según el **alcance** del aviso (ORG / SUCURSAL / CATEGORIA, que ya
existe) y los grupos que el admin marque. Cierra el lazo "publico un anuncio → la gente se
entera por WhatsApp" sin obligar al envío (opt-in por aviso). **Mock-first**: hasta que se
configure Meta + plantilla aprobada, no hay envíos reales (el mock los registra).

Beneficiado: ADMIN de la escuela (difusión inmediata); receptores: entrenadores y tutores.

## Alcance MVP
- Flags opt-in `notificar_entrenadores` / `notificar_tutores` en el alta del aviso (`POST /avisos`).
- Resolución de destinatarios según el alcance del aviso (3 alcances) reutilizando las
  relaciones existentes (`entrenador_sucursal`, `entrenador_disciplina`, `deportista_tutor`,
  `Deportista.sucursal_id/categoria_id`, `Categoria.disciplina_id`).
- Endpoint de **preview** que cuenta destinatarios **sin enviar** (para confirmar antes).
- Envío **idempotente** en segundo plano (Celery) vía `send_template` (plantilla `nuevo_aviso`).
- Tabla-log `aviso_notificacion` (auditoría + idempotencia: no doble envío).
- UI: checkboxes en NuevoAviso + paso de confirmación con conteo.

## Fuera de alcance (NO hacer en este epic)
- **Opt-in / consentimiento real de WhatsApp del destinatario** (suscripción, gestión de
  bajas, ventana 24h de sesión). Ver nota de cumplimiento abajo.
- **Envíos reales en producción**: requieren credenciales Meta y la plantilla `nuevo_aviso`
  **aprobada** (queda como pendiente de prod). En este epic todo corre con
  `WHATSAPP_PROVIDER=noop/mock`.
- Notificar al **editar** un aviso (`PUT /avisos`) o al borrarlo. Solo en el alta.
- Reintentos automáticos / cola de reenvío sofisticada; portal del tutor; chatbot; voz
  (fases 2/3 del SRS §2).
- Cambiar el feed/visibilidad del aviso (ese comportamiento queda intacto).

### Nota de cumplimiento (RNF-02 / RNF-07)
- Los tutores son identidad **passwordless** (teléfono/WhatsApp) — SRS §3. Este epic envía a
  números que la org ya capturó para su gestión; **no** implementa consentimiento explícito
  ni opt-out por destinatario. Si Producto exige opt-in real, es epic aparte (ver decisiones
  pendientes).
- WhatsApp en frío exige **plantilla pre-aprobada** (RNF-07): se usa `send_template`, nunca
  `send_text` (solo válido dentro de la ventana de sesión de 24h, que aquí no aplica).

## Reglas de negocio
- **RF-COM (avisos)**: el alta de aviso ya existe (ADMIN, invariante alcance↔ids, soft-delete).
  Este epic **añade** la notificación opcional; no cambia la lógica del aviso ni del feed.
- **Multi-tenant (SRS §4.1)**: todo bajo `app.current_org` (RLS). La tabla nueva es tenant
  con RLS fail-closed. El envío se resuelve dentro del contexto de la org del aviso.
- **Adaptadores por país (SRS §4.2/§4.3)**: el envío va detrás de `WhatsAppPort`
  (`backend/app/domain/ports/whatsapp.py`); el dominio no conoce Meta. Selección por
  configuración vía `get_whatsapp_port()`.
- **Idempotencia**: reenviar el mismo aviso al mismo destinatario no produce doble envío
  (UNIQUE + `ON CONFLICT DO NOTHING`, patrón de `recordatorio_deudores`).

## Decisiones LOCKED (no reabrir)
1. **Opt-in con checkboxes al crear**: el admin marca `[ ] Entrenadores` `[ ] Tutores`
   (ninguno / uno / ambos), **desmarcados por defecto**. Solo se notifica a los grupos
   marcados. Sin flag marcado ⇒ el alta del aviso se comporta exactamente como hoy (no se
   encola nada).
2. **Resolución de destinatarios según el alcance del aviso**:
   - **ORG** → entrenadores: todos los de la org; tutores: todos los tutores con ≥1
     deportista en la org.
   - **SUCURSAL** → entrenadores: los de `entrenador_sucursal` de esa sucursal; tutores:
     tutores de deportistas de esa sucursal (`Deportista.sucursal_id = aviso.sucursal_id`).
   - **CATEGORIA** → entrenadores: `entrenador_disciplina` con
     `disciplina_id = categoria.disciplina_id` (si la categoría no tiene `disciplina_id` ⇒
     **0 entrenadores**); tutores: tutores de deportistas de esa categoría
     (`Deportista.categoria_id = aviso.categoria_id`).
   - **Dedupe por id** (un destinatario una sola vez aunque tenga varios deportistas).
   - Solo se envía a quien tenga `telefono` **no nulo**; los demás cuentan como
     **"sin teléfono"** (no se llama al puerto por ellos; se registran como `SIN_TELEFONO`).
3. **Confirmar con conteo antes de enviar**: el frontend, antes de enviar, muestra
   "se enviará a N personas (X entrenadores, Y tutores; K sin teléfono omitidos)" y pide
   confirmación. Requiere el endpoint de **preview** (cuenta sin enviar).

---

## Contratos compartidos
> Definir ANTES de paralelizar. **Edit, nunca Write** en archivos compartidos. Si una columna
> o forma cambia tras empezar → handoff y parar (no driftear el esquema en un solo lado).

### C1 — Tabla nueva `aviso_notificacion` (migración **0021** + modelo SQLAlchemy)
Tabla **tenant** (`org_id`) con **RLS fail-closed** (patrón NULLIF + ENABLE + FORCE + policy
`org_isolation`) y GRANTs DML, **idéntico a `recordatorio_deudores`** (usar la migración
**0014** como plantilla literal). Head actual de migraciones = **0020** → la nueva es
**0021** (`down_revision = "0020"`).

Columnas (EXACTAS; el modelo SQLAlchemy las refleja 1:1):
| Columna | Tipo | Notas |
|---|---|---|
| `id` | uuid PK | `server_default gen_random_uuid()` (modelo: `UUIDPkMixin`) |
| `org_id` | uuid NOT NULL | FK→`organizacion(id)` ON DELETE CASCADE; **columna de RLS** |
| `aviso_id` | uuid NOT NULL | FK→`aviso(id)` **ON DELETE CASCADE** |
| `tipo_destinatario` | text NOT NULL | CHECK IN (`'ENTRENADOR'`,`'TUTOR'`) |
| `destinatario_id` | uuid NOT NULL | id del entrenador o tutor; **sin FK polimórfico** |
| `canal` | text NOT NULL | DEFAULT `'WHATSAPP'` |
| `destino` | text NULL | teléfono (NULL si SIN_TELEFONO) |
| `estado` | text NOT NULL | CHECK IN (`'ENVIADO'`,`'FALLIDO'`,`'SIN_TELEFONO'`) |
| `provider_message_id` | text NULL | id del proveedor (auditoría) |
| `error` | text NULL | descripción del fallo cuando `estado='FALLIDO'` |
| `created_at` | timestamptz NOT NULL | DEFAULT `now()` |
| `enviado_en` | timestamptz NULL | sello del envío efectivo |

Constraints e índices:
- **`UNIQUE(aviso_id, tipo_destinatario, destinatario_id)`** → idempotencia (no doble envío).
- Índice `(org_id, aviso_id)` para listar por aviso.
- RLS: `ENABLE` + `FORCE` + policy `org_isolation`
  `USING/WITH CHECK (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)`.
- GRANT `SELECT, INSERT, UPDATE, DELETE` a `latinosport_app` + `USAGE, SELECT` en secuencias
  (replica 0014 por consistencia/idempotencia).
- El modelo NO hereda `TimestampMixin` (no hay `updated_at`); lleva `created_at` propio +
  `enviado_en`, igual que `recordatorio_deudores`.

**Propiedad**: la migración la posee `db-dev` (`migrations/`); el modelo SQLAlchemy
(`backend/app/models/aviso_notificacion.py`) lo posee `backend-dev`. Mismas columnas a ambos
lados (contrato compartido `Base.metadata`).

### C2 — API (backend produce → frontend consume)
- `AvisoCreate` **+=** `notificar_entrenadores: bool = False`, `notificar_tutores: bool = False`.
  (NO añadir a `AvisoUpdate`.) Default `False` ⇒ no rompe clientes existentes.
- **Preview** — `POST /avisos/notificacion/preview` (require_role **ADMIN**). Cuenta sin enviar.
  - Body:
    ```json
    {
      "alcance": "ORG|SUCURSAL|CATEGORIA",
      "sucursal_id": "uuid|null",
      "categoria_id": "uuid|null",
      "notificar_entrenadores": true,
      "notificar_tutores": false
    }
    ```
    Valida la misma invariante alcance↔ids que `AvisoCreate` (422 si no cumple).
  - Respuesta:
    ```json
    { "entrenadores": 0, "tutores": 0, "total": 0, "sin_telefono": 0 }
    ```
    `entrenadores`/`tutores` = destinatarios **con** teléfono de cada grupo marcado (0 si el
    flag está en false). `total = entrenadores + tutores`. `sin_telefono` = destinatarios
    resueltos (de los grupos marcados) **omitidos por no tener teléfono**. Dedupe aplicado.
- **Alta con envío** — `POST /avisos`: si `notificar_entrenadores` o `notificar_tutores` es
  `true`, crea el aviso (igual que hoy) y **encola** el envío en segundo plano (Celery task,
  idempotente). La respuesta del POST **no espera** al envío (sigue devolviendo `AvisoOut`).
  Sin ningún flag ⇒ comportamiento idéntico al actual (no encola nada).

### C3 — Mensaje (mock-first)
- Usar `WhatsAppPort.send_template` con `WhatsAppTemplateMessage` (lo correcto en frío;
  `send_text` queda prohibido aquí).
- Plantilla `nuevo_aviso`, `lang_code="es"`. `body_params` sugeridos:
  `[escuela, titulo, cuerpo_corto]` (cuerpo recortado a un límite razonable, p. ej. ~200
  chars; el límite exacto lo fija backend-dev). `header_image=None`.
- Con `WHATSAPP_PROVIDER=noop/mock` (`get_whatsapp_port()` → `MockWhatsAppAdapter`) **no hay
  envío real**; el mock registra y devuelve `WhatsAppSendResult(ok=True, ...)`. La fila
  `aviso_notificacion` queda `ENVIADO` con el `provider_message_id` del mock.
- **Pendiente prod**: aprobar la plantilla `nuevo_aviso` en Meta + credenciales
  (`whatsapp_provider=meta`, `whatsapp_phone_number_id`, `whatsapp_access_token`).

---

## Fases

### F1 (db) — migración 0021 `aviso_notificacion`
**Propiedad**: `db-dev` (`migrations/`).
Crear `migrations/versions/0021_aviso_notificacion.py` (a mano, como 0014: `--autogenerate`
no detecta RLS/GRANTs). `down_revision = "0020"`. Columnas/constraints/RLS/GRANTs de **C1**.
**Criterios de aceptación**
- `alembic upgrade head` y `alembic downgrade -1` corren **limpios** (sin error, reversible).
- Tabla con RLS `ENABLE` + `FORCE` + policy `org_isolation` (NULLIF fail-closed).
- Query a `aviso_notificacion` **sin** `app.current_org` fijado ⇒ **0 filas** (fail-closed);
  con contexto de la org propia ⇒ ve solo las suyas; nunca filas de otro `org_id`.
- `UNIQUE(aviso_id, tipo_destinatario, destinatario_id)` presente; CHECKs de
  `tipo_destinatario` y `estado` presentes; FK `aviso_id` con ON DELETE CASCADE.
- GRANTs DML a `latinosport_app` aplicados.

### F2 (backend) — schema, resolver, servicio, preview, task, cableado
**Propiedad**: `backend-dev` (`backend/`).
1. Modelo `backend/app/models/aviso_notificacion.py` (1:1 con C1; patrón de
   `recordatorio_deudores.py`).
2. Schema: añadir flags a `AvisoCreate` (C2); schema del preview (request/response) en
   `backend/app/schemas/aviso.py` o un schema propio.
3. **Resolver de destinatarios** (función con I/O bajo RLS, sin `WHERE org_id`): dados
   `alcance`, `sucursal_id`, `categoria_id` y los flags, devuelve, por grupo marcado, la
   lista de `(destinatario_id, tipo, telefono|None)` con **dedupe por id**. Implementa los 3
   alcances de la decisión LOCKED 2 (incluido "categoría sin `disciplina_id` ⇒ 0
   entrenadores"). Separar el **conteo** (preview) del **envío** reutilizando el mismo
   resolver.
4. Servicio `enviar_aviso_whatsapp(db, *, org_id, aviso, port, ...)` (patrón
   `enviar_digest_*`): por cada destinatario resuelto, INSERT idempotente
   `ON CONFLICT (aviso_id, tipo_destinatario, destinatario_id) DO NOTHING`; estado
   `SIN_TELEFONO` si sin teléfono (no llama al puerto, `destino=NULL`); si tiene teléfono y
   se insertó (era nuevo) → `send_template` plantilla `nuevo_aviso` y marca `ENVIADO`
   (con `provider_message_id`/`enviado_en`) o `FALLIDO` (con `error`) según el resultado.
   **No commitea** (sigue la tx del caller).
5. Endpoint preview `POST /avisos/notificacion/preview` (require_role ADMIN) en
   `backend/app/api/v1/avisos.py`: valida invariante, llama al resolver en modo conteo,
   devuelve `{entrenadores, tutores, total, sin_telefono}`. **No** inserta ni envía.
6. Task Celery `enviar_aviso_whatsapp_task(aviso_id, org_id)` en
   `backend/app/workers/tasks.py`: fija `app.current_org` (patrón `_set_org`), carga el
   aviso, llama al servicio, **commitea**. Sin entrada en `beat_schedule` (no es cron; se
   encola a demanda).
7. Cableado en `POST /avisos`: tras crear el aviso, si algún flag está en `true`, **encola**
   la task (`.delay(...)`) con el `aviso_id` y `org_id`. La respuesta no espera.
**Criterios de aceptación** (tests `@db` con `MockWhatsAppAdapter`)
- **Idempotencia**: ejecutar el envío del mismo aviso dos veces ⇒ una sola fila por
  destinatario y **un solo** envío (el segundo no llama al puerto).
- Destinatario sin `telefono` ⇒ fila `SIN_TELEFONO`, `destino=NULL`, **sin** llamada al puerto.
- Resolver correcto en los 3 alcances + dedupe + categoría sin `disciplina_id` ⇒ 0
  entrenadores.
- **Preview cuenta sin enviar**: tras llamar al preview, `aviso_notificacion` sigue vacía y
  el puerto no fue invocado; los números coinciden con lo que luego envía el servicio.
- `POST /avisos` sin flags ⇒ no encola (comportamiento actual intacto); con flag ⇒ encola y
  responde `AvisoOut` sin bloquear.
- import-linter en verde (el servicio usa `WhatsAppPort`, no el adaptador concreto).

### F3 (frontend) — checkboxes + preview + confirmación
**Propiedad**: `frontend-dev` (`frontend/`).
En `frontend/src/features/avisos/NuevoAviso.tsx` (y tipos en `frontend/src/api/types.ts` +
cliente en `frontend/src/api/client.ts`):
- Sección "Notificar por WhatsApp": `[ ] Entrenadores` `[ ] Tutores`, **desmarcados por
  defecto**. Solo visibles/aplicables en **alta** (no en edición).
- Al confirmar el alta con algún checkbox marcado: primero llamar al **preview**
  (`POST /avisos/notificacion/preview` con alcance/ids/flags actuales), mostrar
  "Se enviará a N personas (X entrenadores, Y tutores; K sin teléfono omitidos)" y pedir
  **confirmación** explícita; recién entonces hacer el `POST /avisos` con los flags incluidos
  en el payload.
- Sin checkbox marcado: el alta funciona como hoy (sin paso de preview/confirmación).
- Reflejar 422/403 del backend como ya hace el formulario.
**Criterios de aceptación**
- Checkboxes desmarcados por defecto; el payload de `POST /avisos` incluye
  `notificar_entrenadores`/`notificar_tutores`.
- Con algún flag marcado, antes de enviar se muestra el conteo del preview y se exige
  confirmación; cancelar no publica.
- El alta **sin notificación** no se rompe (no llama al preview).
- `npm run lint`, `typecheck`, `test`, `build` en verde.

---

## Criterios de aceptación (epic, verificables)
- Crear aviso ORG con ambos flags ⇒ se encola; al correr la task, hay filas `aviso_notificacion`
  para entrenadores y tutores con teléfono (`ENVIADO`) y `SIN_TELEFONO` para los sin teléfono;
  reejecutar la task no duplica ni reenvía.
- Crear aviso CATEGORIA cuya categoría no tiene `disciplina_id`, con `notificar_entrenadores`
  ⇒ 0 filas de tipo ENTRENADOR (tutores de esa categoría sí, si aplica).
- Preview devuelve los mismos números que luego materializa el envío (con/sin teléfono).
- **Aislamiento RLS**: `aviso_notificacion` sin contexto de tenant ⇒ 0 filas; nunca cruza orgs.
- Con `WHATSAPP_PROVIDER=mock`: ningún envío real; filas registradas con `provider_message_id`
  del mock.

## Propiedad por carpeta
- `db-dev` → `migrations/` (migración 0021). No toca `backend/`/`frontend/`.
- `backend-dev` → `backend/` (modelo, schema, resolver, servicio, endpoint, task, cableado,
  tests). No toca `migrations/`/`frontend/`.
- `frontend-dev` → `frontend/` (checkboxes, preview, confirmación, tipos, cliente). No toca
  `backend/`/`migrations/`.
- Orden: **F1 → F2 → F3** (F2 necesita la tabla de F1; F3 consume la API de F2). Dentro de
  F2, modelo y schema pueden ir antes del endpoint/task. El contrato C1/C2 ya está fijado
  aquí, así que db y el modelo backend pueden arrancar en paralelo siempre que respeten C1.

## Riesgos
- **Envío masivo en ORG**: un aviso de alcance ORG en una org grande puede generar cientos de
  mensajes. Mitigación: el preview obliga a ver el conteo y confirmar antes; el envío va en
  Celery (no bloquea el request). Considerar un tope/aviso si N supera un umbral (decisión de
  producto pendiente).
- **Costo por mensaje (RNF-07)**: WhatsApp cobra por plantilla enviada; el opt-in por aviso +
  confirmación reducen envíos accidentales. Mock-first evita costo en dev.
- **Plantilla pendiente**: `nuevo_aviso` debe aprobarse en Meta antes de producción; hasta
  entonces solo mock (sin envíos reales). Documentar en HANDOFF al cerrar.
- **Cumplimiento / opt-out**: sin consentimiento explícito ni baja por destinatario en este
  MVP (ver nota de cumplimiento y decisión pendiente).
- **Drift de esquema**: tabla compartida db↔backend; si cambia una columna tras arrancar,
  handoff y parar.

## Gates (Definition of Done por fase)
- Backend: `ruff check .`, `ruff format --check .`, `mypy .` (sin errores nuevos vs baseline),
  `lint-imports` (núcleo no importa adaptadores concretos), `pytest -q` (incluye tests `@db`
  de idempotencia/preview/sin-teléfono/3-alcances con mock).
- DB: `alembic upgrade head` + `alembic downgrade -1` limpios; **aislamiento RLS verificado**
  (query sin contexto ⇒ 0 filas).
- Si toca envío/idempotencia: probar que reencolar/reejecutar la task **no** produce doble
  envío ni doble fila.
- Frontend: `npm run lint`, `npm run typecheck`, `npm run test`, `npm run build` en verde;
  UX confirmada en navegador (checkboxes desmarcados, preview + confirmación).
- `git diff` revisado por **main** (no solo el reporte del agente).
- Última fase del epic: **borrar esta spec** en ese commit; actualizar `docs/HANDOFF.md`
  (incluir el pendiente de prod: plantilla `nuevo_aviso` + credenciales Meta).

## Decisiones de producto pendientes (para el usuario)
1. **Tope de envío en ORG**: ¿poner un umbral (p. ej. "más de N destinatarios requiere
   confirmación extra" o un límite duro) para acotar costo en escuelas grandes? Hoy solo se
   muestra el conteo y se confirma.
2. **Recorte del cuerpo en `body_params`**: ¿largo máximo del `cuerpo_corto` en la plantilla
   y qué hacer si excede (truncar con "…" / solo título)? (Si no se decide, backend-dev fija
   un técnico ~200 chars con elipsis.)
3. **Consentimiento / opt-out de WhatsApp** (RNF-02/§3): ¿el MVP necesita gestión de baja por
   destinatario o basta el opt-in por aviso del admin? Si se necesita, es un epic aparte.
4. **Notificar al editar** un aviso ya publicado: por ahora **NO** (solo en el alta).
   ¿Confirmas que no hace falta reenvío al editar en este epic?
