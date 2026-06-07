/**
 * DocumentScanner — escáner OCR on-device de cédula de identidad boliviana (CI).
 *
 * STANDALONE: este componente solo EXTRAE campos best-effort de una imagen de CI;
 * NO se conecta a ningún formulario de entidad (la integración a alta de
 * deportista/tutor llega en S3/S4). La corrección manual de los datos la hará el
 * formulario padre vía el callback `onExtract`.
 *
 * Privacidad (menores): la imagen se procesa 100% en el navegador con
 * Tesseract.js. NUNCA se sube a un servidor ni se persiste; el `objectURL` de la
 * vista previa se revoca al desmontar/cambiar de imagen y el resultado vive solo
 * en memoria mientras la pestaña está abierta.
 *
 * Modelo de idioma: `spa.traineddata` se descarga en runtime desde el CDN por
 * defecto de Tesseract.js (jsDelivr). Self-host del modelo es una decisión
 * posterior (ver README.md de esta carpeta). Es la ÚNICA red que ocurre y no es
 * una llamada a nuestro backend.
 *
 * Dependencia: tesseract.js está aislado tras un *dynamic import* para que el
 * typecheck del resto del frontend pase aunque el paquete no esté instalado
 * localmente (el proxy TLS del equipo bloquea `npm install`). Ver
 * `src/types/tesseract.d.ts`.
 */
import { useCallback, useEffect, useRef, useState, type ChangeEvent } from 'react';
import { parseCedula, type CedulaFields } from './parseCedula';
import './DocumentScanner.css';

export type { CedulaFields } from './parseCedula';

export interface DocumentScannerProps {
  /** Se invoca cuando termina el OCR, con los campos parseados (parciales). */
  onExtract?: (fields: CedulaFields) => void;
  /**
   * Si es `true`, también entrega el texto OCR crudo además de los campos.
   * Útil para la página de spike de validación.
   */
  onRawText?: (rawText: string) => void;
  /** Texto del botón principal. */
  label?: string;
}

type Estado = 'idle' | 'cargando' | 'reconociendo' | 'listo' | 'error';

export function DocumentScanner({ onExtract, onRawText, label }: DocumentScannerProps) {
  const [estado, setEstado] = useState<Estado>('idle');
  const [progreso, setProgreso] = useState(0);
  const [etapa, setEtapa] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [duracionMs, setDuracionMs] = useState<number | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  // Guardamos el objectURL activo para revocarlo sin depender del render.
  const previewUrlRef = useRef<string | null>(null);

  const revocarPreview = useCallback(() => {
    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current);
      previewUrlRef.current = null;
    }
  }, []);

  // Revoca el objectURL de la vista previa al desmontar (no dejar la imagen viva).
  useEffect(() => revocarPreview, [revocarPreview]);

  const procesar = useCallback(
    async (file: File) => {
      setError(null);
      setProgreso(0);
      setEtapa('');
      setDuracionMs(null);

      // Vista previa local (en memoria, nunca sube a red).
      revocarPreview();
      const url = URL.createObjectURL(file);
      previewUrlRef.current = url;
      setPreviewUrl(url);

      const inicio = performance.now();
      let worker: Awaited<
        ReturnType<typeof import('tesseract.js')['createWorker']>
      > | null = null;
      try {
        setEstado('cargando');
        // Dynamic import: aísla tesseract.js para que el typecheck del resto del
        // bundle no dependa de que el paquete esté instalado localmente.
        const { createWorker } = await import('tesseract.js');
        worker = await createWorker('spa', 1, {
          logger: (m) => {
            setEtapa(m.status);
            if (typeof m.progress === 'number') {
              setProgreso(Math.round(m.progress * 100));
            }
            if (m.status === 'recognizing text') {
              setEstado('reconociendo');
            }
          },
        });

        setEstado('reconociendo');
        const { data } = await worker.recognize(file);
        const rawText = data.text ?? '';

        const fields = parseCedula(rawText);
        setDuracionMs(Math.round(performance.now() - inicio));
        setEstado('listo');
        setProgreso(100);

        onRawText?.(rawText);
        onExtract?.(fields);
      } catch (err) {
        const detalle = err instanceof Error ? err.message : String(err);
        setError(
          `No se pudo procesar la imagen en el navegador. ${detalle}`.trim(),
        );
        setEstado('error');
      } finally {
        // Liberar el worker (y su WASM) para no acumular memoria entre escaneos.
        if (worker) {
          try {
            await worker.terminate();
          } catch {
            /* terminar es best-effort; no afecta el resultado ya entregado */
          }
        }
      }
    },
    [onExtract, onRawText, revocarPreview],
  );

  function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    // Permitir re-seleccionar el mismo archivo en un escaneo posterior.
    e.target.value = '';
    if (file) void procesar(file);
  }

  const ocupado = estado === 'cargando' || estado === 'reconociendo';
  const etapaLegible = etapaLabel(estado, etapa);

  return (
    <div className="doc-scanner">
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        capture="environment"
        className="doc-scanner__file"
        onChange={handleFileChange}
        disabled={ocupado}
      />

      <button
        type="button"
        className="doc-scanner__btn"
        onClick={() => fileInputRef.current?.click()}
        disabled={ocupado}
      >
        {ocupado ? 'Procesando…' : (label ?? 'Escanear cédula')}
      </button>

      <p className="doc-scanner__privacy" role="note">
        La imagen se procesa en tu dispositivo. No se sube ni se guarda.
      </p>

      {previewUrl && (
        <img
          src={previewUrl}
          alt="Vista previa de la cédula (solo en tu dispositivo)"
          className="doc-scanner__preview"
        />
      )}

      {ocupado && (
        <div className="doc-scanner__progress" aria-live="polite">
          <div className="doc-scanner__progress-head">
            <span>{etapaLegible}</span>
            <span className="num">{progreso}%</span>
          </div>
          <div
            className="doc-scanner__bar"
            role="progressbar"
            aria-valuenow={progreso}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <div className="doc-scanner__bar-fill" style={{ width: `${progreso}%` }} />
          </div>
        </div>
      )}

      {estado === 'listo' && duracionMs != null && (
        <p className="doc-scanner__done" aria-live="polite">
          Listo en <span className="num">{(duracionMs / 1000).toFixed(1)}s</span>. Revisa y
          corrige los datos.
        </p>
      )}

      {error && (
        <p className="doc-scanner__error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

function etapaLabel(estado: Estado, raw: string): string {
  if (estado === 'cargando') return 'Cargando modelo de OCR…';
  if (raw === 'recognizing text') return 'Reconociendo texto…';
  if (raw) return `${raw}…`;
  return 'Procesando…';
}
