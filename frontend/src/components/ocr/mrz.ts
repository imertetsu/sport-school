/**
 * Lectura de la MRZ (Machine Readable Zone) TD1 del reverso del CI boliviano
 * NUEVO. Función PURA: sin DOM ni tesseract, para test aislado.
 *
 * Formato TD1 (ICAO 9303): 3 líneas de 30 caracteres.
 *
 *   Línea 1: 1-2 tipo doc ("ID") · 3-5 país emisor ("BOL") · 6-14 nº documento
 *            (9) · 15 check del nº doc · 16-30 datos opcionales.
 *   Línea 2: 1-6 fecha nac (YYMMDD) · 7 check · 8 sexo (M/F/<) · 9-14 vencimiento
 *            (YYMMDD) · 15 check · 16-18 nacionalidad · 19-29 opcional · 30 check
 *            compuesto.
 *   Línea 3: APELLIDOS<<NOMBRES (palabras internas separadas por `<`).
 *
 * El OCR sobre una FOTO (no escáner) confunde 0/O, 1/I, B/8, S/5. Por eso se
 * validan los check digits y, si no cuadran, NO se propaga el campo como fiable
 * (el llamador cae al anverso/etiquetas). El parser nunca lanza.
 */

import type { CedulaFields } from './parseCedula';

/** Valor ICAO de un carácter: dígitos = su valor, A–Z = 10–35, `<` = 0. */
function valorChar(ch: string): number {
  if (ch >= '0' && ch <= '9') return ch.charCodeAt(0) - 48;
  if (ch >= 'A' && ch <= 'Z') return ch.charCodeAt(0) - 55; // 'A' (65) -> 10
  return 0; // '<' u otros
}

/**
 * Check digit ICAO 9303: pesos cíclicos 7,3,1 sobre la subcadena; suma
 * ponderada mod 10.
 */
export function checkDigit(sub: string): number {
  const pesos = [7, 3, 1];
  let suma = 0;
  for (let i = 0; i < sub.length; i++) {
    suma += valorChar(sub[i]) * pesos[i % 3];
  }
  return suma % 10;
}

/**
 * Convierte un YY de la MRZ a un año de 4 dígitos con pivote en el año actual:
 * si `YY <= (añoActual % 100)` → 20YY, si no → 19YY. Para nacimiento nunca debe
 * resultar una fecha futura (se garantiza con el pivote).
 */
function expandirAnio(yy: number, ahora = new Date()): number {
  const pivote = ahora.getFullYear() % 100;
  return yy <= pivote ? 2000 + yy : 1900 + yy;
}

/** YYMMDD de la MRZ → ISO `YYYY-MM-DD`, o `undefined` si no es plausible. */
function fechaMrzAIso(yymmdd: string): string | undefined {
  if (!/^\d{6}$/.test(yymmdd)) return undefined;
  const yy = Number(yymmdd.slice(0, 2));
  const mm = Number(yymmdd.slice(2, 4));
  const dd = Number(yymmdd.slice(4, 6));
  if (mm < 1 || mm > 12 || dd < 1 || dd > 31) return undefined;
  const yyyy = expandirAnio(yy);
  return `${yyyy}-${String(mm).padStart(2, '0')}-${String(dd).padStart(2, '0')}`;
}

/**
 * Extrae de un bloque de texto OCR crudo las 3 líneas candidatas de una MRZ TD1.
 * Tolera líneas de longitud != 30 (recorta o rellena con `<`), espacios y
 * caracteres fuera del alfabeto MRZ. Devuelve `undefined` si no halla 3 líneas
 * "tipo MRZ" (predominio de `[A-Z0-9<]` y muchos `<`).
 */
function extraerLineasMrz(texto: string): [string, string, string] | undefined {
  const candidatas = texto
    .split(/\r?\n/)
    .map((l) => l.toUpperCase())
    // Ruido OCR frecuente: un fragmento suelto de 1–2 letras + espacio ANTES de
    // una línea MRZ (p.ej. "MÍ RODRIGUEZ<GONZALEZ<<..."). Solo lo quitamos si lo
    // que sigue ya tiene pinta de MRZ (contiene '<'), para no tocar líneas normales.
    .map((l) => (/[<«»]/.test(l) ? l.replace(/^\s*[A-ZÀ-ÿ]{1,2}\s+(?=\S*[<«»])/, '') : l))
    .map((l) => l.replace(/\s+/g, '').replace(/[«»]/g, '<'))
    // Las fotos suelen leer `<` como `K`, `C`, `(` ... pero conservar `<` reales.
    .map((l) => l.replace(/[^A-Z0-9<]/g, ''))
    .filter((l) => l.length >= 20)
    // Una línea MRZ tiene una proporción alta de letras/dígitos/`<`.
    .filter((l) => (l.match(/</g)?.length ?? 0) >= 1 || /^[A-Z0-9<]{25,}$/.test(l));

  if (candidatas.length < 3) return undefined;

  // Busca una ventana de 3 líneas consecutivas (en el array filtrado) donde la
  // primera empiece por algo tipo "ID". Si no, toma las últimas 3.
  let inicio = candidatas.findIndex((l) => /^I[D0]/.test(l));
  if (inicio < 0 || inicio + 3 > candidatas.length) {
    inicio = candidatas.length - 3;
  }
  const tres = candidatas.slice(inicio, inicio + 3);
  if (tres.length < 3) return undefined;

  const norm = (l: string): string => (l + '<'.repeat(30)).slice(0, 30);
  return [norm(tres[0]), norm(tres[1]), norm(tres[2])];
}

