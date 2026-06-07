/**
 * Declaración de tipos AMBIENTE mínima para `tesseract.js`.
 *
 * Por qué existe: el proxy TLS del equipo no deja `npm install` localmente, así
 * que el paquete `tesseract.js` puede no estar presente en `node_modules` cuando
 * corremos `npm run typecheck`/`lint`. Sin esta declaración, TS fallaría con
 * "Cannot find module 'tesseract.js'" y rompería el typecheck del RESTO del
 * frontend.
 *
 * Esta es una superficie de API DELIBERADAMENTE recortada: solo lo que usa
 * `DocumentScanner.tsx`. En CI/Docker el paquete sí se instala y trae sus
 * propios tipos (`tesseract.js` incluye `.d.ts`); como esos son más completos y
 * compatibles, prevalecen — esta declaración solo es un *fallback* para el dev
 * local sin el dep instalado.
 *
 * Si CI reportara un choque de tipos (firma divergente), borra esta declaración:
 * en CI el paquete está instalado y sus tipos reales bastan.
 */
declare module 'tesseract.js' {
  /** Progreso/estado emitido por el logger de Tesseract durante el OCR. */
  export interface LoggerMessage {
    /** Etapa actual: 'loading tesseract core', 'recognizing text', etc. */
    status: string;
    /** Avance 0..1 dentro de la etapa actual. */
    progress: number;
    [key: string]: unknown;
  }

  export interface RecognizeWord {
    text: string;
    confidence: number;
  }

  export interface RecognizeResultData {
    /** Texto plano reconocido (con saltos de línea). */
    text: string;
    /** Confianza media 0..100. */
    confidence: number;
    words?: RecognizeWord[];
    [key: string]: unknown;
  }

  export interface RecognizeResult {
    data: RecognizeResultData;
  }

  export interface WorkerOptions {
    logger?: (msg: LoggerMessage) => void;
    [key: string]: unknown;
  }

  export interface Worker {
    recognize(image: ImageLike): Promise<RecognizeResult>;
    terminate(): Promise<unknown>;
    [key: string]: unknown;
  }

  /** Entradas que acepta `recognize`/`createWorker` para la imagen. */
  export type ImageLike = string | File | Blob | HTMLCanvasElement | HTMLImageElement;

  /**
   * Crea un worker de OCR. Firma de tesseract.js v5 (langs + oem + options).
   * Mantenemos los parámetros laxos para no chocar con los tipos reales en CI.
   */
  export function createWorker(
    langs?: string | string[],
    oem?: number,
    options?: WorkerOptions,
  ): Promise<Worker>;

  const Tesseract: {
    createWorker: typeof createWorker;
  };
  export default Tesseract;
}
