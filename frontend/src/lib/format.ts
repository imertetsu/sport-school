// Formato de dinero y fechas. Moneda/locale son por organización (RNF-04):
// no hardcodear el símbolo. Defaults razonables para Bolivia (es-BO / BOB → "Bs").

const DEFAULT_LOCALE = 'es-BO';
const DEFAULT_CURRENCY = 'BOB';

export interface OrgLocale {
  locale?: string;
  currency?: string;
}

export function formatMoney(
  amount: number | string | null | undefined,
  org: OrgLocale = {},
): string {
  if (amount === null || amount === undefined || amount === '') return '—';
  const value = typeof amount === 'string' ? Number(amount) : amount;
  if (Number.isNaN(value)) return '—';
  const locale = org.locale ?? DEFAULT_LOCALE;
  const currency = org.currency ?? DEFAULT_CURRENCY;
  try {
    return new Intl.NumberFormat(locale, {
      style: 'currency',
      currency,
      currencyDisplay: 'narrowSymbol',
      minimumFractionDigits: 0,
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `Bs ${value.toLocaleString(locale)}`;
  }
}

export function formatDate(
  iso: string | null | undefined,
  org: OrgLocale = {},
): string {
  if (!iso) return '—';
  // Una fecha "solo día" (YYYY-MM-DD) se debe interpretar como medianoche LOCAL,
  // no UTC: `new Date("2016-07-04")` es UTC y en zonas negativas (Bolivia, UTC−4)
  // retrocede un día al mostrarse (mostraba "3 jul"). Construir con componentes
  // (año, mes, día) la ancla al día local correcto. Los datetime con hora/offset
  // (ISO completo) siguen parseándose tal cual.
  const soloDia = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  const d = soloDia
    ? new Date(Number(soloDia[1]), Number(soloDia[2]) - 1, Number(soloDia[3]))
    : new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  const locale = org.locale ?? DEFAULT_LOCALE;
  return new Intl.DateTimeFormat(locale, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  }).format(d);
}

// Meses en español para el formato largo "5 junio 2026" (día mes año, sin "de").
const MESES_LARGO_ES = [
  'enero',
  'febrero',
  'marzo',
  'abril',
  'mayo',
  'junio',
  'julio',
  'agosto',
  'septiembre',
  'octubre',
  'noviembre',
  'diciembre',
];

// Fecha "día mes año" en español, p. ej. `5 junio 2026`. Misma ancla local que
// `formatDate` para las fechas "solo día" (no retrocede por zona horaria).
export function formatDateLarga(iso: string | null | undefined): string {
  if (!iso) return '—';
  const soloDia = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  const d = soloDia
    ? new Date(Number(soloDia[1]), Number(soloDia[2]) - 1, Number(soloDia[3]))
    : new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return `${d.getDate()} ${MESES_LARGO_ES[d.getMonth()]} ${d.getFullYear()}`;
}

// Mes (en MAYÚSCULAS) de una fecha, p. ej. "JULIO". Se usa en la columna "Cuota"
// del historial/kardex: la cuota se etiqueta por el MES en que vence el pago.
export function mesLargo(iso: string | null | undefined): string {
  if (!iso) return '—';
  const soloDia = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  const d = soloDia
    ? new Date(Number(soloDia[1]), Number(soloDia[2]) - 1, Number(soloDia[3]))
    : new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return MESES_LARGO_ES[d.getMonth()].toUpperCase();
}

// Formato de hora a partir de un "time" del backend (HH:MM o HH:MM:SS).
// Usa el locale de la organización (RNF-04): no hardcodear el formato. Devuelve
// p. ej. "16:30" (es-BO usa reloj de 24h por defecto).
export function formatTime(
  time: string | null | undefined,
  org: OrgLocale = {},
): string {
  if (!time) return '—';
  const [hStr, mStr] = time.split(':');
  const h = Number(hStr);
  const m = Number(mStr);
  if (Number.isNaN(h) || Number.isNaN(m)) return '—';
  const locale = org.locale ?? DEFAULT_LOCALE;
  const d = new Date(2000, 0, 1, h, m);
  try {
    // Reloj de 24h (h23): apropiado para una rejilla de horarios y consistente
    // entre locales; se respeta el locale para dígitos/separadores.
    return new Intl.DateTimeFormat(locale, {
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    }).format(d);
  } catch {
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
  }
}

// Etiqueta legible del nivel de categoría (PRINCIPIANTE → Principiante).
export function nivelLabel(nivel: string): string {
  if (!nivel) return '';
  return nivel.charAt(0).toUpperCase() + nivel.slice(1).toLowerCase();
}
