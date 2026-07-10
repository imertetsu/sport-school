import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import type { AsistenciaReporte, IngresosReporte } from '@/api/types';

// Mock del cliente API: los tests usan mocks, no la API real.
const ingresosMock = vi.fn();
const asistenciaMock = vi.fn();
const categoriasMock = vi.fn();
vi.mock('@/api/client', () => ({
  api: {
    reportesIngresos: (...args: unknown[]) => ingresosMock(...args),
    reportesAsistencia: (...args: unknown[]) => asistenciaMock(...args),
    categorias: (...args: unknown[]) => categoriasMock(...args),
  },
  ApiError: class ApiError extends Error {},
}));

// Contexto de sucursal (Todas las sucursales) con una sucursal de ejemplo.
vi.mock('@/components/shell/SucursalContext', () => ({
  useSucursales: () => ({
    sucursales: [{ id: 's1', nombre: 'Centro', direccion: '' }],
    loading: false,
    error: null,
    selected: '',
    setSelected: vi.fn(),
  }),
}));

import { Reportes } from './Reportes';

const ANIO = new Date().getFullYear();

const INGRESOS: IngresosReporte = {
  anio: ANIO,
  total: '12400',
  n_pagos: 31,
  meses: [
    { mes: 1, etiqueta: 'ene', monto: '0', n_pagos: 0 },
    { mes: 2, etiqueta: 'feb', monto: '0', n_pagos: 0 },
    { mes: 3, etiqueta: 'mar', monto: '1500', n_pagos: 4 },
    { mes: 4, etiqueta: 'abr', monto: '2000', n_pagos: 5 },
    { mes: 5, etiqueta: 'may', monto: '3400', n_pagos: 8 },
    { mes: 6, etiqueta: 'jun', monto: '5500', n_pagos: 14 },
    { mes: 7, etiqueta: 'jul', monto: '0', n_pagos: 0 },
    { mes: 8, etiqueta: 'ago', monto: '0', n_pagos: 0 },
    { mes: 9, etiqueta: 'sep', monto: '0', n_pagos: 0 },
    { mes: 10, etiqueta: 'oct', monto: '0', n_pagos: 0 },
    { mes: 11, etiqueta: 'nov', monto: '0', n_pagos: 0 },
    { mes: 12, etiqueta: 'dic', monto: '0', n_pagos: 0 },
  ],
};

const ASISTENCIA: AsistenciaReporte = {
  desde: '2026-03-01',
  hasta: '2026-06-01',
  global: { sesiones: 40, presentes: 360, ausentes: 90, total_marcas: 450, pct_presente: 80 },
  por_categoria: [
    {
      categoria: { id: 'c1', nombre: 'Sub-14 Intermedio' },
      sucursal: { nombre: 'Centro' },
      sesiones: 20,
      presentes: 180,
      ausentes: 20,
      total_marcas: 200,
      pct_presente: 90,
    },
    {
      categoria: { id: 'c2', nombre: 'Sub-10 Principiante' },
      sucursal: { nombre: 'Cala Cala' },
      sesiones: 20,
      presentes: 180,
      ausentes: 70,
      total_marcas: 250,
      pct_presente: 72,
    },
  ],
  por_deportista: [
    {
      deportista: { id: 'a1', nombre_completo: 'Mateo Quispe Mamani' },
      categoria: 'Sub-14 Intermedio',
      sucursal: 'Centro',
      sesiones: 20,
      presentes: 18,
      ausentes: 2,
      total_marcas: 20,
      pct_presente: 90,
    },
  ],
};

function renderReportes() {
  return render(
    <MemoryRouter>
      <Reportes />
    </MemoryRouter>,
  );
}

