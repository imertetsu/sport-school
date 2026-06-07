# Roadmap de coordinación: Personas y Disciplinas

> **ESTO NO ES UNA SPEC EFÍMERA DE UN EPIC.** Es un documento de **coordinación
> multi-sesión** que abarca **4 sesiones / 4 ramas** secuenciadas. Cada sesión, al
> abrirse, tendrá **su propia spec efímera** `docs/specs/<sesion>.md` (que se borra al
> cerrar esa sesión). Este roadmap se mantiene mientras el conjunto esté en vuelo y se
> borra cuando la **última sesión (S4)** aterrice en `main`.
>
> **No son sesiones paralelas.** Hay dependencias reales (nombres, catálogo, patrón
> compartido) **y** solapamiento de archivos (mismos formularios, mismos services,
> cadena Alembic única) → van **secuenciadas S1 → S2 → S3 → S4, mergeando entre medias**.

---

## Objetivo y valor

Mejorar el **registro de personas** (deportistas, tutores, entrenadores) con OCR del
documento, deduplicación por CI y un **catálogo global de disciplinas** controlado por
superadmin. Beneficia a **ADMIN y ENTRENADOR** (alta más rápida, sin duplicados, datos
consistentes) y a **superadmin** (gobierna las disciplinas del SaaS).

---

## Lo que pidió el usuario (7 puntos)

