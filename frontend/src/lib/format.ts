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

// Etiqueta legible del nivel de categoría (PRINCIPIANTE → Principiante).
export function nivelLabel(nivel: string): string {
  if (!nivel) return '';
  return nivel.charAt(0).toUpperCase() + nivel.slice(1).toLowerCase();
}