describe('Reportes', () => {
  beforeEach(() => {
    ingresosMock.mockReset();
    asistenciaMock.mockReset();
    categoriasMock.mockReset();
    ingresosMock.mockResolvedValue(INGRESOS);
    asistenciaMock.mockResolvedValue(ASISTENCIA);
    categoriasMock.mockResolvedValue([]);
  });
  afterEach(() => vi.clearAllMocks());

  it('renderiza las 12 barras de ingresos con altura proporcional al monto', async () => {
    const { container } = renderReportes();
    await screen.findByText(`Total ${ANIO}`);

    const barras = container.querySelectorAll<HTMLElement>('.barchart__bar');
    expect(barras.length).toBe(12);

    // El mes pico (jun, 5500 = max) llega al 100%; los meses sin ingresos a 0%.
    const junio = barras[5];
    expect(junio.style.height).toBe('100%');
    expect(barras[0].style.height).toBe('0%');
    // Los meses vacíos llevan la clase placeholder.
    expect(barras[0].className).toContain('barchart__bar--empty');
  });

  it('muestra el total del año formateado', async () => {
    const { container } = renderReportes();
    await screen.findByText(`Total ${ANIO}`);
    const total = container.querySelector('.reportes__total-value');
    // Total formateado por org (incluye "12.400" en es-BO; no comprobamos símbolo).
    expect(total?.textContent).toMatch(/12.?400/);
  });

  it('renderiza la tabla de asistencia por categoría con datos mock', async () => {
    renderReportes();
    await screen.findByRole('table', { name: 'Asistencia por categoría' });
    // Acotamos a la tabla de categorías: la de deportistas repite % y nombres.
    const tabla = within(screen.getByRole('table', { name: 'Asistencia por categoría' }));
    expect(tabla.getByText('Sub-14 Intermedio')).toBeInTheDocument();
    expect(tabla.getByText('Sub-10 Principiante')).toBeInTheDocument();
    // presentes / total
    expect(tabla.getByText('180 / 200')).toBeInTheDocument();
    expect(tabla.getByText('180 / 250')).toBeInTheDocument();
    // % por categoría
    expect(tabla.getByText('90%')).toBeInTheDocument();
    expect(tabla.getByText('72%')).toBeInTheDocument();
  });

  it('renderiza la tabla de asistencia por deportista del período', async () => {
    renderReportes();
    await screen.findByRole('table', { name: 'Asistencia por deportista' });
    const tabla = within(screen.getByRole('table', { name: 'Asistencia por deportista' }));
    expect(tabla.getByText('Mateo Quispe Mamani')).toBeInTheDocument();
    expect(tabla.getByText('Sub-14 Intermedio · Centro')).toBeInTheDocument();
    expect(tabla.getByText('18 / 20')).toBeInTheDocument(); // presentes / total
    expect(tabla.getByText('90%')).toBeInTheDocument();
  });

  it('muestra el % global de asistencia como KPI', async () => {
    const { container } = renderReportes();
    await screen.findByText('% Asistencia global');
    const kpi = container.querySelector('.asistencia-kpi__value');
    expect(kpi?.textContent).toBe('80%');
  });

  it('renderiza barras de progreso por categoría con el ancho del %', async () => {
    renderReportes();
    const tabla = await screen.findByRole('table', { name: 'Asistencia por categoría' });
    const fills = tabla.querySelectorAll<HTMLElement>('.progress__fill');
    expect(fills.length).toBe(2);
    expect(fills[0].style.width).toBe('90%');
    expect(fills[1].style.width).toBe('72%');
  });

  it('recarga ingresos al cambiar el año seleccionado', async () => {
    const user = userEvent.setup();
    renderReportes();
    await screen.findByText(`Total ${ANIO}`);
    ingresosMock.mockClear();

    const select = screen.getByLabelText('Año');
    await user.selectOptions(select, String(ANIO - 1));
    await waitFor(() =>
      expect(ingresosMock).toHaveBeenCalledWith(ANIO - 1, expect.anything()),
    );
  });

  it('aplica el filtro de rango de fechas a la consulta de asistencia', async () => {
    const user = userEvent.setup();
    renderReportes();
    await screen.findByText('Sub-14 Intermedio');
    asistenciaMock.mockClear();

    const desde = screen.getByLabelText('Desde');
    await user.clear(desde);
    await user.type(desde, '2026-01-01');
    await waitFor(() =>
      expect(asistenciaMock).toHaveBeenCalledWith(
        expect.objectContaining({ desde: '2026-01-01' }),
        expect.anything(),
      ),
    );
  });

  it('muestra el mensaje vacío cuando no hay marcas de asistencia', async () => {
    asistenciaMock.mockResolvedValue({ ...ASISTENCIA, por_categoria: [] });
    renderReportes();
    expect(
      await screen.findByText('Sin marcas de asistencia en el rango seleccionado'),
    ).toBeInTheDocument();
  });

  it('marca el % global con un badge de tono según el nivel', async () => {
    renderReportes();
    // 80% -> "presente" badge (verde). Comprobamos que el badge aparece.
    const badge = await screen.findByText('80% presente');
    expect(badge).toBeInTheDocument();
  });
});
