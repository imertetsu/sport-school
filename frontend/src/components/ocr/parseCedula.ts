/**
 * Parser best-effort del texto OCR de una cédula de identidad boliviana (CI).
 *
 * Es una FUNCIÓN PURA, sin dependencias de tesseract.js ni del DOM, para que
 * sea testeable de forma aislada y rápida. `DocumentScanner.tsx` la alimenta con
 * el texto crudo que devuelve el OCR.
 *
 * IMPORTANTE: el OCR de una foto de carnet es ruidoso. Esto NO es una fuente de
 * verdad; solo pre-rellena. La corrección manual la hace el formulario padre
 * (S3/S4). Por eso todos los campos son opcionales y nunca lanzamos.
 */

export interface CedulaFields {
  /** Número de cédula (solo dígitos, sin extensión departamental). */
  numeroCi?: string;
  /** Nombres (de pila). */
  nombres?: string;
  /** Apellido paterno. */
  apellidoPaterno?: string;
  /** Apellido materno. */
  apellidoMaterno?: string;
  /** Fecha de nacimiento normalizada a ISO `YYYY-MM-DD` (apto para <input type="date">). */
  fechaNacimiento?: string;
  /** Fecha de nacimiento tal como apareció en el documento (sin normalizar). */
  fechaNacimientoRaw?: string;
}

const MESES: Record<string, number> = {
  ene: 1, enero: 1,
  feb: 2, febrero: 2,
  mar: 3, marzo: 3,
  abr: 4, abril: 4,
  may: 5, mayo: 5,
  jun: 6, junio: 6,
  jul: 7, julio: 7,
  ago: 8, agosto: 8,
  sep: 9, set: 9, septiembre: 9, setiembre: 9,
  oct: 10, octubre: 10,
  nov: 11, noviembre: 11,
  dic: 12, diciembre: 12,
};

