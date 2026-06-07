# OCR on-device — Escáner de cédula (CI boliviana)

Componente reutilizable para escanear una cédula de identidad boliviana en el
navegador y extraer, best-effort, sus 5 campos. Está **cableado al alta de
deportista y entrenador** (pre-rellena el formulario vía `onExtract`); la
corrección manual siempre la hace el formulario padre.

Soporta los **dos formatos vigentes** del CI a **dos fotos** (Anverso + Reverso):

- **CI NUEVO** (con MRZ TD1 en el reverso): la **MRZ** es la fuente más fiable
  para el número de documento y la fecha de nacimiento (monoespaciada, con
  *check digits*); gana al anverso cuando valida.
- **CI ANTIGUO** (sin MRZ): el número real va en el **anverso** (abajo, junto al
  complemento/extensión; el `No. ####` de arriba es **folio de trámite**, no el
  CI) y el **nombre solo en el reverso** ("…pertenece A: NOMBRES APELLIDOS", en
  orden nombres → apellidos).

## Archivos

- `DocumentScanner.tsx` — UI de **dos capturas** (Anverso/Reverso) + progreso por
  lado + preprocesado en canvas (grises/contraste, autorrotación OSD, pasada MRZ
  con charset whitelist en el reverso) + errores. Llama a `mergeLados`.
- `DocumentScanner.css` — estilos mobile-first con tokens del design system.
- `parseCedula.ts` — parser puro (sin DOM ni tesseract): `parseCedula`,
  `normalizarFecha`, `detectarFormato`, `parseAntiguo`, `mergeLados` (+ re-exporta
  `parseMrz`).
- `mrz.ts` — lectura de la MRZ TD1 con validación de *check digits* (ICAO 9303).
- `../../types/tesseract.d.ts` — declaración de tipos ambiente mínima (ver abajo).

## Cómo probar el spike con un CI real

1. Arranca el frontend: `cd frontend && npm run dev`.
2. Abre `http://localhost:5173/dev/ocr` (ruta de **dev**; no aparece en el menú).
3. Captura/sube el **anverso** y el **reverso** del carnet (botón por lado). En
   móvil abre la cámara trasera (`capture="environment"`).
4. Verás, en vivo: avance/etapa del OCR **por lado**, **texto OCR crudo de ambos
   lados** y el **resultado merge** de los 5 campos (número de CI con
   complemento/extensión si aplica, nombres, apellido paterno/materno, fecha de
   nacimiento). Compara contra el documento para evaluar precisión y para decidir
   la heurística de extensión ("08-L3") con varias cédulas reales.

## Privacidad (postura)

- La imagen se procesa **100% en el dispositivo** con Tesseract.js (WASM).
- **No se sube** a ningún servidor y **no se guarda**: la vista previa usa un
  `objectURL` en memoria que se revoca al cambiar de imagen o desmontar; el texto
  y los campos viven solo en memoria mientras la pestaña está abierta.
- Esto es deliberado por tratarse de documentos de **menores**.

## Modelo de idioma (`spa.traineddata`)

- Tesseract.js descarga el modelo de español **en runtime** desde su **CDN por
  defecto** (jsDelivr) la primera vez que se reconoce texto. Es la **única** red
  que ocurre y **no** es una llamada a nuestro backend.
- **Self-host** del `.traineddata` (servirlo desde nuestros assets para no
  depender del CDN / funcionar offline) se decidirá después; no es parte de este
  spike.

## Dependencia y tipos (proxy TLS que bloquea `npm install`)

`tesseract.js` está declarado en `package.json` (`dependencies`) pero **puede no
estar instalado localmente** porque el proxy TLS del equipo bloquea
`npm install`. Para que el resto del frontend siga typechequeando:

- El uso de Tesseract está aislado tras un **dynamic import**
  (`await import('tesseract.js')`), de modo que el grafo de tipos del resto del
  bundle no depende del paquete.
- Hay una **declaración de tipos ambiente mínima** en
  `src/types/tesseract.d.ts` (`declare module 'tesseract.js'`) con solo la
  superficie que usa el componente. Es un *fallback* para el dev local: en
  **CI/Docker** el paquete sí se instala y trae sus tipos reales, que prevalecen.

### Qué NO se puede verificar localmente sin el paquete instalado

- `npm run build` (vite) — falla al resolver el import real de `tesseract.js`.
  **CI/Docker lo instala** y ahí debe pasar.
- `npm run lint` y `npm run typecheck` **sí** pasan localmente gracias al shim de
  tipos y al dynamic import.

## Limitaciones esperadas

- El OCR de una foto de carnet es **ruidoso**: iluminación, ángulo, reflejos y
  resolución degradan mucho el resultado. Trátalo como **pre-rellenado**, nunca
  como verdad.
- El parser es heurístico (MRZ con check digits, etiquetas "Apellidos/Nombres",
  patrones de fecha y de número de CI). Puede confundir apellido paterno/materno
  o dejar campos vacíos; por eso `CedulaFields` tiene **todos los campos
  opcionales** y el flujo asume corrección manual posterior.
- **MRZ sobre foto:** Tesseract confunde `0/O`, `1/I`, `B/8`, `S/5`. Por eso se
  validan los *check digits* y, si no cuadran, NO se propaga el número/fecha de la
  MRZ (se cae al anverso/etiquetas).
- **"08-L3" del CI antiguo:** podría ser código de **lote** y no la extensión
  departamental; se anexa a `numeroCi` como complemento, pero se confirma mirando
  varias cédulas reales en `/dev/ocr` (decisión a fijar con datos).

## API del componente

```ts
import {
  DocumentScanner,
  type CedulaFields,
  type RawLados,
} from '@/components/ocr/DocumentScanner';

<DocumentScanner
  label="Escanea anverso y reverso de la cédula."
  onExtract={(fields: CedulaFields) => { /* pre-rellenar formulario (merge) */ }}
  onRawText={(raw: RawLados) => { /* opcional: { anverso, reverso } crudo */ }}
/>
```

`CedulaFields` (todos opcionales): `numeroCi` (formato canónico
`"<numero>[ <complemento>][ <EXT>]"`, ej. `"3727170 CB"`), `nombres`,
`apellidoPaterno`, `apellidoMaterno`, `fechaNacimiento` (ISO `YYYY-MM-DD`),
`fechaNacimientoRaw`.
