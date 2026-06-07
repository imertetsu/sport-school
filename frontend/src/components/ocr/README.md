# OCR on-device — Escáner de cédula (CI boliviana)

Componente **STANDALONE** y reutilizable para escanear una cédula de identidad
boliviana en el navegador y extraer, best-effort, sus campos. **No se conecta
todavía a ningún formulario de entidad** (la integración a alta de deportista /
tutor llega en S3/S4). Por ahora solo extrae; la corrección manual la hará el
formulario padre.

## Archivos

- `DocumentScanner.tsx` — componente de UI (cámara/subida + progreso + errores).
- `DocumentScanner.css` — estilos mobile-first con tokens del design system.
- `parseCedula.ts` — parser puro (sin DOM ni tesseract) del texto OCR → `CedulaFields`.
- `../../types/tesseract.d.ts` — declaración de tipos ambiente mínima (ver abajo).

## Cómo probar el spike con un CI real

1. Arranca el frontend: `cd frontend && npm run dev`.
2. Abre `http://localhost:5173/dev/ocr` (ruta de **dev**; no aparece en el menú).
3. Pulsa **Subir o capturar cédula** y elige/captura una foto del **anverso** del
   carnet. En móvil abre la cámara trasera (`capture="environment"`).
4. Verás, en vivo: avance/etapa del OCR, **texto OCR crudo**, **campos parseados**
   (número de CI, nombres, apellido paterno/materno, fecha de nacimiento) y el
   **tiempo** total. Compara contra el documento para evaluar precisión.

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
- El parser es heurístico (etiquetas "Apellidos/Nombres", patrones de fecha y de
  número de CI). Puede confundir apellido paterno/materno o dejar campos vacíos;
  por eso `CedulaFields` tiene **todos los campos opcionales** y el flujo asume
  corrección manual posterior.
- Solo se valida el **anverso**; no se leen el reverso ni el MRZ.

## API del componente

```ts
import { DocumentScanner, type CedulaFields } from '@/components/ocr/DocumentScanner';

<DocumentScanner
  label="Escanear cédula"
  onExtract={(fields: CedulaFields) => { /* pre-rellenar formulario */ }}
  onRawText={(raw: string) => { /* opcional: depurar/validar */ }}
/>
```

`CedulaFields` (todos opcionales): `numeroCi`, `nombres`, `apellidoPaterno`,
`apellidoMaterno`, `fechaNacimiento` (ISO `YYYY-MM-DD`), `fechaNacimientoRaw`.
