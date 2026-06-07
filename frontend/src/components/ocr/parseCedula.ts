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
 *
 * Soporta los DOS formatos vigentes del CI boliviano:
 *  - NUEVO: con MRZ TD1 en el reverso (ver `mrz.ts`); la MRZ es la fuente más
 *    fiable (monoespaciada, con check digits).
 *  - ANTIGUO: sin MRZ; el número real va en el anverso (abajo, junto al
 *    complemento/extensión; el "No." de arriba es FOLIO de trámite, no el CI) y
 *    el nombre está SOLO en el reverso tras "...pertenece A:" en orden
 *    NOMBRES → APELLIDOS.
 */

import { parseMrz } from './mrz';

export { parseMrz } from './mrz';

export interface CedulaFields {
  /**
   * Número de cédula en formato canónico `"<numero>[ <complemento>][ <EXT>]"`
   * (espacio separador, EXT departamental en MAYÚSCULAS, ej. `"3727170 CB"`).
   * Si no se detecta complemento/extensión con confianza, es solo el número.
   */
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

// ===========================================================================
// Soporte de DOS lados (anverso + reverso) y DOS formatos (nuevo/antiguo)
// ===========================================================================

/** Códigos departamentales de Bolivia usados como extensión del CI. */
const DEPARTAMENTOS = new Set(['LP', 'CB', 'SC', 'OR', 'PT', 'TJ', 'CH', 'BE', 'PD']);

/**
 * Detecta el formato del CI por el texto OCR (de uno o ambos lados):
 *  - 'nuevo' si parece haber una MRZ TD1 válida (la fuente de verdad del nuevo).
 *  - 'antiguo' si hay marcas típicas del viejo (pertenece a:, expedida/emitida,
 *    "nacido el <fecha larga>") sin MRZ.
 *  - 'desconocido' si no hay señales claras.
 */
export function detectarFormato(texto: string): 'nuevo' | 'antiguo' | 'desconocido' {
  if (!texto) return 'desconocido';
  if (parseMrz(texto)) return 'nuevo';

  const norm = deburr(texto).toLowerCase();
  // Heurística de MRZ aunque no validara: 2+ líneas con muchos '<' seguidos.
  if (/<{3,}/.test(texto)) return 'nuevo';

  if (/pertenece a\b|nacido el\b|nacida el\b|expedid|emitid|estado civil/.test(norm)) {
    return 'antiguo';
  }
  return 'desconocido';
}

/** Quita el complemento `Nro.`/`No.` (folio de trámite) de una línea OCR. */
function esLineaFolio(norm: string): boolean {
  return /\b(no\.?|nro\.?|n°|nº|folio|tramite|tr[aá]mite)\b/.test(norm);
}

/**
 * Extrae el número REAL del titular en el CI ANTIGUO desde el anverso, junto a
 * su complemento/extensión, en el FORMATO CANÓNICO.
 *
 * El anverso del antiguo lleva ARRIBA un `No. #######` que es FOLIO de trámite
 * (a descartar) y ABAJO el número real, normalmente acompañado de un sufijo
 * tipo `08-L3` (complemento/lote) o un código departamental (LP/CB/SC...).
 * Heurística: preferir el número acompañado de ese sufijo/depto; descartar el
 * que sigue a la etiqueta "No.".
 */
function extraerCiAntiguo(anverso: string): string | undefined {
  if (!anverso) return undefined;
  const lineas = anverso
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);

  type Cand = { numero: string; complemento?: string; ext?: string; score: number };
  const candidatos: Cand[] = [];

