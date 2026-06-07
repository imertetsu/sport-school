# Epic: ocr-cedula

## Objetivo y valor
Mejorar la extracción OCR de la cédula de identidad boliviana (CI) en el alta de
**deportista** y **entrenador**, para que el escaneo pre-llene de forma fiable los 5 campos
que importan en **ambos formatos vigentes** del CI (nuevo con MRZ; antiguo sin MRZ). Hoy el
parser falla en el CI antiguo (elige el folio como CI, invierte el orden del nombre) y no
sabe leer el reverso ni la MRZ. Beneficiario: Administrador/Entrenador que da de alta —
menos tipeo y menos errores de captura; la corrección manual sigue disponible siempre.

## Alcance MVP
- Parser TS puro que soporta **CI nuevo (con MRZ)** y **CI antiguo (sin MRZ)**, leyendo
  **anverso + reverso**.
- `DocumentScanner` con **dos capturas** (Anverso / Reverso), OCR por lado, preprocesado en
  canvas y merge de resultados.
- Cableado del flujo de 2 fotos en alta de deportista y entrenador.
- `/dev/ocr` mostrando ambos lados + el resultado merge para validación manual con fotos
  reales (cierra el pendiente "validar con CI real" del HANDOFF).

## Fuera de alcance (NO hacer)
- **Nada de cloud OCR.** El motor es 100% on-device (Tesseract.js); la imagen nunca sale
  del navegador (RNF-02, posible CI de menor).
- **Campos descartados:** sexo, lugar de nacimiento, domicilio, profesión, estado civil,
  fecha de emisión/vencimiento, nacionalidad. Solo se extraen los 5 campos de abajo.
- **Sin backend, sin migración, sin cambio de esquema, sin tocar la deduplicación.** El
  campo `ci` ya es texto editable y único por organización; no se crea campo nuevo para la
  extensión/complemento.
- No se persiste la imagen ni el texto OCR.

## Decisiones LOCKED (no reabrir)
1. **Motor on-device (Tesseract.js).** La imagen NUNCA sale del navegador. Nada de cloud.
2. **Solo 5 campos:** `apellidoPaterno`, `apellidoMaterno`, `nombres`, `ci`,
   `fechaNacimiento`. Todo lo demás se descarta.
3. **Extensión/ciudad de emisión (depto: LP, CB, SC, OR…) y complemento van DENTRO del
   string `ci`** (ej. `ci = "3727170 CB"`). No se crea campo nuevo ni se toca
   backend/migración/dedup.

## Contratos compartidos (definir ANTES de paralelizar)
El contrato cruza `parseCedula.ts` → `DocumentScanner.tsx` → formularios de alta y
`OcrSpike.tsx`. Es **un solo `frontend-dev`**, así que no hay paralelismo entre agentes,
pero el contrato debe quedar fijado en F1 antes de tocar la UI.

### `CedulaFields` (resultado del merge)
Se mantienen los 5 campos visibles + los auxiliares ya existentes. **El nombre del campo de
CI sigue siendo `numeroCi`** (lo consumen hoy `NuevoDeportista.handleOcr` y
`NuevoEntrenador.onScan`); NO renombrar para no romper consumidores. Lo que cambia es su
**contenido**: ahora `numeroCi` puede incluir el complemento/extensión.

```ts
export interface CedulaFields {
  numeroCi?: string;          // CI canónico (ver formato abajo); puede traer complemento/extensión
  nombres?: string;           // nombres de pila, MAYÚSCULAS
  apellidoPaterno?: string;
  apellidoMaterno?: string;
  fechaNacimiento?: string;   // ISO YYYY-MM-DD (apto para <input type="date">)
  fechaNacimientoRaw?: string;// como apareció en el documento (sin normalizar)
}
```

### Formato canónico de `numeroCi`
- Base: **solo el número real** del titular (no el folio "No." del CI antiguo).
- Si se detecta complemento y/o extensión departamental, se **anexan al string** así:
  `"<numero>[ <complemento>][ <EXT>]"`, con un **espacio** separador y **EXT en
  MAYÚSCULAS** (ej. `"3727170 CB"`, o si hay complemento `"3727170 1A CB"`).
- Si no se detecta complemento/extensión con confianza, `numeroCi` es solo el número
  (ej. `"8942507"`). Nunca inventar una extensión.
- Tope de longitud razonable para el número base: 5–10 dígitos (ya vigente en el parser).

### Funciones nuevas/expuestas del parser (F1)
- `detectarFormato(texto): 'nuevo' | 'antiguo' | 'desconocido'` — heurística por presencia
  de MRZ / etiquetas / formato de fecha.
- `parseMrz(texto): Partial<CedulaFields> | undefined` — TD1 (3 líneas × 30), valida check
  digits; devuelve `undefined` si no hay MRZ válida.
- `parseAntiguo(anverso: string, reverso: string): Partial<CedulaFields>`.
- `mergeLados(anverso: string, reverso: string): CedulaFields` — orquesta detección + merge
  (MRZ-first en el nuevo). Es la entrada que usará `DocumentScanner`.
