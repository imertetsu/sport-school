/**
 * DocumentScanner — escáner OCR on-device de cédula de identidad boliviana (CI),
 * a DOS fotos (Anverso + Reverso).
 *
 * Flujo: el usuario captura/sube el ANVERSO y el REVERSO (cada uno con su vista
 * previa y su progreso). Se hace OCR por lado y luego `mergeLados(anverso,
 * reverso)` orquesta la detección de formato (nuevo con MRZ / antiguo) y el
 * merge de los 5 campos. El resultado se entrega por `onExtract`; el texto crudo
 * de ambos lados (etiquetado) por `onRawText` (para el spike).
 *
 * El componente SOLO pre-llena; la corrección manual la hace el formulario padre.
 *
 * Privacidad (menores, RNF-02): la imagen se procesa 100% en el navegador con
 * Tesseract.js (WASM). NUNCA se sube a un servidor ni se persiste; los
 * `objectURL` de las vistas previas (ambos lados) se revocan al cambiar de imagen
 * y al desmontar, y el worker de OCR se termina tras cada lado. El texto y los
 * campos viven solo en memoria mientras la pestaña está abierta.
 *
 * Preprocesado en <canvas> antes del OCR: escala de grises + contraste/umbral y
 * autorrotación (las fotos del CI antiguo suelen venir giradas 90°: se prueban
 * orientaciones y se elige la de mayor confianza/longitud de texto). Para el
 * REVERSO se hace además una pasada de MRZ con charset whitelist (A–Z 0–9 <) y
 * PSM de bloque uniforme.
 *
 * Modelo de idioma: `spa.traineddata` se descarga en runtime desde el CDN por
 * defecto de Tesseract.js (jsDelivr). Es la ÚNICA red que ocurre y NO es una
 * llamada a nuestro backend.
 *
 * Dependencia: tesseract.js está aislado tras un *dynamic import* para que el
 * typecheck del resto del frontend pase aunque el paquete no esté instalado
 * localmente. Ver `src/types/tesseract.d.ts`.
 */
import {
  useCallback,
  useEffect,
  useReducer,
  useRef,
  useState,
  type ChangeEvent,
} from 'react';
import { mergeLados, type CedulaFields } from './parseCedula';
import './DocumentScanner.css';

export type { CedulaFields } from './parseCedula';

/** Texto OCR crudo de ambos lados, etiquetado (para depurar en el spike). */
export interface RawLados {
  anverso: string;
  reverso: string;
}

export interface DocumentScannerProps {
  /** Se invoca cuando termina el OCR de algún lado, con el merge acumulado. */
  onExtract?: (fields: CedulaFields) => void;
  /**
   * Si se pasa, entrega el texto OCR crudo de ambos lados (etiquetado). Útil para
   * la página de spike de validación.
   */
  onRawText?: (raw: RawLados) => void;
  /** Texto del encabezado/botón principal. */
  label?: string;
}

type Lado = 'anverso' | 'reverso';
type EstadoLado = 'idle' | 'cargando' | 'reconociendo' | 'listo' | 'error';

interface LadoState {
  estado: EstadoLado;
  progreso: number;
  etapa: string;
  error: string | null;
  previewUrl: string | null;
  rawText: string;
  duracionMs: number | null;
}

const LADO_INICIAL: LadoState = {
  estado: 'idle',
  progreso: 0,
  etapa: '',
  error: null,
  previewUrl: null,
  rawText: '',
  duracionMs: null,
};

interface State {
  anverso: LadoState;
  reverso: LadoState;
}

type Action =
  | { type: 'reset'; lado: Lado; previewUrl: string }
  | { type: 'patch'; lado: Lado; patch: Partial<LadoState> };

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'reset':
      return {
        ...state,
        [action.lado]: { ...LADO_INICIAL, previewUrl: action.previewUrl, estado: 'cargando' },
      };
    case 'patch':
      return { ...state, [action.lado]: { ...state[action.lado], ...action.patch } };
    default:
      return state;
  }
}

const LADOS: { id: Lado; titulo: string; ayuda: string }[] = [
  { id: 'anverso', titulo: 'Anverso (frente)', ayuda: 'Lado con la foto y los datos.' },
  { id: 'reverso', titulo: 'Reverso (atrás)', ayuda: 'Lado con la firma / código de máquina.' },
];