  for (const linea of lineas) {
    const norm = deburr(linea).toLowerCase();
    const esFolio = esLineaFolio(norm);
    const sufijoLinea = deburr(linea).toUpperCase();

    // 1) Patrón estructurado: número base (5-10 dígitos, SIN espacios internos)
    //    seguido de complemento "08-L3" o de un código departamental. Es la
    //    señal más fuerte de que es el número REAL del titular (no el folio).
    let estructurado = false;
    for (const m of sufijoLinea.matchAll(/\b(\d{5,10})\s*[-\s]?\s*(\d{2}-[A-Z0-9]{2}|[A-Z]{2})\b/g)) {
      const numero = m[1];
      const cola = m[2];
      let score = 5; // patrón estructurado: muy probable
      let complemento: string | undefined;
      let ext: string | undefined;
      if (/^\d{2}-[A-Z0-9]{2}$/.test(cola)) {
        complemento = cola;
      } else if (DEPARTAMENTOS.has(cola)) {
        ext = cola;
      } else {
        // Dos letras que NO son depto: no es extensión fiable; no la anexamos.
        score = 2;
      }
      if (esFolio) score -= 5;
      candidatos.push({ numero, complemento, ext, score });
      estructurado = true;
    }

    // 2) Si no hubo patrón estructurado en la línea, toma un grupo de dígitos
    //    suelto (admite separadores OCR) como candidato de menor confianza.
    if (!estructurado) {
      for (const m of linea.matchAll(/(\d[\d.\s-]{4,12}\d)/g)) {
        const numero = m[1].replace(/\D/g, '');
        if (numero.length < 5 || numero.length > 10) continue;
        const score = esFolio ? -5 : 1; // sin sufijo no sube de confianza
        candidatos.push({ numero, score });
      }
    }
  }

  if (candidatos.length === 0) return undefined;
  // Mejor score; a igualdad, el más largo (más específico).
  candidatos.sort((a, b) => b.score - a.score || b.numero.length - a.numero.length);
  const mejor = candidatos[0];

  let out = mejor.numero;
  if (mejor.complemento) out += ` ${mejor.complemento}`;
  if (mejor.ext) out += ` ${mejor.ext}`;
  return out;
}

/**
 * Extrae el nombre del CI ANTIGUO desde el REVERSO. El reverso dice
 * "...pertenece A: NOMBRES APELLIDOS" en orden NOMBRES → APELLIDOS.
 * Heurística best-effort: últimas 2 palabras = apellidos (paterno, materno), el
 * resto = nombres. El usuario corrige a mano si la persona tiene 1 apellido o
 * apellidos compuestos.
 */
function extraerNombreAntiguo(reverso: string): Partial<CedulaFields> {
  const out: Partial<CedulaFields> = {};
  if (!reverso) return out;

  const lineas = reverso
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);

  let nombreRaw = '';
  for (let i = 0; i < lineas.length; i++) {
    const norm = deburr(lineas[i]).toLowerCase();
    // "...pertenece a: JUAN ..." (la etiqueta puede venir sin ':' por el OCR).
    // Localiza la etiqueta en el texto deburreado y corta el ORIGINAL en la misma
    // posición (deburr conserva longitud salvo por el colapso de espacios, así que
    // re-buscamos sobre la línea original con un regex case-insensitive).
    const m = lineas[i].match(/pertenece\s+a\b\s*:?\s*(.*)$/i);
    if (m) {
      let valor = limpiarValor(m[1]);
      // Si la etiqueta quedó sola en su línea, toma la siguiente.
      if (!valor && lineas[i + 1]) valor = limpiarValor(lineas[i + 1]);
      if (valor) {
        nombreRaw = valor;
        break;
      }
    } else if (/pertenece a\b\s*:?\s*$/.test(norm) && lineas[i + 1]) {
      // Etiqueta sola al final de la línea (acentos perdidos por OCR) → siguiente.
      const valor = limpiarValor(lineas[i + 1]);
      if (valor) {
        nombreRaw = valor;
        break;
      }
    }
  }

  if (!nombreRaw) return out;
  // Solo letras (descarta dígitos/ruido residual).
  const palabras = nombreRaw
    .split(/\s+/)
    .map((p) => p.trim())
    .filter((p) => /^[A-Za-zÁÉÍÓÚÑÜáéíóúñü'’.-]+$/.test(p) && p.length > 1);

  if (palabras.length === 0) return out;
  if (palabras.length === 1) {
    out.nombres = palabras[0];
  } else if (palabras.length === 2) {
    out.nombres = palabras[0];
    out.apellidoPaterno = palabras[1];
  } else {
    // últimas 2 = apellidos; el resto = nombres (orden NOMBRES → APELLIDOS).
    out.apellidoMaterno = palabras[palabras.length - 1];
    out.apellidoPaterno = palabras[palabras.length - 2];
    out.nombres = palabras.slice(0, palabras.length - 2).join(' ');
  }
  return out;
}

/**
 * Parser del CI ANTIGUO combinando anverso (número+complemento) y reverso
 * (nombre + fecha de nacimiento). Best-effort; nunca lanza.
 */
export function parseAntiguo(anverso: string, reverso: string): Partial<CedulaFields> {
  const out: Partial<CedulaFields> = {};

  const ci = extraerCiAntiguo(anverso);
  if (ci) out.numeroCi = ci;

  Object.assign(out, extraerNombreAntiguo(reverso));

  // Fecha de nacimiento: el reverso trae "Nacido el <fecha larga>".
  const lineasRev = reverso
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);
  for (const linea of lineasRev) {
    const norm = deburr(linea).toLowerCase();
    if (/nacid[oa] el|fecha de nac|nacim/.test(norm)) {
      const iso = normalizarFecha(linea);
      if (iso) {
        out.fechaNacimiento = iso;
        out.fechaNacimientoRaw = limpiarValor(linea.replace(/.*?:/, ''));
        break;
      }
    }
  }
  // Fallback: primera fecha plausible del reverso.
  if (!out.fechaNacimiento) {
    for (const linea of lineasRev) {
      const iso = normalizarFecha(linea);
      if (iso) {
        out.fechaNacimiento = iso;
        out.fechaNacimientoRaw = limpiarValor(linea);
        break;
      }
    }
  }

  return out;
}