/** Separa la línea 3 `APELLIDOS<<NOMBRES` en sus tres campos de nombre. */
function parseNombresMrz(linea3: string): Partial<CedulaFields> {
  const out: Partial<CedulaFields> = {};
  const limpio = linea3.replace(/<+$/, ''); // quita relleno final
  const [apRaw = '', nomRaw = ''] = limpio.split('<<');
  // Tokeniza por '<'; descarta fragmentos sueltos de 1 carácter (ruido OCR
  // típico de la MRZ, p.ej. una "R" colgando al final de la línea de nombres).
  const tokens = (s: string): string[] =>
    s
      .split('<')
      .map((t) => t.trim())
      .filter((t) => t.length >= 2);
  const apellidos = tokens(apRaw);
  const nombres = tokens(nomRaw);

  if (apellidos[0]) out.apellidoPaterno = apellidos[0];
  if (apellidos.length > 1) out.apellidoMaterno = apellidos.slice(1).join(' ');
  if (nombres.length > 0) out.nombres = nombres.join(' ');
  return out;
}

/**
 * Parsea una MRZ TD1 desde el texto OCR del reverso. Valida los check digits del
 * nº de documento, de la fecha de nacimiento y el compuesto. Solo propaga
 * `numeroCi`/`fechaNacimiento` si SU check cuadra (los nombres no tienen check y
 * se devuelven siempre que haya línea 3). Devuelve `undefined` si no hay MRZ.
 */
export function parseMrz(texto: string): Partial<CedulaFields> | undefined {
  if (!texto) return undefined;
  const lineas = extraerLineasMrz(texto);
  if (!lineas) return undefined;
  const [l1, l2, l3] = lineas;

  const out: Partial<CedulaFields> = {};

  // --- Nombres (línea 3, sin check digit) ---
  Object.assign(out, parseNombresMrz(l3));

  // --- Nº de documento (línea 1, pos 6-14 + check pos 15) ---
  const docField = l1.slice(5, 14); // 9 chars
  const docCheckChar = l1.slice(14, 15);
  const docNumero = docField.replace(/</g, '').replace(/\D/g, '');
  if (
    docNumero.length >= 5 &&
    docNumero.length <= 10 &&
    /^\d$/.test(docCheckChar) &&
    checkDigit(docField) === Number(docCheckChar)
  ) {
    out.numeroCi = docNumero;
  }

  // --- Fecha de nacimiento (línea 2, pos 1-6 + check pos 7) ---
  const birthField = l2.slice(0, 6);
  const birthCheckChar = l2.slice(6, 7);
  if (/^\d$/.test(birthCheckChar) && checkDigit(birthField) === Number(birthCheckChar)) {
    const iso = fechaMrzAIso(birthField);
    if (iso) {
      out.fechaNacimiento = iso;
      out.fechaNacimientoRaw = birthField;
    }
  }

  // --- Check compuesto (línea 2, pos 30) ---
  // Cubre L1[6-30] + L2[1-7] + L2[9-15] + L2[19-29]. Si NO cuadra, los datos
  // numéricos son sospechosos: descartamos numeroCi/fecha para no propagar basura
  // (los nombres se conservan: no participan del check compuesto).
  const compInput = l1.slice(5, 30) + l2.slice(0, 7) + l2.slice(8, 15) + l2.slice(18, 29);
  const compCheckChar = l2.slice(29, 30);
  if (!/^\d$/.test(compCheckChar) || checkDigit(compInput) !== Number(compCheckChar)) {
    delete out.numeroCi;
    delete out.fechaNacimiento;
    delete out.fechaNacimientoRaw;
  }

  // Si no se extrajo NADA fiable, no hay MRZ útil.
  if (!out.numeroCi && !out.fechaNacimiento && !out.nombres) return undefined;
  return out;
}
