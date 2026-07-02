import { describe, expect, it } from 'vitest';
import { formatDate, formatMoney } from './format';

// Fechas "solo día" (YYYY-MM-DD): deben formatearse ancladas al día LOCAL. El bug
// original venía de `new Date("2016-07-04")`, que JS interpreta como medianoche UTC;
// en zonas negativas (Bolivia, UTC−4) retrocedía al día anterior ("3 jul"). Estos
// tests fijan la salida correcta (sin corrimiento) y, en un runner con TZ negativa,
// fallan si se revierte el fix.
describe('formatDate', () => {
  it('fecha de nacimiento no corre un día (4 jul, no 3 jul)', () => {
    expect(formatDate('2016-07-04')).toMatch(/^4 /);
  });

  it('el primero de mes no retrocede al mes anterior', () => {
    expect(formatDate('2026-01-01')).toMatch(/^1 ene/);
  });

  it('vacío/nulo devuelve guion', () => {
    expect(formatDate(null)).toBe('—');
    expect(formatDate(undefined)).toBe('—');
    expect(formatDate('')).toBe('—');
  });

  it('un datetime ISO completo (con hora) se sigue parseando', () => {
    expect(formatDate('2026-05-25T18:30:00Z')).toMatch(/25/);
  });
});

describe('formatMoney', () => {
  it('formatea un monto e incluye el número', () => {
    expect(formatMoney(60)).toContain('60');
  });

  it('vacío/NaN devuelve guion', () => {
    expect(formatMoney(null)).toBe('—');
    expect(formatMoney('abc')).toBe('—');
  });
});