- Se conserva `parseCedula(rawText)` y `normalizarFecha(raw)` (firmas actuales); `parseCedula`
  puede reusarse internamente como parser de un solo lado/anverso.

## Reglas de negocio (RF / SRS)
- **RNF-02 (privacidad de menores):** la imagen del CI se procesa solo en el dispositivo;
  no se sube ni se persiste. `DocumentScanner` revoca los `objectURL` y libera el worker.
- El OCR **pre-llena, no es fuente de verdad**: todos los campos quedan editables y la
  validación dura del alta (CI obligatorio en deportista; CI opcional en entrenador) no
  cambia. El parser nunca lanza; devuelve lo que pudo.
- El CI nuevo trae **MRZ TD1** en el reverso: es la fuente más fiable para el número de
  documento y la fecha de nacimiento (monoespaciado, check digits). MRZ gana al anverso
  cuando ambos están disponibles y la MRZ valida.
- El CI antiguo trae el **nombre solo en el reverso** ("...pertenece A: NOMBRES APELLIDOS",
  orden **nombres → apellidos**) y "Nacido el <fecha larga>"; el número real está en el
  anverso (abajo, junto al complemento), y el "No. ####" de arriba es **folio de trámite,
  NO el CI**.

## Fases

### F1 — Núcleo del parser (TS puro, testeable)
Solo `frontend/src/components/ocr/parseCedula.ts` y `parseCedula.test.ts`. Sin tocar UI.

Implementar:
- `detectarFormato(texto)`.
- `parseMrz(texto)` TD1: parsea las 3 líneas, valida los **check digits** (documento, fecha
  de nacimiento, y check compuesto), extrae `numeroCi`, `fechaNacimiento`, y separa
  `APELLIDOS << NOMBRES` (línea 3) en `apellidoPaterno`/`apellidoMaterno`/`nombres`.
- `parseAntiguo(anverso, reverso)`: CI = número real junto al complemento (NO el "No."
  folio); nombre desde "A:" en orden **nombres → apellidos**; fechas largas vía
  `normalizarFecha` (ya soporta "31 de Octubre de 2022").
- `mergeLados(anverso, reverso)`: detecta formato, aplica **MRZ-first** en el nuevo y cae a
  anverso/etiquetas si la MRZ no valida; en el antiguo combina anverso (CI+complemento) con
  reverso (nombre+fecha). El `numeroCi` resultante incluye complemento/extensión si se
  detecta, según el formato canónico.

**Criterios de aceptación F1 (verificables por tests):**
- Fixtures con el **texto OCR de las 4 caras** (anverso/reverso × nuevo/antiguo), tomados de
  las fotos reales que pasó el usuario, **incluyendo variantes con ruido** (caracteres mal
  reconocidos, `0/O`, `1/I`, líneas espurias).
- CI nuevo: `parseMrz` extrae `numeroCi`, `fechaNacimiento` (ISO) y los 3 campos de nombre
  desde la línea `APELLIDOS<<NOMBRES`; **rechaza** una MRZ con check digit inválido
  (devuelve `undefined` o ignora el campo, no propaga basura).
- CI antiguo: `numeroCi` es el **número real** (p. ej. el que va con la extensión), **no** el
  folio "No. 9396529"; `nombres`/`apellidoPaterno`/`apellidoMaterno` salen del reverso en el
  orden correcto (nombres→apellidos); `fechaNacimiento` se normaliza desde la fecha larga.
- `numeroCi` incluye el complemento/extensión en el formato canónico cuando se detecta
  (espacio + MAYÚSCULAS); si no, queda solo el número (no se inventa extensión).
- Se mantienen verdes los tests existentes de `normalizarFecha` y `parseCedula` (no
  regresión); el parser sigue sin lanzar ante texto vacío/ilegible.

### F2 — `DocumentScanner` a dos fotos
Solo `frontend/src/components/ocr/DocumentScanner.tsx` (+ su `.css` si hace falta).

- Dos capturas **etiquetadas Anverso / Reverso** (dos inputs/botones o un flujo de 2 pasos),
  cada una con su vista previa.
- OCR por lado y luego `mergeLados(anversoTexto, reversoTexto)`; `onExtract` recibe el
  resultado merge; `onRawText` (si se usa) entrega el texto crudo de **ambos** lados
  (etiquetados) para el spike.
- **Progreso por lado** (qué cara se está procesando + %).
- **Preprocesado en canvas** antes del OCR: escala de grises, aumento de contraste,
  **autorrotación/OSD** (las fotos del antiguo suelen venir giradas 90°), y para la MRZ del
  reverso: recorte de la banda inferior + **whitelist de charset** (`A–Z`, `0–9`, `<`) y
  modo monoespaciado para mejorar el reconocimiento.
