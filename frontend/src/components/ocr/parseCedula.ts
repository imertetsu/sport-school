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
 *    fiable (monoespaciada, con check digits). Rellena bien.
 *  - ANTIGUO: sin MRZ. NO es legible de forma fiable por OCR on-device (tinta
 *    roja + microimpresión). DECISIÓN DE PRODUCTO: se ingresa A MANO. El parser
 *    es CONSERVADOR: ante baja confianza deja el campo VACÍO (mejor vacío que
 *    basura). En particular NO toma como CI el serial de tarjeta del anverso
 *    ("NNNNNNN NN-XX") ni rellena nombres con texto institucional del carnet.
 */

import { parseMrz } from './mrz';

export { parseMrz } from './mrz';

export interface CedulaFields {
  /**
   * Número de cédula: SOLO el número del titular, sin complemento/extensión
   * (decisión de producto). Un grupo de dígitos CONTIGUO de 6–8. Si no se puede
   * leer con confianza (típico del CI antiguo), queda `undefined` y se teclea a
   * mano. Nunca incluye el serial de tarjeta ("NNNNNNN NN-XX").
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
  /**
   * Domicilio (OPCIONAL). Solo se rellena desde una línea CLARAMENTE etiquetada
   * "DOMICILIO" del reverso. Conservador: ante duda, vacío (el reverso suele salir
   * basura por OCR, así que lo normal es que quede `undefined`).
   */
  domicilio?: string;
  /**
   * Lugar de nacimiento (OPCIONAL). Solo desde una línea etiquetada "LUGAR DE
   * NACIMIENTO". Conservador: ante duda, vacío.
   */
  lugarNacimiento?: string;
  /**
   * Grupo sanguíneo (OPCIONAL), p.ej. "O+", "A-", "AB+". Solo desde una línea
   * etiquetada "GRUPO SANGUINEO"/"RH" con un grupo plausible. Conservador: ante
   * duda, vacío.
   */
  grupoSanguineo?: string;
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

/**
 * Palabras institucionales/legales del carnet que NUNCA son nombre ni apellido.
 * Se comparan deburreadas + en MAYÚSCULAS. Filtrar contra esta lista evita el bug
 * de producción donde el fallback posicional tomaba "DOCUMENTOS REGISTRADOS",
 * "ESTADO", etc. como datos del titular. Ante baja confianza, mejor campo vacío.
 */
const PALABRAS_INSTITUCIONALES = new Set([
  'DOCUMENTOS',
  'DOCUMENTO',
  'REGISTRADOS',
  'REGISTRADO',
  'REGISTRADA',
  'REGISTRO',
  // Fragmentos típicos del troceo OCR de "DOCUMENTOS REGISTRADOS".
  'REGISTRA',
  'DOS',
  'ESTADO',
  'PLURINACIONAL',
  'BOLIVIA',
  'CEDULA',
  'IDENTIDAD',
  'ENTIDAD',
  'SERVICIO',
  'GENERAL',
  'DIRECCION',
  'CERTIFICA',
  'DOMICILIO',
  'PROFESION',
  'OCUPACION',
  'NACIONAL',
  'FIRMA',
  'INTERESADO',
  'TITULAR',
  'ESTUDIANTE',
  'SOLTERO',
  'SOLTERA',
  'CASADO',
  'CASADA',
  'CERCADO',
  'NACIDO',
  'NACIDA',
  'EMITIDA',
  'EXPIRA',
  'SERIE',
  'SECCION',
  'BIO',
  // Términos frecuentes del encabezado/etiquetas que el OCR cuela como "nombre".
  'IDENTIFICACION',
  'PERSONAL',
  'PRESENTE',
  'PERTENECE',
  'REPUBLICA',
  'CIVIL',
  'NACIMIENTO',
  'EXPEDIDA',
  'EXPEDICION',
]);

/** ¿La palabra (deburreada + uppercase) es institucional (no un nombre)? */
function esPalabraInstitucional(palabra: string): boolean {
  return PALABRAS_INSTITUCIONALES.has(deburr(palabra).toUpperCase());
}

/**
 * Filtra una lista de palabras candidatas a nombre/apellido, quitando las
 * institucionales. Devuelve `[]` si todas eran institucionales (señal de que la
 * línea NO es un nombre y no debe rellenarse nada).
 */
function palabrasNombreValidas(palabras: string[]): string[] {
  return palabras.filter((p) => !esPalabraInstitucional(p));
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
    if (d >= 1 && d <= 31 && m >= 1 && m <= 12 && anioNacimientoPlausible(y)) {
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
    if (m && d >= 1 && d <= 31 && anioNacimientoPlausible(y)) {
      return `${y}-${pad2(m)}-${pad2(d)}`;
    }
  }

  // ddmm[sep]yyyy: el OCR a veces pierde el separador interno día/mes
  // (p.ej. "0504/2003" = 05/04/2003). Conservador: exige dd/mm válidos y año
  // plausible; si no, no aporta nada.
  const compacta = txt.match(/\b(\d{2})(\d{2})[\s./-]+(\d{4})\b/);
  if (compacta) {
    const d = Number(compacta[1]);
    const m = Number(compacta[2]);
    const y = Number(compacta[3]);
    if (d >= 1 && d <= 31 && m >= 1 && m <= 12 && anioNacimientoPlausible(y)) {
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
 * ¿La línea parece un nombre HUMANO real y no ruido/etiqueta institucional?
 * Mucho más estricta que `pareceNombre`: exige que, tras quitar las palabras
 * institucionales, queden ≥1 palabra "limpia" y que cada palabra restante tenga
 * pinta de nombre (≥2 letras, sin fragmentos sueltos tipo "ZO O U L"). Usada por
 * los caminos posicionales/sin etiqueta, donde el riesgo de basura es máximo.
 */
function pareceNombreHumano(s: string): boolean {
  const v = limpiarValor(s);
  if (!pareceNombre(v)) return false;
  const palabras = v.split(/\s+/).filter(Boolean);
  // Demasiados fragmentos de 1 letra (p.ej. "ZO O U L") = ruido OCR, no nombre.
  const fragmentosCortos = palabras.filter((p) => p.replace(/[^A-Za-zÁÉÍÓÚÑÜáéíóúñü]/g, '').length <= 1);
  if (fragmentosCortos.length >= 2) return false;
  const limpias = palabrasNombreValidas(palabras);
  if (limpias.length === 0) return false;
  // Si quedó UNA sola palabra y es corta/dudosa, no la tratamos como nombre.
  if (limpias.length === 1 && limpias[0].length < 3) return false;
  // Todas las palabras restantes deben tener ≥2 letras reales.
  return limpias.every((p) => p.replace(/[^A-Za-zÁÉÍÓÚÑÜáéíóúñü]/g, '').length >= 2);
}

/** Año actual, para validar plausibilidad de fechas de nacimiento. */
function anioActual(): number {
  return new Date().getFullYear();
}

/** ¿El año es plausible como año de nacimiento? Rango [1900, año_actual]. */
function anioNacimientoPlausible(y: number): boolean {
  return Number.isInteger(y) && y >= 1900 && y <= anioActual();
}

/**
 * ¿La línea (deburreada + lowercase) habla de una fecha de TRÁMITE (emisión,
 * expedición, expiración/vencimiento)? Esas fechas NO son de nacimiento; las
 * descartamos en el fallback de fecha para no meter basura.
 */
function esLineaFechaTramite(norm: string): boolean {
  return /\b(emitid|emision|expedid|expedicion|expira|expiracion|vence|vencimient|valid[ao]|caduc)/.test(
    norm,
  );
}

/** ¿Es un grupo de dígitos CONTIGUO en el rango típico del CI boliviano (6–8)? */
function esCiContiguoPlausible(soloDigitos: string): boolean {
  return /^\d{6,8}$/.test(soloDigitos);
}

/**
 * Devuelve el primer grupo de dígitos CONTIGUO de 6–8 de la línea, descartando
 * los que forman parte de un SERIAL de tarjeta (patrón "NNNNNNN NN-XX" del CI
 * antiguo, donde lo legible es el serial, NO el número del titular). Si el grupo
 * va seguido inmediatamente de un complemento tipo " 08-L3" o "-L3", se descarta.
 */
function primerCiContiguo(linea: string): string | undefined {
  const re = /\d{6,8}/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(linea)) !== null) {
    const num = m[0];
    if (!esCiContiguoPlausible(num)) continue;
    // ¿Lo que sigue inmediatamente es un sufijo de serial (complemento "NN-XX"
    // o "-XX")? Entonces este número es serial de tarjeta, no el CI.
    const resto = linea.slice(m.index + num.length);
    if (/^\s*[-\s]?\s*(\d{2}\s*-\s*[A-Za-z0-9]{1,3}|-\s*[A-Za-z0-9]{1,3})\b/.test(resto)) {
      continue;
    }
    return num;
  }
  return undefined;
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
  // CONSERVADOR: solo un grupo de dígitos CONTIGUO de 6–8 (rango típico boliviano),
  // SIN cruzar espacios/guiones (eso pegaría el complemento/serial → basura). No
  // incluimos complemento/extensión: solo el número.
  for (const linea of lineas) {
    const norm = deburr(linea).toLowerCase();
    if (/\b(c\.?\s*i\.?|no\.?|nro\.?|numero|cédula|cedula)\b/.test(norm)) {
      const ci = primerCiContiguo(linea);
      if (ci) {
        fields.numeroCi = ci;
        break;
      }
    }
  }
  if (!fields.numeroCi) {
    // Sin etiqueta: el grupo contiguo más largo dentro del rango plausible, pero
    // DESCARTANDO los seriales de tarjeta ("NNNNNNN NN-XX" del CI antiguo).
    let mejor = '';
    for (const linea of lineas) {
      const ci = primerCiContiguo(linea);
      if (ci && ci.length > mejor.length) mejor = ci;
    }
    if (mejor) fields.numeroCi = mejor;
  }

  // ---- Fecha de nacimiento ------------------------------------------------
  // Preferimos la línea etiquetada como "nacimiento". Como fallback tomamos la
  // primera fecha plausible PERO descartando líneas de emisión/expiración (para
  // no confundir una fecha de trámite con la de nacimiento). `normalizarFecha`
  // ya rechaza años fuera de [1900, año_actual].
  for (const linea of lineas) {
    const norm = deburr(linea).toLowerCase();
    if (/nacim|nacid[oa]|nac\.|f\.?\s*nac|fecha de nac/.test(norm)) {
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
      const norm = deburr(linea).toLowerCase();
      if (esLineaFechaTramite(norm)) continue; // emisión/expiración/expedición
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
    // Filtra palabras institucionales: si tras el filtro no queda nada, no setea.
    const partes = palabrasNombreValidas(apellidosLinea.split(/\s+/).filter(Boolean));
    if (partes.length > 0) {
      fields.apellidoPaterno = partes[0];
      if (partes.length > 1) fields.apellidoMaterno = partes.slice(1).join(' ');
    }
  }
  if (nombresLinea && pareceNombre(nombresLinea)) {
    const partes = palabrasNombreValidas(nombresLinea.split(/\s+/).filter(Boolean));
    if (partes.length > 0) fields.nombres = partes.join(' ');
  }

  // ---- Fallback posicional (CONSERVADOR) ----------------------------------
  // Si no hubo etiquetas usables, antes se tomaban "líneas de solo mayúsculas"
  // como apellidos/nombres. Eso capturaba basura institucional ("DOCUMENTOS
  // REGISTRADOS"). Ahora exigimos que la línea parezca un nombre HUMANO real
  // (sin palabras institucionales, sin fragmentos sueltos). Ante duda, vacío.
  if (!fields.apellidoPaterno && !fields.nombres) {
    const candidatos = lineas
      .map(limpiarValor)
      .filter(
        (l) =>
          pareceNombreHumano(l) && l === l.toUpperCase() && l.split(/\s+/).length <= 4,
      )
      // Quita las palabras institucionales que sobrevivieran dentro de la línea.
      .map((l) => palabrasNombreValidas(l.split(/\s+/).filter(Boolean)))
      .filter((palabras) => palabras.length > 0);
    if (candidatos[0]) {
      const partes = candidatos[0];
      fields.apellidoPaterno = partes[0];
      if (partes.length > 1) fields.apellidoMaterno = partes.slice(1).join(' ');
    }
    if (candidatos[1]) {
      fields.nombres = candidatos[1].join(' ');
    }
  }

  return fields;
}

// ===========================================================================
// Soporte de DOS lados (anverso + reverso) y DOS formatos (nuevo/antiguo)
// ===========================================================================

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

/** ¿La línea está etiquetada como número de CI ("No."/"C.I."/"cédula"/"Nro.")? */
function esLineaEtiquetaCi(norm: string): boolean {
  return /\b(c\.?\s*i\.?|no\.?|nro\.?|n°|nº|numero|cédula|cedula)\b/.test(norm);
}

/**
 * Extrae el número del titular en el CI ANTIGUO desde el anverso.
 *
 * DECISIÓN DE PRODUCTO: en el CI antiguo el número REAL (en tinta roja, "No.
 * #######") casi nunca lo lee el OCR on-device. Lo que el OCR SÍ lee abajo —el
 * patrón "NNNNNNN NN-XX" (p.ej. "3727170 08-L3")— es el SERIAL de la tarjeta, NO
 * el CI del titular. Por tanto:
 *  - NUNCA tomamos ese patrón de serial como CI.
 *  - Solo devolvemos un número si aparece CLARAMENTE etiquetado como CI ("No.",
 *    "C.I.", "cédula"...) y es un grupo de dígitos contiguo plausible (6–8) que
 *    NO sea, a su vez, un serial.
 *  - Ante cualquier duda → `undefined` (el usuario lo teclea a mano).
 */
function extraerCiAntiguo(anverso: string): string | undefined {
  if (!anverso) return undefined;
  const lineas = anverso
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);

  for (const linea of lineas) {
    const norm = deburr(linea).toLowerCase();
    if (!esLineaEtiquetaCi(norm)) continue;
    // Tras la etiqueta, un grupo CONTIGUO de 6–8 dígitos que no sea serial.
    const ci = primerCiContiguo(linea);
    if (ci) return ci;
  }
  // Sin etiqueta de CI clara → no devolvemos serial ni "el primer número": vacío.
  return undefined;
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
  // Solo letras (descarta dígitos/ruido residual) Y filtra palabras
  // institucionales: si lo que sigue a "pertenece a:" es texto legal/ruido, no
  // setea nada (mejor vacío que basura).
  const palabras = palabrasNombreValidas(
    nombreRaw
      .split(/\s+/)
      .map((p) => p.trim())
      .filter((p) => /^[A-Za-zÁÉÍÓÚÑÜáéíóúñü'’.-]+$/.test(p) && p.length > 1),
  );

  if (palabras.length === 0) return out;
  // Una sola palabra "limpia" es demasiado dudosa para repartir en campos: vacío.
  if (palabras.length === 1) return out;
  if (palabras.length === 2) {
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

/** Quita iconos/basura OCR del borde izquierdo (del QR/huella del reverso) y recorta. */
function limpiarReverso(s: string): string {
  return s
    .replace(/^(?:\s*\[[^\]]*\]\s*)+/, '') // iconos tipo "[m] [m]"
    .replace(/^[\s|\]>}*."'`,;:.-]+/, '') // signos sueltos al inicio
    .trim();
}

/** ¿Tiene al menos una palabra de letras reales (no solo dígitos/puntuación)? */
function tieneLetras(s: string): boolean {
  return /[A-Za-zÁÉÍÓÚÑÜáéíóúñü]{2,}/.test(s);
}

// Palabras que marcan el INICIO de OTRO campo del reverso: paran la captura
// multilínea para no tragarse el valor del campo siguiente.
// Substrings distintivos del inicio de OTRO campo del reverso (sin \b: son
// prefijos como "ocupaci"/"grupo sangu" dentro de palabras más largas).
const OTRO_CAMPO_REVERSO =
  /(domicilio|ocupaci|profesi|estado civil|grupo sangu|nacionalidad|firma del|fecha de|expira|emisi)/i;

/**
 * Valor etiquetado que puede ocupar VARIAS líneas (p.ej. domicilio o lugar de
 * nacimiento van en 2 renglones). Junta el resto de la línea de la etiqueta + hasta
 * `max` líneas de continuación, parando ante una MRZ o el inicio de otro campo.
 */
function valorMultilinea(lineas: string[], i: number, etiquetaRe: RegExp, max = 2): string {
  const m = lineas[i].match(etiquetaRe);
  if (!m) return '';
  const partes: string[] = [];
  const resto = limpiarReverso(lineas[i].slice(m.index! + m[0].length));
  if (tieneLetras(resto)) partes.push(resto);
  for (let k = 1; k <= max + 1 && partes.length < max; k++) {
    const ln = lineas[i + k];
    if (!ln) break;
    if (/<<|<{3,}/.test(ln) || /^[I<][<A-Z0-9]{6,}/.test(ln.replace(/\s/g, ''))) break; // MRZ
    if (OTRO_CAMPO_REVERSO.test(deburr(ln))) break; // empezó otro campo
    const v = limpiarReverso(ln);
    if (tieneLetras(v)) partes.push(v);
    else if (partes.length) break;
  }
  return partes
    .join(' ')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

/**
 * Extrae DOMICILIO y LUGAR DE NACIMIENTO del reverso SOLO desde líneas claramente
 * etiquetadas. CONSERVADOR: si no hay etiqueta + valor con pinta razonable, deja
 * el campo vacío (mejor vacío que basura). El reverso suele salir ruidoso, así que
 * lo normal es que queden `undefined`.
 */
function extraerDatosReverso(reverso: string): Partial<CedulaFields> {
  const out: Partial<CedulaFields> = {};
  if (!reverso) return out;

  const lineas = reverso
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);

  for (let i = 0; i < lineas.length; i++) {
    const norm = deburr(lineas[i]).toLowerCase();

    // LUGAR DE NACIMIENTO — la etiqueta suele garblearse en foto real ("lugar de"
    // se pierde y queda "...NACIMIENTO"). Aceptamos "nacimiento" salvo que sea la
    // línea de FECHA de nacimiento (esa no lleva un lugar). El valor (depto-prov-mun)
    // puede ocupar 2 renglones.
    if (out.lugarNacimiento == null && /\bnacimiento\b/.test(norm) && !/fecha/.test(norm)) {
      const valor = valorMultilinea(lineas, i, /(?:lugar de\s+)?nac\w*\s*:?\s*/i, 2);
      if (tieneLetras(valor)) out.lugarNacimiento = valor;
      continue;
    }

    if (out.domicilio == null && /\bdomicilio\b/.test(norm)) {
      const valor = valorMultilinea(lineas, i, /domicilio\s*:?\s*/i, 2);
      if (tieneLetras(valor)) out.domicilio = valor;
      continue;
    }
  }

  return out;
}

/**
 * Extrae el GRUPO SANGUÍNEO del reverso SOLO desde una línea etiquetada
 * ("GRUPO SANGUINEO" o "RH") con un grupo plausible (A|B|AB|O) + factor (+/-/RH).
 * CONSERVADOR: si no hay etiqueta + grupo claro, deja vacío. Normaliza a la forma
 * "<grupo><signo>" (p.ej. "O+", "A-", "AB+"); si solo hay grupo sin signo, devuelve
 * el grupo a secas.
 */
function extraerGrupoSanguineo(reverso: string): string | undefined {
  if (!reverso) return undefined;

  const lineas = reverso
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);

  for (let i = 0; i < lineas.length; i++) {
    const norm = deburr(lineas[i]).toLowerCase();
    if (!/\bgrupo sanguineo\b|\brh\b|\bgrupo sanguinio\b/.test(norm)) continue;
    // El valor ("A RH+") puede estar en la MISMA línea de la etiqueta o en la
    // SIGUIENTE (en el CI nuevo la etiqueta va arriba y el valor debajo). Exigimos
    // el factor +/- para no confundir una "A"/"O" suelta de otra palabra.
    for (const cand of [lineas[i], lineas[i + 1] ?? '']) {
      const m = cand.match(/\b(AB|A|B|O)\s*(?:RH)?\s*([+-])/i);
      if (m) return `${m[1].toUpperCase()}${m[2]}`;
    }
  }
  return undefined;
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

  // Campos OPCIONALES del reverso (CONSERVADOR: solo si vienen etiquetados claro).
  Object.assign(out, extraerDatosReverso(reverso));
  const grupo = extraerGrupoSanguineo(reverso);
  if (grupo) out.grupoSanguineo = grupo;

  // Fecha de nacimiento — CONSERVADOR: SOLO desde una línea etiquetada como
  // nacimiento ("nacid[oa]"/"nacimiento"/"f. nac"). En el CI antiguo abundan
  // fechas de EMISIÓN/EXPIRACIÓN; tomar "la primera fecha que aparezca" mete
  // basura (p.ej. fecha de emisión como nacimiento). Si no hay línea de
  // nacimiento legible, dejamos la fecha VACÍA (el usuario la teclea).
  const lineasRev = reverso
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);
  for (const linea of lineasRev) {
    const norm = deburr(linea).toLowerCase();
    if (/nacid[oa]\b|nacid[oa] el|fecha de nac|nacim/.test(norm)) {
      const iso = normalizarFecha(linea);
      if (iso) {
        out.fechaNacimiento = iso;
        out.fechaNacimientoRaw = limpiarValor(linea.replace(/.*?:/, ''));
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
 * Campos OPCIONALES etiquetados del reverso (domicilio, lugar de nacimiento, grupo
 * sanguíneo). CONSERVADOR: solo desde etiquetas claras. Se prueba el reverso y,
 * por si el usuario invirtió las capturas, también el anverso. Independiente del
 * formato (nuevo/antiguo/desconocido). Ante duda, los campos quedan `undefined`.
 */
function rellenarOpcionalesReverso(out: CedulaFields, r: string, a: string): void {
  rellenarVacios(out, extraerDatosReverso(r));
  rellenarVacios(out, extraerDatosReverso(a));
  if (out.grupoSanguineo == null) {
    const grupo = extraerGrupoSanguineo(r) ?? extraerGrupoSanguineo(a);
    if (grupo) out.grupoSanguineo = grupo;
  }
}

/**
 * Nombres y apellidos del ANVERSO del CI NUEVO desde sus etiquetas ("NOMBRES" /
 * "APELLIDOS"), con el valor en la MISMA línea o en la SIGUIENTE (el carnet nuevo
 * los imprime debajo de la etiqueta). Es MÁS completo que la MRZ —que trunca el 2º
 * nombre—, por eso se prefiere para el nombre. Conservador: valida con `pareceNombre`.
 */
/** Recorta basura no-alfabética en los BORDES (el OCR antepone `"`, `”`, `-`…). */
function recortarNoLetras(s: string): string {
  const L = 'A-Za-zÁÉÍÓÚÑÜáéíóúñü';
  return s
    .replace(new RegExp(`^[^${L}]+`), '')
    .replace(new RegExp(`[^${L}]+$`), '')
    .trim();
}

function parseNombresAnverso(anverso: string): Partial<CedulaFields> {
  const out: Partial<CedulaFields> = {};
  if (!anverso) return out;
  const lineas = anverso
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);
  // El valor puede quedar en lo que sigue a la etiqueta o en las 1-2 líneas
  // siguientes (el carnet lo imprime debajo y el OCR deja basura tras la etiqueta).
  // Tomamos el PRIMER candidato que parezca un nombre real.
  const tomar = (i: number, re: RegExp): string => {
    const m = lineas[i].match(re);
    if (!m) return '';
    const cands = [lineas[i].slice(m.index! + m[0].length), lineas[i + 1] ?? '', lineas[i + 2] ?? ''];
    for (const c of cands) {
      const v = recortarNoLetras(limpiarValor(c));
      if (v && pareceNombre(v)) return v;
    }
    return '';
  };
  for (let i = 0; i < lineas.length; i++) {
    const norm = deburr(lineas[i]).toLowerCase();
    if (out.nombres == null && /\bnombres?\b/.test(norm) && !/apellido/.test(norm)) {
      const v = tomar(i, /nombres?\s*\$?\s*:?\s*/i);
      if (v) out.nombres = v;
    }
    if (out.apellidoPaterno == null && /\bapellidos?\b/.test(norm)) {
      const v = tomar(i, /apellidos?\s*:?\s*/i);
      if (v) {
        const partes = v.split(/\s+/);
        out.apellidoPaterno = partes[0];
        if (partes.length > 1) out.apellidoMaterno = partes.slice(1).join(' ');
      }
    }
  }
  return out;
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
    // NOMBRE primero desde las etiquetas del anverso (más completo que la MRZ, que
    // trunca el 2º nombre). Luego MRZ (número/fecha validados por check digits, y
    // nombre si el anverso no se leyó). Luego anverso/combinado para huecos.
    rellenarVacios(out, parseNombresAnverso(a));
    if (mrz) rellenarVacios(out, mrz);
    rellenarVacios(out, parseCedula(a));
    rellenarVacios(out, parseCedula(combinado));
    // Opcionales etiquetados del reverso (conservador).
    rellenarOpcionalesReverso(out, r, a);
    return out;
  }

  if (formato === 'antiguo') {
    rellenarVacios(out, parseAntiguo(a, r));
    // Relleno conservador con el parser genérico para huecos (p.ej. fecha en el
    // anverso, número en el reverso si el usuario invirtió las capturas).
    rellenarVacios(out, parseAntiguo(r, a));
    rellenarVacios(out, parseCedula(combinado));
    rellenarOpcionalesReverso(out, r, a);
    return out;
  }

  // Desconocido: parser genérico sobre el texto combinado.
  rellenarVacios(out, parseCedula(combinado));
  rellenarOpcionalesReverso(out, r, a);
  return out;
}
