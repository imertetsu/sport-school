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

// Helper: arma un mes con sus 3 series (utilidad = ingresos - egresos).
function mes(
  n: number,
  etiqueta: string,
  monto: string,
  egresos = '0',
  n_pagos = 0,
): IngresosReporte['meses'][number] {
  return {
    mes: n,
    etiqueta,
    monto,
    n_pagos,
    egresos,
    n_egresos: egresos === '0' ? 0 : 1,
    utilidad: String(Number(monto) - Number(egresos)),
  };
}

const INGRESOS: IngresosReporte = {
  anio: ANIO,
  total: '12400',
  n_pagos: 31,
  total_egresos: '2400',
  n_egresos: 4,
  utilidad: '10000',
  sucursal_id: null,
  meses: [
    mes(1, 'ene', '0'),
    mes(2, 'feb', '0'),
    mes(3, 'mar', '1500', '400', 4),
    mes(4, 'abr', '2000', '500', 5),
    mes(5, 'may', '3400', '900', 8),
    mes(6, 'jun', '5500', '600', 14),
    mes(7, 'jul', '0'),
    mes(8, 'ago', '0'),
    mes(9, 'sep', '0'),
    mes(10, 'oct', '0'),
    mes(11, 'nov', '0'),
    mes(12, 'dic', '0'),
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
      marcas: [
        { fecha: '2026-03-02', estado: 'PRESENTE' },
        { fecha: '2026-03-09', estado: 'AUSENTE' },
        { fecha: '2026-03-16', estado: 'PRESENTE' },
      ],
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

  it('renderiza 12 columnas con las 3 series y altura proporcional al monto', async () => {
    const { container } = renderReportes();
    await screen.findByText(`Ingresos ${ANIO}`);

    const columnas = container.querySelectorAll<HTMLElement>('.barchart__col');
    expect(columnas.length).toBe(12);
    // Cada mes dibuja ingresos, egresos y utilidad.
    expect(columnas[0].querySelectorAll('.barchart__bar').length).toBe(3);

    // El pico del año (jun, 5500 de ingresos) llega al 100% de la escala.
    const junio = columnas[5].querySelector<HTMLElement>('.barchart__bar--ingreso');
    expect(junio?.style.height).toBe('100%');
    // Su egreso (600) y su utilidad (4900) escalan contra el mismo máximo.
    const junioEgreso = columnas[5].querySelector<HTMLElement>('.barchart__bar--egreso');
    expect(junioEgreso?.style.height).toBe(`${(600 / 5500) * 100}%`);
    const junioUtil = columnas[5].querySelector<HTMLElement>('.barchart__bar--utilidad');
    expect(junioUtil?.style.height).toBe(`${(4900 / 5500) * 100}%`);

    // Mes sin movimiento: las 3 barras a 0% y con la clase placeholder.
    const enero = columnas[0].querySelectorAll<HTMLElement>('.barchart__bar');
    enero.forEach((b) => {
      expect(b.style.height).toBe('0%');
      expect(b.className).toContain('barchart__bar--empty');
    });
  });

  it('sin meses en pérdida, la línea de cero queda en el piso del gráfico', async () => {
    const { container } = renderReportes();
    await screen.findByText(`Ingresos ${ANIO}`);
    const cero = container.querySelector<HTMLElement>('.barchart__zero');
    expect(cero?.style.bottom).toBe('0%');
  });

  it('dibuja la utilidad negativa por debajo de la línea de cero', async () => {
    // Un solo mes: 100 de ingresos y 300 de egresos -> utilidad -200.
    ingresosMock.mockResolvedValue({
      ...INGRESOS,
      total: '100',
      total_egresos: '300',
      utilidad: '-200',
      meses: [mes(1, 'ene', '100', '300', 1), ...INGRESOS.meses.slice(1).map((m) => ({ ...m, monto: '0', egresos: '0', utilidad: '0', n_pagos: 0, n_egresos: 0 }))],
    });
    const { container } = renderReportes();
    await screen.findByText(`Ingresos ${ANIO}`);

    // Escala: max 300 (egresos), min -200 (utilidad) -> span 500, cero al 40%.
    const cero = container.querySelector<HTMLElement>('.barchart__zero');
    expect(cero?.style.bottom).toBe('40%');

    const enero = container.querySelectorAll<HTMLElement>('.barchart__col')[0];
    const utilidad = enero.querySelector<HTMLElement>('.barchart__bar--utilidad');
    // 200/500 = 40% de alto, arrancando 40% por debajo del cero -> bottom 0%.
    expect(utilidad?.style.height).toBe('40%');
    expect(utilidad?.style.bottom).toBe('0%');
  });

  it('muestra los totales del año de ingresos, egresos y utilidad', async () => {
    const { container } = renderReportes();
    await screen.findByText(`Ingresos ${ANIO}`);
    // Montos formateados por org (es-BO usa "12.400"; no comprobamos símbolo).
    expect(
      container.querySelector('.reportes__total-value--ingreso')?.textContent,
    ).toMatch(/12.?400/);
    expect(container.querySelector('.reportes__total-value--egreso')?.textContent).toMatch(
      /2.?400/,
    );
    expect(
      container.querySelector('.reportes__total-value--utilidad')?.textContent,
    ).toMatch(/10.?000/);
  });

  it('marca la utilidad anual negativa con el estilo de pérdida', async () => {
    ingresosMock.mockResolvedValue({ ...INGRESOS, utilidad: '-500' });
    const { container } = renderReportes();
    await screen.findByText(`Ingresos ${ANIO}`);
    expect(container.querySelector('.reportes__total-value--perdida')).not.toBeNull();
    expect(container.querySelector('.reportes__total-value--utilidad')).toBeNull();
  });

  it('recarga las finanzas al filtrar por sucursal', async () => {
    const user = userEvent.setup();
    renderReportes();
    await screen.findByText(`Ingresos ${ANIO}`);
    ingresosMock.mockClear();

    // El selector de sucursal del gráfico financiero (el primero de la página).
    const [sucursalFin] = screen.getAllByLabelText('Sucursal');
    await user.selectOptions(sucursalFin, 's1');
    await waitFor(() =>
      expect(ingresosMock).toHaveBeenCalledWith(ANIO, expect.anything(), 's1'),
    );
    // Al filtrar se avisa que los egresos a nivel org quedan fuera.
    expect(
      await screen.findByText(/no se incluyen los egresos registrados a nivel de/i),
    ).toBeInTheDocument();
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

  it('despliega las fechas de asistencia de un deportista', async () => {
    const user = userEvent.setup();
    renderReportes();
    const tabla = await screen.findByRole('table', { name: 'Asistencia por deportista' });
    const scoped = within(tabla);
    // Colapsado: no se ven las fechas todavía.
    expect(scoped.queryByText('Ausente')).not.toBeInTheDocument();

    await user.click(scoped.getByRole('button', { name: /Mateo Quispe Mamani/ }));

    // Desplegado: cada marca con su fecha y su estado.
    expect(scoped.getAllByText('Presente')).toHaveLength(2);
    expect(scoped.getByText('Ausente')).toBeInTheDocument();
  });

  it('vuelve a colapsar el detalle al pulsar de nuevo', async () => {
    const user = userEvent.setup();
    renderReportes();
    const tabla = await screen.findByRole('table', { name: 'Asistencia por deportista' });
    const scoped = within(tabla);
    const toggle = scoped.getByRole('button', { name: /Mateo Quispe Mamani/ });

    await user.click(toggle);
    expect(scoped.getByText('Ausente')).toBeInTheDocument();
    await user.click(toggle);
    expect(scoped.queryByText('Ausente')).not.toBeInTheDocument();
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
    await screen.findByText(`Ingresos ${ANIO}`);
    ingresosMock.mockClear();

    const select = screen.getByLabelText('Año');
    await user.selectOptions(select, String(ANIO - 1));
    await waitFor(() =>
      expect(ingresosMock).toHaveBeenCalledWith(ANIO - 1, expect.anything(), undefined),
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