export function DocumentScanner({ onExtract, onRawText, label }: DocumentScannerProps) {
  const [state, dispatch] = useReducer(reducer, { anverso: LADO_INICIAL, reverso: LADO_INICIAL });
  // `true` cuando ya se procesó al menos un lado y el merge no extrajo NINGÚN
  // campo (caso típico del CI antiguo, ilegible por OCR): mostramos un hint para
  // que el usuario teclee a mano. No bloquea nada.
  const [sinDatos, setSinDatos] = useState(false);

  const inputRefs = {
    anverso: useRef<HTMLInputElement>(null),
    reverso: useRef<HTMLInputElement>(null),
  };

  // objectURLs activos (uno por lado) para revocarlos sin depender del render.
  const previewUrlRefs = useRef<Record<Lado, string | null>>({ anverso: null, reverso: null });
  // Texto crudo más reciente por lado (para el merge y el callback de raw).
  const rawRefs = useRef<Record<Lado, string>>({ anverso: '', reverso: '' });

  const revocarPreview = useCallback((lado: Lado) => {
    const url = previewUrlRefs.current[lado];
    if (url) {
      URL.revokeObjectURL(url);
      previewUrlRefs.current[lado] = null;
    }
  }, []);

  // Revoca AMBOS objectURL al desmontar (no dejar imágenes vivas).
  useEffect(() => {
    return () => {
      revocarPreview('anverso');
      revocarPreview('reverso');
    };
  }, [revocarPreview]);

  const emitir = useCallback(() => {
    const anverso = rawRefs.current.anverso;
    const reverso = rawRefs.current.reverso;
    onRawText?.({ anverso, reverso });
    const campos = mergeLados(anverso, reverso);
    onExtract?.(campos);
    // ¿Se extrajo algún campo útil? (parser conservador: ante duda deja vacío).
    const algunCampo = Object.values(campos).some((v) => v != null && v !== '');
    setSinDatos(!algunCampo);
  }, [onExtract, onRawText]);

  const procesar = useCallback(
    async (lado: Lado, file: File) => {
      // Vista previa local (en memoria, nunca sube a red).
      revocarPreview(lado);
      setSinDatos(false); // se recalcula al terminar el OCR de este lado
      const url = URL.createObjectURL(file);
      previewUrlRefs.current[lado] = url;
      dispatch({ type: 'reset', lado, previewUrl: url });

      const inicio = performance.now();
      let worker: Awaited<
        ReturnType<typeof import('tesseract.js')['createWorker']>
      > | null = null;
      try {
        // Dynamic import: aísla tesseract.js del grafo de tipos del bundle.
        const tesseract = await import('tesseract.js');
        const { createWorker } = tesseract;
        worker = await createWorker('spa', 1, {
          logger: (m) => {
            dispatch({
              type: 'patch',
              lado,
              patch: {
                etapa: m.status,
                ...(typeof m.progress === 'number'
                  ? { progreso: Math.round(m.progress * 100) }
                  : {}),
                ...(m.status === 'recognizing text' ? { estado: 'reconociendo' as const } : {}),
              },
            });
          },
        });

        dispatch({ type: 'patch', lado, patch: { estado: 'reconociendo' } });

        // Preprocesa la imagen en canvas y elige la mejor orientación.
        const base = await prepararImagen(file);
        const orientada = await mejorOrientacion(worker, base);

        // Pasada principal (idioma español, página completa).
        const { data } = await worker.recognize(orientada.canvas);
        let texto = data.text ?? '';

        // En el reverso del CI nuevo, una pasada MRZ con charset whitelist sobre
        // la banda inferior suele recuperar mejor las 3 líneas monoespaciadas.
        if (lado === 'reverso') {
          const mrzTexto = await reconocerMrz(worker, orientada.canvas);
          if (mrzTexto) texto = `${texto}\n${mrzTexto}`;
        }

        rawRefs.current[lado] = texto;
        dispatch({
          type: 'patch',
          lado,
          patch: {
            rawText: texto,
            estado: 'listo',
            progreso: 100,
            duracionMs: Math.round(performance.now() - inicio),
          },
        });
        emitir();
      } catch (err) {
        const detalle = err instanceof Error ? err.message : String(err);
        dispatch({
          type: 'patch',
          lado,
          patch: {
            estado: 'error',
            error: `No se pudo procesar la imagen en el navegador. ${detalle}`.trim(),
          },
        });
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
    [emitir, revocarPreview],
  );

  function handleFileChange(lado: Lado) {
    return (e: ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      // Permitir re-seleccionar el mismo archivo en un escaneo posterior.
      e.target.value = '';
      if (file) void procesar(lado, file);
    };
  }

  const algunoOcupado =
    state.anverso.estado === 'cargando' ||
    state.anverso.estado === 'reconociendo' ||
    state.reverso.estado === 'cargando' ||
    state.reverso.estado === 'reconociendo';

  return (
    <div className="doc-scanner">
      <p className="doc-scanner__privacy" role="note">
        La imagen se procesa en tu dispositivo. No se sube ni se guarda.
      </p>

      <details className="doc-scanner__guia">
        <summary>📷 Cómo tomar la foto para mejores resultados</summary>
        <ul>
          <li>Carnet <strong>plano</strong> sobre una superficie lisa; sin funda ni reflejos.</li>
          <li><strong>Buena luz</strong>, sin sombras ni brillos sobre el carnet.</li>
          <li>Encuadra <strong>solo el carnet</strong> (que llene la foto), en <strong>horizontal</strong>.</li>
          <li>Teléfono <strong>paralelo</strong> al carnet y enfocado hasta que el texto se lea nítido.</li>
        </ul>
      </details>

      <div className="doc-scanner__lados">
        {LADOS.map(({ id, titulo, ayuda }) => {
          const s = state[id];
          const ocupado = s.estado === 'cargando' || s.estado === 'reconociendo';
          return (
            <div className="doc-scanner__lado" key={id}>
              <div className="doc-scanner__lado-head">
                <span className="doc-scanner__lado-titulo">{titulo}</span>
                <span className="doc-scanner__lado-ayuda">{ayuda}</span>
              </div>

              <input
                ref={inputRefs[id]}
                type="file"
                accept="image/*"
                capture="environment"
                className="doc-scanner__file"
                onChange={handleFileChange(id)}
                disabled={ocupado}
              />

              <button
                type="button"
                className="doc-scanner__btn"
                onClick={() => inputRefs[id].current?.click()}
                disabled={ocupado}
              >
                {ocupado
                  ? 'Procesando…'
                  : s.estado === 'listo'
                    ? `Reemplazar ${titulo.toLowerCase()}`
                    : `Escanear ${titulo.toLowerCase()}`}
              </button>

              {s.previewUrl && (
                <img
                  src={s.previewUrl}
                  alt={`Vista previa del ${titulo.toLowerCase()} (solo en tu dispositivo)`}
                  className="doc-scanner__preview"
                />
              )}

              {ocupado && (
                <div className="doc-scanner__progress" aria-live="polite">
                  <div className="doc-scanner__progress-head">
                    <span>{etapaLabel(s.estado, s.etapa)}</span>
                    <span className="num">{s.progreso}%</span>
                  </div>
                  <div
                    className="doc-scanner__bar"
                    role="progressbar"
                    aria-valuenow={s.progreso}
                    aria-valuemin={0}
                    aria-valuemax={100}
                  >
                    <div
                      className="doc-scanner__bar-fill"
                      style={{ width: `${s.progreso}%` }}
                    />
                  </div>
                </div>
              )}

              {s.estado === 'listo' && s.duracionMs != null && (
                <p className="doc-scanner__done" aria-live="polite">
                  Listo en <span className="num">{(s.duracionMs / 1000).toFixed(1)}s</span>.
                </p>
              )}

              {s.error && (
                <p className="doc-scanner__error" role="alert">
                  {s.error}
                </p>
              )}
            </div>
          );
        })}
      </div>

      <p className="doc-scanner__hint">
        {label ?? 'Escanea ambos lados de la cédula.'} Revisa y corrige los datos antes de
        guardar.
        {algunoOcupado ? ' Procesando…' : ''}
      </p>

      {sinDatos && !algunoOcupado && (
        <p className="doc-scanner__nodata" role="note">
          No se pudieron leer datos automáticamente; ingrésalos a mano.
        </p>
      )}
    </div>
  );
}

// ===========================================================================
// Preprocesado de imagen (canvas) + autorrotación + pasada MRZ
// ===========================================================================

/** Lado del que se hace OCR ya preprocesado y su orientación de rotación. */
interface Preparada {
  canvas: HTMLCanvasElement;
}

// Lado objetivo: SUBE imágenes pequeñas (un carnet limpio suele venir en baja
// resolución y el texto fino se pierde) y ACOTA las grandes (coste on-device).
// Tesseract rinde mejor con texto grande (~300dpi equivalente).
const OBJETIVO_LADO = 1800;

/**
 * Carga el archivo en un canvas, lo re-escala (upscale de pequeñas / downscale de
 * grandes) a `OBJETIVO_LADO` y lo pasa a escala de grises. NO estira contraste: el
 * estiramiento degradaba el texto fino de los carnets limpios (p.ej. la fecha del
 * anverso quedaba ilegible). El OCR de Tesseract ya maneja bien grises nítidos.
 */
async function prepararImagen(file: File): Promise<HTMLCanvasElement> {
  const bitmap = await cargarBitmap(file);
  const ladoMayor = Math.max(bitmap.width, bitmap.height);
  const escala = OBJETIVO_LADO / ladoMayor; // >1 sube, <1 baja
  const w = Math.max(1, Math.round(bitmap.width * escala));
  const h = Math.max(1, Math.round(bitmap.height * escala));

  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d');
  if (!ctx) return canvas;
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(bitmap, 0, 0, w, h);
  cerrarBitmap(bitmap);

  // Solo escala de grises (sin estiramiento de contraste).
  const img = ctx.getImageData(0, 0, w, h);
  const d = img.data;
  for (let i = 0; i < d.length; i += 4) {
    const gris = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
    d[i] = d[i + 1] = d[i + 2] = gris;
  }
  ctx.putImageData(img, 0, 0);
  return canvas;
}

/** Rota un canvas 0/90/180/270 grados y devuelve un canvas nuevo. */
function rotarCanvas(src: HTMLCanvasElement, grados: number): HTMLCanvasElement {
  if (grados === 0) return src;
  const rad = (grados * Math.PI) / 180;
  const swap = grados === 90 || grados === 270;
  const out = document.createElement('canvas');
  out.width = swap ? src.height : src.width;
  out.height = swap ? src.width : src.height;
  const ctx = out.getContext('2d');
  if (!ctx) return src;
  ctx.translate(out.width / 2, out.height / 2);
  ctx.rotate(rad);
  ctx.drawImage(src, -src.width / 2, -src.height / 2);
  return out;
}

/**
 * Autorrotación por OSD: pregunta a Tesseract la orientación detectada y rota la
 * imagen para enderezarla. Las fotos del CI antiguo suelen venir giradas 90°.
 * Si el OSD no está disponible o falla, devuelve el canvas tal cual (best-effort).
 */
async function mejorOrientacion(
  worker: Awaited<ReturnType<typeof import('tesseract.js')['createWorker']>>,
  canvas: HTMLCanvasElement,
): Promise<Preparada> {
  try {
    if (typeof worker.detect === 'function') {
      const osd = await worker.detect(canvas);
      // tesseract.js v5: data.orientation_degrees indica cuántos grados está
      // rotada la imagen; rotamos en sentido inverso para enderezar.
      const deg = Number(osd?.data?.orientation_degrees ?? 0);
      const normal = ((Math.round(deg / 90) * 90) % 360 + 360) % 360;
      if (normal !== 0) {
        return { canvas: rotarCanvas(canvas, (360 - normal) % 360) };
      }
    }
  } catch {
    /* OSD best-effort: si no está disponible, seguimos sin rotar */
  }
  return { canvas };
}

/**
 * Pasada específica para la MRZ del reverso: recorta la banda inferior (~30% de
 * la altura, donde vive la MRZ TD1) y reconoce con charset whitelist (A–Z 0–9 <)
 * y modo de bloque uniforme. Devuelve el texto crudo de la banda o '' si falla.
 */
async function reconocerMrz(
  worker: Awaited<ReturnType<typeof import('tesseract.js')['createWorker']>>,
  canvas: HTMLCanvasElement,
): Promise<string> {
  try {
    const bandaY = Math.floor(canvas.height * 0.62);
    const bandaH = canvas.height - bandaY;
    if (bandaH < 10) return '';
    const banda = document.createElement('canvas');
    banda.width = canvas.width;
    banda.height = bandaH;
    const ctx = banda.getContext('2d');
    if (!ctx) return '';
    ctx.drawImage(canvas, 0, bandaY, canvas.width, bandaH, 0, 0, canvas.width, bandaH);

    if (typeof worker.setParameters === 'function') {
      await worker.setParameters({
        tessedit_char_whitelist: 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<',
        tessedit_pageseg_mode: '6', // bloque uniforme de texto
      });
    }
    const { data } = await worker.recognize(banda);
    // Restaura parámetros por si el worker se reutilizara (aquí se termina luego).
    if (typeof worker.setParameters === 'function') {
      await worker.setParameters({ tessedit_char_whitelist: '' });
    }
    return data.text ?? '';
  } catch {
    return '';
  }
}

/** Carga un File como ImageBitmap (con fallback a HTMLImageElement). */
async function cargarBitmap(file: File): Promise<ImageBitmap | HTMLImageElement> {
  if (typeof createImageBitmap === 'function') {
    try {
      return await createImageBitmap(file);
    } catch {
      /* fallback abajo */
    }
  }
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise<HTMLImageElement>((resolve, reject) => {
      const el = new Image();
      el.onload = () => resolve(el);
      el.onerror = () => reject(new Error('No se pudo cargar la imagen.'));
      el.src = url;
    });
    return img;
  } finally {
    URL.revokeObjectURL(url);
  }
}

function cerrarBitmap(bitmap: ImageBitmap | HTMLImageElement): void {
  if ('close' in bitmap && typeof bitmap.close === 'function') bitmap.close();
}

function etapaLabel(estado: EstadoLado, raw: string): string {
  if (estado === 'cargando') return 'Cargando modelo de OCR…';
  if (raw === 'recognizing text') return 'Reconociendo texto…';
  if (raw) return `${raw}…`;
  return 'Procesando…';
}
