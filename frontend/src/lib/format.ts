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
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  const locale = org.locale ?? DEFAULT_LOCALE;
  return new Intl.DateTimeFormat(locale, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  }).format(d);
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