1. OCR: foto del documento de identidad → autollenar datos.
2. Al escribir el CI, **recuperar** al deportista si ya existía ("se recuperó el registro
   anterior del deportista"); **no pueden existir dos deportistas con el mismo CI**.
3. Disciplina = **select controlable desde superadmin**.
4. Tutor: mismo patrón; CI **NO obligatorio** (a veces solo nombre); si se lee el documento
   autollena; si ya existe por CI → recuperar para **actualizar su teléfono**.
5. Renombrar **"alumnos" → "deportistas"**.
6. Entrenador: agregar **CI** (misma unicidad/recuperar que tutor/deportista) + OCR + la
   **misma select de disciplina** que deportista.
7. En `categoria` añadir **disciplina** (p.ej. registrar vóleibol sin confundir).

---

## Decisiones ya tomadas (NO reabrir aquí)

- **Disciplinas = catálogo GLOBAL gestionado por superadmin.** Tabla nueva `disciplina`
  **SIN `org_id` y SIN RLS** (mismo patrón que `organizacion` y `plataforma_admin`). CRUD
  solo superadmin desde `/plataforma`. **Lectura** disponible para admins de escuela (poblar
  selects). Las escuelas eligen de la lista global.
- **OCR = gratuito y on-device** (ej. Tesseract.js en navegador): el documento **NO sale del
  dispositivo** (privacidad de menores, RNF-02), sin costo. **Spike previo** para validar
  precisión con un CI boliviano real. **SIEMPRE** con edición manual de respaldo (OCR
  pre-llena, el usuario confirma/corrige). **La foto NO se guarda** (CONFIRMADO): solo se
  extraen los campos y la imagen se descarta.
- **Rename alumno→deportista = COMPLETO pero DATA-PRESERVING.** Hay datos en prod →
  migración Alembic `ALTER TABLE alumno RENAME TO deportista` (+ `alumno_tutor`→
  `deportista_tutor`, FKs, índices, constraints, **policies/grants RLS**). **NUNCA**
  drop/recreate ni `down -v`. Renombrar también rutas `/alumnos`→`/deportistas`, carpeta
  frontend, schemas, services, etiquetas UI.
- **CI único = POR ORGANIZACIÓN.** Índice único **PARCIAL** sobre `(org_id, ci) WHERE ci IS
  NOT NULL` (permite múltiples NULL). Aplica a **deportista, tutor y entrenador**.
- **Regla operativa transversal:** de aquí en adelante **TODO** cambio de esquema es una
  migración Alembic **aplicada sobre los datos existentes** (el contenedor api ya corre
  `alembic upgrade head` al desplegar). **Sin borrar datos.**
- **Backup antes de migrar en prod (CONFIRMADO):** ahora que prod tiene **datos reales**,
  **antes** de aplicar la migración de cada sesión en prod se hace un **`pg_dump` de
  respaldo** (reversibilidad). Aplica a S1–S4.

---

## Estado real de prod (VERIFICADO)

- Instancia viva: BD **`latinosport`**, **alembic 0014**, **2 orgs** (Cachinita mete gol,
  Club Aurora), **5 usuarios**, **1 superadmin** — datos **reales** creados tras el rename.
- El rename **cantera→latinosport quedó hecho de facto**: Docker creó un volumen nuevo
  `latinosport_db_data` al cambiar `name:` del compose; el viejo `cantera_db_data` quedó
  **huérfano** con solo datos de prueba ≤0008. **No hay nada que migrar "desde cantera".**
- **Consecuencia:** todas las migraciones de S1–S4 se apilan sobre la BD viva (**0015+**) y
  **DEBEN ser data-preserving** (hay datos reales). Más backup `pg_dump` previo (arriba).

---

## Estado real del código (verificado por main — el HANDOFF está desactualizado)

| Entidad | Hoy tiene | Le falta |
|---------|-----------|----------|
| `alumno` | `ci` (nullable, **no único**), `disciplina` (texto libre), `categoria_id`, `fecha_nac`, ficha_medica | rename → `deportista`; CI único parcial; disciplina → ref catálogo |
| `tutor` | `nombres`, `telefono`, `ci` (nullable, **no único**) | CI único parcial; flujo recuperar→actualizar teléfono |
| `entrenador` | `usuario_id`, `nombres`, `especialidad`, `telefono`, `disciplinas` (texto libre JSONB) | **`ci`** (no existe); disciplina → ref catálogo |
| `categoria` | `nombre`, `nivel`, `rango_edad` | **disciplina** (no existe) |
| catálogo disciplinas | **NO existe** (todo texto libre) | crear tabla `disciplina` global + sembrar valores actuales |
| superadmin | `plataforma_admin` (sin RLS), consola `/plataforma`, `require_superadmin`. Migraciones 0013+ | (reutilizar tal cual) |

---

## Tabla resumen de sesiones

| Sesión | Rama | Cubre puntos | Depende de | Migración |
|--------|------|--------------|------------|-----------|
| **S1** | `refactor/deportistas` | #5 | — | rename (ALTER, data-preserving) |
| **S2** | `feat/disciplinas` | #3, #7 | S1 | tabla `disciplina` global + `categoria.disciplina_id` + migración de datos texto→ref |
| **S3** | `feat/identidad-ci-ocr` | #1, #2, #4 | S1, S2 | índice único parcial `(org_id, ci)` en deportista y tutor |
| **S4** | `feat/entrenador-ci` | #6 | S1, S2, S3 | `entrenador.ci` + único parcial + entrenador **multi-disciplina** referenciando el catálogo (join table o array de FKs — reemplaza `disciplinas` texto) |

**Por qué secuencial (no paralelo):** S2/S3/S4 dependen del nombre fijado en S1; S3/S4
dependen del catálogo de S2; S4 reusa el patrón CI y el componente OCR de S3; y todas tocan
los mismos formularios/services/cadena Alembic. (Árbol de decisión SSS → SERIAL por
dependencia + archivos compartidos.)

---

## Sesión 1 · `refactor/deportistas` (punto #5)

- **Objetivo:** renombrar alumno→deportista en TODO el stack, **conservando los datos**.
  Va primero para no construir sobre un nombre que cambiará.
- **Alcance:** rename de esquema, código y UI. **Fuera de alcance:** cualquier cambio de
  comportamiento (CI, OCR, disciplinas) — eso es S2–S4.
- **Toca:**
  - migrations: `ALTER TABLE alumno RENAME TO deportista`, `alumno_tutor`→
    `deportista_tutor`, FKs/índices/constraints, **renombrar/reaplicar policies y grants RLS**.
  - backend: `services/alumno.py`, schemas, routers `/alumnos`, modelos, referencias
    cruzadas (auto-registro `solicitud_registro`, asistencia, cobranza, deudores).
  - frontend: carpeta/rutas `/alumnos`→`/deportistas`, tipos, client, etiquetas UI.
  - tests: renombrar fixtures/aserciones que referencian "alumno".
- **Enfoque clave:** **contrato de nombres fijado por main** antes de empezar (como el rename
  cantera→latinosport). Cambio mecánico amplio en un solo barrido coherente.
- **Riesgos / sub-dudas:**
  - Cambio mecánico muy amplio → fácil dejar referencias huérfanas.
  - **Verificar que RLS (policies/grants) siga correcto tras renombrar la tabla** — un rename
    no traslada solo las policies si están nombradas por la tabla vieja.
  - Estado de prod **ya verificado** (ver sección "Estado real de prod"): BD `latinosport`,
    alembic 0014, datos reales → esta migración se apila en **0015+** y es **la primera con
    rename de tabla sobre datos reales**.
- **DoD relevante:** **`pg_dump` de respaldo tomado antes de migrar en prod**; data-preserving
  verificado (filas intactas pre/post); RLS verificada (query sin contexto de tenant ⇒ 0
  filas de otro `org_id`); migración roundtrip OK (up/down sin pérdida); tests verdes; build
  frontend verde.

## Sesión 2 · `feat/disciplinas` (puntos #3 + #7)

- **Objetivo:** catálogo global de disciplinas gestionado por superadmin; `categoria` con
  disciplina; convertir los texto-libre actuales a referencias del catálogo.
- **Alcance:** tabla `disciplina` (sin org_id, sin RLS) + CRUD superadmin en `/plataforma` +
  **lectura para admins de escuela** (poblar selects) + `categoria.disciplina_id` + migrar
  `deportista.disciplina` y `entrenador.disciplinas` (texto) a refs. **Fuera de alcance:**
  OCR/CI (S3/S4); UI de selects en formularios de alta de persona (la consumen S3/S4, pero el
  endpoint de lectura y el select de `categoria` viven aquí).
- **Toca:**
  - migrations: crear `disciplina` (patrón sin RLS); `categoria.disciplina_id` (FK);
    **migración de datos**: sembrar el catálogo con los valores **distintos** existentes en
    `deportista.disciplina` + `entrenador.disciplinas`, y enlazar las filas a la nueva ref.
  - backend: modelo `Disciplina`; router superadmin (CRUD, reusa `require_superadmin`);
    endpoint de **lectura** del catálogo para ADMIN; schemas; `services/categoria.py`.
  - frontend: consola `/plataforma` (CRUD disciplinas); select de disciplina en form de
    `categoria`; tipos/client.
  - tests: CRUD superadmin; lectura por admin; migración de datos (texto→ref) idempotente.
- **Enfoque clave:** `disciplina` es **global** (ortogonal a RLS, como `plataforma_admin`).
  El endpoint de lectura para ADMIN debe exponer **solo** el catálogo (no datos de tenant).
- **Riesgos / sub-dudas:**
  - **Confirmar con platform-architect** que exponer lectura del catálogo a admins **no rompe
    el aislamiento** (es tabla sin datos de tenant → debería ser seguro, pero validarlo).
  - Normalización al sembrar (mayúsculas/espacios/duplicados "Voley" vs "Vóleibol").
  - **Redundancia `deportista.disciplina` vs disciplina derivada de `categoria`:** ahora que
    `categoria` tendrá disciplina, ¿el deportista la guarda directo o se deriva de su
    categoría? **Resolver en S2** (define el contrato que S3 consumirá en el form).
- **DoD relevante:** migración de datos data-preserving y verificada (todo valor texto quedó
  mapeado, sin huérfanos); RLS de tablas tenant intacta; tests verdes.

## Sesión 3 · `feat/identidad-ci-ocr` (puntos #1 + #2 + #4)

- **Objetivo:** patrón compartido **CI único / "recuperar registro"** + **OCR on-device**
  para **deportista y tutor** en el mismo formulario de alta.
- **Alcance:** índice único parcial `(org_id, ci)` en deportista y tutor; lógica
  recuperar-por-CI; OCR reutilizable (cliente); en tutor el CI **no es obligatorio** y
  recuperar permite **actualizar teléfono**. **Fuera de alcance:** entrenador (S4).
- **Toca:**
  - migrations: índice único **parcial** `(org_id, ci) WHERE ci IS NOT NULL` en
    `deportista` y `tutor`.
  - backend: lógica "buscar por CI antes de crear" en `services/deportista.py` y tutor;
    respuesta que indique "registro recuperado"; en tutor, **update de teléfono** al recuperar.
  - frontend: **componente OCR reutilizable** (Tesseract.js, on-device); integrarlo en alta
    de deportista y de tutor; mensaje "se recuperó el registro anterior del deportista";
    select de disciplina (de S2) en el form de deportista.
  - tests: dedup por CI (no se crean dos con mismo CI en una org); múltiples NULL permitidos;
    recuperar deportista; recuperar tutor + actualizar teléfono.
- **Enfoque clave:** **spike OCR previo** con un CI boliviano real (precisión); el OCR
  **pre-llena**, el usuario confirma/corrige (edición manual de respaldo **siempre**).
- **Riesgos / sub-dudas:**
  - **Resultado del spike OCR** (precisión real en CI boliviano) — condiciona el flujo.
  - Probar **idempotencia/dedup** del alta (doble submit del mismo CI ⇒ un solo registro).
  - Consumir la decisión de S2 sobre `deportista.disciplina` directo vs derivado.
- **DoD relevante:** dedup por CI verificada; múltiples NULL OK; **idempotencia del alta**
  probada; OCR no envía la imagen a servidor (privacidad de menores RNF-02); RLS verificada.

## Sesión 4 · `feat/entrenador-ci` (punto #6)

- **Objetivo:** entrenador con CI (mismo patrón que tutor/deportista), OCR (mismo
  componente) y **multi-disciplina** referenciando el catálogo (reemplaza el texto-libre
  `disciplinas`, conservando la cardinalidad múltiple).
- **Alcance:** `entrenador.ci` + único parcial; reusar lógica recuperar-por-CI de S3; reusar
  componente OCR de S3; entrenador **multi-disciplina** validada contra el catálogo de S2
  (CONFIRMADO multi) reemplazando el JSONB texto. **Fuera de alcance:** nada nuevo — es
  composición de S2 + S3.
- **Toca:**
  - migrations: `entrenador.ci` (nullable) + único parcial `(org_id, ci) WHERE ci IS NOT
    NULL`; relación entrenador↔disciplina **muchos-a-muchos** (tabla join
    `entrenador_disciplina`) o **array de FKs** — la **elección concreta** se fija en la spec
    de S4; + **migrar** el `disciplinas` JSONB texto a refs de catálogo; deprecar/eliminar la
    columna texto según resultado de la migración.
  - backend: `services/entrenador.py` (recuperar-por-CI, reusa patrón S3); schemas; router
    `/entrenadores`. **Ojo:** el CRUD de entrenador **crea cuenta de login** en una
    transacción — preservar ese flujo al añadir CI/disciplina.
  - frontend: form de entrenador con CI + OCR + **multi-select** de disciplinas (del
    catálogo de S2); tipos/client.
  - tests: dedup CI entrenador; recuperar; migración `disciplinas`→refs de catálogo (multi).
- **Enfoque clave:** **máxima reutilización** (patrón CI de S3, componente OCR de S3,
  catálogo de S2). No reinventar.
- **Riesgos / sub-dudas:**
  - No romper la transacción que crea la cuenta de login del entrenador.
- **DoD relevante:** dedup CI verificada; migración de datos data-preserving; flujo de alta
  con cuenta de login intacto; RLS verificada; tests verdes.

---

## Sub-dudas abiertas (resolver al abrir cada sesión — NO inventar)

1. **(S3)** **Precisión del OCR** en CI boliviano (resultado del spike).
2. **(S2 → contrato para S3)** **`deportista.disciplina` directo vs derivado** de la
   `categoria` (que ahora tendrá disciplina) — resolver la posible redundancia en S2.
3. **(S2)** **Exposición de lectura del catálogo global a admins de escuela:** confirmar con
   `platform-architect` que no rompe el aislamiento (tabla sin datos de tenant → debería ser
   seguro).

> Las anteriores son técnicas/de ejecución. **No hay decisiones de producto pendientes.**

---

## Decisiones de producto pendientes (para el usuario)

— sin decisiones de producto pendientes —