/** Quita acentos y normaliza espacios para comparar etiquetas con tolerancia. */
function deburr(s: string): string {
  return s
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function pad2(n: number): string {
  return String(n).padStart(2, '0');
}

/**
 * Normaliza una fecha detectada a ISO `YYYY-MM-DD`. Acepta dd/mm/yyyy,
 * dd-mm-yyyy, dd.mm.yyyy y "dd de <mes> de yyyy" / "dd MES yyyy".
 * Devuelve `undefined` si no logra una fecha plausible.
 */
export function normalizarFecha(raw: string): string | undefined {
  const txt = deburr(raw).toLowerCase();

  // dd[/.-]mm[/.-]yyyy
  const numerica = txt.match(/\b(\d{1,2})[\s./-]+(\d{1,2})[\s./-]+(\d{4})\b/);
  if (numerica) {
    const d = Number(numerica[1]);
    const m = Number(numerica[2]);
    const y = Number(numerica[3]);
    if (d >= 1 && d <= 31 && m >= 1 && m <= 12) {
      return `${y}-${pad2(m)}-${pad2(d)}`;
    }
  }

  // dd de <mes> de yyyy  /  dd <mes> yyyy
  const conMes = txt.match(/\b(\d{1,2})\s*(?:de\s+)?([a-z]{3,12})\.?\s*(?:de\s+)?(\d{4})\b/);
  if (conMes) {
    const d = Number(conMes[1]);
    const mesKey = conMes[2].slice(0, 3);
    const m = MESES[conMes[2]] ?? MESES[mesKey];
    const y = Number(conMes[3]);
    if (m && d >= 1 && d <= 31) {
      return `${y}-${pad2(m)}-${pad2(d)}`;
    }
  }

  return undefined;
}

/** Limpia un valor de texto OCR: recorta, colapsa espacios, quita basura de bordes. */
function limpiarValor(s: string): string {
  return s
    .replace(/[|_]+/g, ' ')
    .replace(/\s{2,}/g, ' ')
    .replace(/^[\s.:,;-]+|[\s.:,;-]+$/g, '')
    .trim();
}

/** ¿La línea parece un nombre/apellido (mayúsculas, letras, sin demasiados dígitos)? */
function pareceNombre(s: string): boolean {
  const v = limpiarValor(s);
  if (v.length < 2) return false;
  if (/\d/.test(v)) return false;
  // Al menos 2 letras; admite espacios, apóstrofos y guiones de apellidos compuestos.
  return /^[A-Za-zÁÉÍÓÚÑÜáéíóúñü][A-Za-zÁÉÍÓÚÑÜáéíóúñü '.-]+$/.test(v);
}

/**
 * Extrae los campos del CI a partir del texto OCR crudo.
 *
 * Estrategia tolerante por capas:
 *  1) Etiquetas explícitas del carnet ("A:" apellidos, "N:" nombres, etc.).
 *  2) Heurísticas posicionales cuando faltan etiquetas (líneas de solo mayúsculas).
 *  3) Número de CI y fecha por patrón en cualquier parte del texto.
 *
 * Nunca lanza; devuelve lo que pudo. Campos ausentes quedan `undefined`.
 */
export function parseCedula(rawText: string): CedulaFields {
  const fields: CedulaFields = {};
  if (!rawText) return fields;

  const lineas = rawText
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l.length > 0);

  // ---- Número de CI -------------------------------------------------------
  // El carnet boliviano suele etiquetarlo como "No.", "Nro", "C.I." o similar.
  // Tomamos un grupo de 5–10 dígitos (admitiendo separadores OCR) cerca de esas
  // etiquetas; si no hay etiqueta, el grupo de dígitos más largo del documento.
  for (const linea of lineas) {
    const norm = deburr(linea).toLowerCase();
    if (/\b(c\.?\s*i\.?|no\.?|nro\.?|numero|cédula|cedula)\b/.test(norm)) {
      const m = linea.match(/(\d[\d.\s-]{4,12}\d)/);
      if (m) {
        const soloDigitos = m[1].replace(/\D/g, '');
        if (soloDigitos.length >= 5 && soloDigitos.length <= 10) {
          fields.numeroCi = soloDigitos;
          break;
        }
      }
    }
  }
  if (!fields.numeroCi) {
    let mejor = '';
    for (const linea of lineas) {
      for (const grupo of linea.matchAll(/(\d[\d.\s-]{4,12}\d)/g)) {
        const soloDigitos = grupo[1].replace(/\D/g, '');
        if (
          soloDigitos.length >= 5 &&
          soloDigitos.length <= 10 &&
          soloDigitos.length > mejor.length
        ) {
          mejor = soloDigitos;
        }
      }
    }
    if (mejor) fields.numeroCi = mejor;
  }

  // ---- Fecha de nacimiento ------------------------------------------------
  // Preferimos la línea etiquetada como "nacimiento"; si no, la primera fecha
  // plausible del documento.
  for (const linea of lineas) {
    const norm = deburr(linea).toLowerCase();
    if (/nacim|nac\.|f\.?\s*nac|fecha de nac/.test(norm)) {
      const iso = normalizarFecha(linea);
      if (iso) {
        fields.fechaNacimiento = iso;
        fields.fechaNacimientoRaw = limpiarValor(linea.replace(/.*?:/, ''));
        break;
      }
    }
  }
  if (!fields.fechaNacimiento) {
    for (const linea of lineas) {
      const iso = normalizarFecha(linea);
      if (iso) {
        fields.fechaNacimiento = iso;
        fields.fechaNacimientoRaw = limpiarValor(linea);
        break;
      }
    }
  }

  // ---- Apellidos y nombres (por etiqueta) ---------------------------------
  // El anverso del CI lista apellidos y nombres con etiquetas variables. Soporta:
  //   "Apellidos: GUTIERREZ MAMANI"  |  "A: GUTIERREZ"  |  "Nombres: JUAN CARLOS"
  let apellidosLinea = '';
  let nombresLinea = '';
  for (const linea of lineas) {
    const norm = deburr(linea).toLowerCase();
    const valor = linea.includes(':') ? linea.slice(linea.indexOf(':') + 1) : '';
    if (!apellidosLinea && /^apellid|^ap\.?\b|^a:\b|\bapellidos?\b/.test(norm)) {
      apellidosLinea = limpiarValor(valor || linea.replace(/^[^:]*/, ''));
    }
    if (!nombresLinea && /^nombre|^nom\.?\b|^n:\b|\bnombres?\b/.test(norm)) {
      nombresLinea = limpiarValor(valor || linea.replace(/^[^:]*/, ''));
    }
  }

  if (apellidosLinea && pareceNombre(apellidosLinea)) {
    const partes = apellidosLinea.split(/\s+/);
    fields.apellidoPaterno = partes[0];
    if (partes.length > 1) fields.apellidoMaterno = partes.slice(1).join(' ');
  }
  if (nombresLinea && pareceNombre(nombresLinea)) {
    fields.nombres = nombresLinea;
  }

  // ---- Fallback posicional ------------------------------------------------
  // Si no hubo etiquetas usables, tomamos líneas de solo letras mayúsculas (los
  // datos del titular en el CI van en mayúsculas). Heurística: primera línea de
  // nombre = apellidos, segunda = nombres. Conservadora a propósito.
  if (!fields.apellidoPaterno && !fields.nombres) {
    const candidatos = lineas
      .map(limpiarValor)
      .filter((l) => pareceNombre(l) && l === l.toUpperCase() && l.split(/\s+/).length <= 4);
    if (candidatos[0]) {
      const partes = candidatos[0].split(/\s+/);
      fields.apellidoPaterno = partes[0];
      if (partes.length > 1) fields.apellidoMaterno = partes.slice(1).join(' ');
    }
    if (candidatos[1]) {
      fields.nombres = candidatos[1];
    }
  }

  return fields;
}