- **Mantener la postura de privacidad:** revocar todos los `objectURL` (ambos lados) al
  cambiar imagen / desmontar; terminar el worker; nada se sube ni se persiste; conservar el
  texto y mensaje de "se procesa en tu dispositivo".

**Criterios de aceptación F2 (verificables en navegador):**
- El usuario puede capturar/seleccionar **dos** imágenes (anverso y reverso) y ve el
  progreso de cada una.
- Con un CI nuevo real, el merge prioriza la MRZ; con un CI antiguo real, el nombre se
  rellena desde el reverso y el CI desde el anverso.
- La autorrotación corrige una foto del CI antiguo tomada girada 90° (el texto se reconoce).
- No quedan `objectURL` sin revocar tras varios escaneos (sin fuga de memoria/imagen viva);
  el worker se libera tras cada lado.
- El flujo de **un solo lado** sigue siendo tolerable (si el usuario solo sube anverso, el
  componente no rompe y entrega lo que pudo del anverso).

### F3 — Cableado + spike
`frontend/src/features/deportistas/NuevoDeportista.tsx`,
`frontend/src/features/entrenadores/NuevoEntrenador.tsx`,
`frontend/src/features/dev/OcrSpike.tsx` (+ css si aplica).

- Alta de deportista y entrenador usan el `DocumentScanner` de 2 fotos. `handleOcr`/`onScan`
  siguen consumiendo `CedulaFields` (mismo contrato); como `numeroCi` ahora puede traer
  complemento/extensión, se vuelca tal cual al campo `ci` (texto editable; el placeholder ya
  es `"9123456 LP"` en deportista). Tras setear el CI, deportista sigue disparando
  `recuperarDeportistaPorCi`.
- `/dev/ocr` muestra **ambos lados** (vistas previas + texto OCR crudo por lado) y el
  **resultado merge** de los 5 campos, para validación manual con CI nuevo y antiguo reales.

**Criterios de aceptación F3:**
- Alta de deportista: escaneo de 2 fotos pre-llena ap. paterno, ap. materno, nombres, CI
  (con complemento si aplica) y fecha de nacimiento; los campos siguen editables; el submit
  y la validación dura (CI obligatorio) no cambian.
- Alta de entrenador: escaneo pre-llena nombres y CI; CI sigue opcional; el resto del modal
  intacto.
- `/dev/ocr` permite cargar anverso + reverso y muestra crudo de ambos + merge; sirve para
  cerrar el pendiente de "validar con CI real" del HANDOFF.

## Riesgos / limitaciones (honestos)
- **Precisión del OCR sobre foto de carnet** es limitada (sombras, brillos, fondo, baja
  resolución). El objetivo es "pre-llenar mejor", no perfección; **siempre** queda la
  corrección manual.
- **MRZ:** Tesseract sobre una foto (no escáner) puede confundir `0/O`, `1/I`, `B/8`,
  `S/5`. Por eso se validan check digits y, si no cuadran, se cae al anverso en vez de
  propagar un número errado.
- **"08-L3" del CI antiguo:** podría ser **código de lote** y no la extensión
  departamental. NO asumirlo como extensión con certeza; se confirma mirando el resultado en
  `/dev/ocr` con varias cédulas reales antes de fijar la heurística de extensión.
- **Autorrotación/OSD** añade coste de cómputo on-device (más lento en móviles modestos);
  aceptable porque el alta no es de alta frecuencia.
- Tesseract descarga `spa.traineddata` desde CDN en runtime (única red, no es a nuestro
  backend); para MRZ puede convenir charset whitelist en lugar de un modelo `OCRB` dedicado
  (decisión técnica del `frontend-dev` dentro de F2).

## Gates (Definition of Done por fase)
- `cd frontend && npm run lint` en verde.
- `cd frontend && npm run typecheck` (tsc --noEmit) sin errores nuevos.
- `cd frontend && npm run test` (vitest) en verde — incluye los nuevos fixtures de F1.
- `cd frontend && npm run build` en verde si tocó código de bundle.
- **Validación manual en `/dev/ocr`** con un CI nuevo y un CI antiguo reales (F3): el merge
  produce los 5 campos esperados o, donde el OCR falla, queda claro y se corrige a mano.
- UX confirmada en navegador para el flujo de 2 fotos en alta de deportista y entrenador.
- `git diff` revisado por main; al cerrar el epic, **esta spec se borra en el mismo commit**
  y se actualiza `docs/HANDOFF.md`.

## Propiedad
- Área **ÚNICA**: `frontend/` (un solo `frontend-dev`).
- **Sin** backend, **sin** migración, **sin** infra. No se toca el esquema ni la dedup de CI.

## Decisiones de producto pendientes (para el usuario)
- Ninguna bloqueante. El usuario ya cerró motor, campos y formato del `ci`.
- A confirmar **durante** F3 con datos reales (no bloquea arrancar): si el sufijo tipo
  "08-L3" del CI antiguo debe tratarse como extensión/complemento dentro de `numeroCi` o
  ignorarse. Se decide observando varias cédulas en `/dev/ocr`.