/** Aplica `src` sobre `dst` solo en campos aún vacíos (no pisa lo ya fiable). */
function rellenarVacios(dst: CedulaFields, src: Partial<CedulaFields>): void {
  for (const k of Object.keys(src) as (keyof CedulaFields)[]) {
    const v = src[k];
    if (v != null && v !== '' && (dst[k] == null || dst[k] === '')) {
      dst[k] = v;
    }
  }
}

/**
 * Orquesta la detección de formato y el merge de ambos lados. Es la entrada que
 * usa `DocumentScanner`. Reglas:
 *  - CI NUEVO: MRZ-first (más fiable por sus check digits); el anverso/etiquetas
 *    rellenan lo que la MRZ no validó.
 *  - CI ANTIGUO: combina anverso (CI + complemento) con reverso (nombre + fecha).
 *  - DESCONOCIDO: parser genérico de un lado sobre el texto combinado.
 *
 * Funciona con un solo lado (el otro = ''): nunca lanza; devuelve lo que pudo.
 */
export function mergeLados(anverso: string, reverso: string): CedulaFields {
  const a = anverso ?? '';
  const r = reverso ?? '';
  const combinado = [a, r].filter(Boolean).join('\n');
  const out: CedulaFields = {};

  // La MRZ puede aparecer en cualquiera de los textos (el usuario podría haber
  // capturado el reverso como "anverso"). Probamos ambos.
  const mrz = parseMrz(r) ?? parseMrz(a);
  const formato = mrz ? 'nuevo' : detectarFormato(combinado);

  if (formato === 'nuevo') {
    // MRZ-first.
    if (mrz) rellenarVacios(out, mrz);
    // Anverso del nuevo: etiquetas "NOMBRES/APELLIDOS/N°/FECHA DE NACIMIENTO".
    rellenarVacios(out, parseCedula(a));
    // Como último recurso, cualquier campo del texto combinado.
    rellenarVacios(out, parseCedula(combinado));
    return out;
  }

  if (formato === 'antiguo') {
    rellenarVacios(out, parseAntiguo(a, r));
    // Relleno conservador con el parser genérico para huecos (p.ej. fecha en el
    // anverso, número en el reverso si el usuario invirtió las capturas).
    rellenarVacios(out, parseAntiguo(r, a));
    rellenarVacios(out, parseCedula(combinado));
    return out;
  }

  // Desconocido: parser genérico sobre el texto combinado.
  rellenarVacios(out, parseCedula(combinado));
  return out;
}
