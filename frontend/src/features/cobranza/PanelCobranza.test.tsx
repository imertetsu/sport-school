import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import type { CuotasListResponse, PanelCobranza as PanelData } from '@/api/types';

// Mock del cliente API: los tests usan mocks, no la API real.
const panelMock = vi.fn();
const cuotasMock = vi.fn();
vi.mock('@/api/client', () => ({
  api: {
    panelCobranza: (...args: unknown[]) => panelMock(...args),
    cuotas: (...args: unknown[]) => cuotasMock(...args),
  },
  ApiError: class ApiError extends Error {},
}));

// Contexto de sucursal (Todas las sucursales).
vi.mock('@/components/shell/SucursalContext', () => ({
  useSucursales: () => ({
    sucursales: [],
    loading: false,
    error: null,
    selected: '',
    setSelected: vi.fn(),
  }),
}));

// El modal de pago tiene su propio fetch; lo stubeamos para aislar el panel.
vi.mock('./RegistrarPago', () => ({
  RegistrarPago: () => <div data-testid="registrar-pago-modal">modal</div>,
}));

import { PanelCobranza } from './PanelCobranza';

const PANEL: PanelData = {
  ingresos_mes: { monto: '28450' },
  alumnos_activos: { count: 142, sucursales: 2, disciplinas: 3 },
  cuotas_pendientes: { count: 23, monto: '5290' },
  cuotas_vencidas: { count: 7, monto: '1680' },
  credito_total: '0',
  morosidad: [
    {
      alumno_id: 'a1',
      nombre_completo: 'Mateo Quispe Mamani',
      categoria: 'Sub-14 Intermedio',
      monto: '250',
      dias_mora: 12,
    },
  ],
};

const CUOTAS: CuotasListResponse = {
  page: 1,
  page_size: 50,
  total: 2,
  items: [
    {
      id: 'q1',
      alumno: { id: 'a1', nombre_completo: 'Mateo Quispe Mamani' },
      sucursal: { nombre: 'Centro' },
      categoria: { nombre: 'Sub-14 Intermedio' },
      periodo_inicio: '2026-06-01',
      vence_el: '2026-06-30',
      monto: '250',
      monto_pagado: '0',
      saldo: '250',
      estado: 'VENCIDO',
      ultimo_metodo: null,
    },
    {
      id: 'q2',
      alumno: { id: 'a2', nombre_completo: 'Valentina Condori Huanca' },
      sucursal: { nombre: 'Cala Cala' },
      categoria: { nombre: 'Sub-10 Principiante' },
      periodo_inicio: '2026-06-01',
      vence_el: '2026-06-30',
      monto: '180',
      monto_pagado: '180',
      saldo: '0',
      estado: 'PAGADO',
      ultimo_metodo: 'QR',
    },
  ],
};

function renderPanel() {
  return render(
    <MemoryRouter>
      <PanelCobranza />
    </MemoryRouter>,
  );
}

describe('PanelCobranza', () => {
  beforeEach(() => {
    panelMock.mockReset();
    cuotasMock.mockReset();
    panelMock.mockResolvedValue(PANEL);
    cuotasMock.mockResolvedValue(CUOTAS);
  });
  afterEach(() => vi.clearAllMocks());

  it('muestra los 4 KPIs con datos del panel', async () => {
    renderPanel();
    expect(await screen.findByText('Ingresos del mes')).toBeInTheDocument();
    expect(screen.getByText('Alumnos activos')).toBeInTheDocument();
    expect(screen.getByText('Cuotas pendientes')).toBeInTheDocument();
    expect(screen.getByText('Cuotas vencidas')).toBeInTheDocument();
    // valores
    expect(await screen.findByText('142')).toBeInTheDocument();
    expect(screen.getByText('23')).toBeInTheDocument();
    expect(screen.getByText('7')).toBeInTheDocument();
    expect(screen.getByText('en 2 sucursales · 3 disciplinas')).toBeInTheDocument();
  });

  it('resalta en rojo la card de Cuotas vencidas', async () => {
    const { container } = renderPanel();
    await screen.findByText('Cuotas vencidas');
    expect(container.querySelector('.kpi-card--overdue')).not.toBeNull();
  });

  it('no muestra la KPI de crédito si credito_total es 0', async () => {
    renderPanel();
    await screen.findByText('Cuotas vencidas');
    expect(screen.queryByText('Crédito a favor')).not.toBeInTheDocument();
  });

  it('muestra la KPI "Crédito a favor" cuando hay crédito (Abonos)', async () => {
    panelMock.mockResolvedValue({ ...PANEL, credito_total: '320' });
    renderPanel();
    expect(await screen.findByText('Crédito a favor')).toBeInTheDocument();
  });

  it('renderiza la tabla de cuotas devueltas por la API mock', async () => {
    renderPanel();
    // El nombre aparece en la tabla y en morosidad: al menos una vez.
    await waitFor(() =>
      expect(screen.getAllByText('Mateo Quispe Mamani').length).toBeGreaterThan(0),
    );
    expect(screen.getByText('Valentina Condori Huanca')).toBeInTheDocument();
    expect(screen.getByText('Centro')).toBeInTheDocument();
    expect(screen.getByText('Cala Cala')).toBeInTheDocument();
    // método de la cuota pagada
    expect(screen.getByText('QR')).toBeInTheDocument();
  });

  it('lista las alertas de morosidad', async () => {
    const { container } = renderPanel();
    await screen.findByText('Alertas de morosidad');
    const moras = container.querySelector('.moras');
    expect(moras).not.toBeNull();
    expect(moras?.textContent).toContain('Mateo Quispe Mamani');
    expect(moras?.textContent).toContain('Sub-14 Intermedio');
    expect(moras?.textContent).toContain('12 días');
    expect(screen.getByText('Ver todos los vencidos →')).toBeInTheDocument();
  });

  it('filtra por estado al pulsar un chip', async () => {
    const user = userEvent.setup();
    renderPanel();
    await screen.findAllByText('Mateo Quispe Mamani');
    cuotasMock.mockClear();
    await user.click(screen.getByRole('button', { name: 'Vencido' }));
    await waitFor(() =>
      expect(cuotasMock).toHaveBeenCalledWith(
        expect.objectContaining({ estado: 'VENCIDO' }),
        expect.anything(),
      ),
    );
  });

  it('abre el modal de registrar pago', async () => {
    const user = userEvent.setup();
    renderPanel();
    await screen.findAllByText('Mateo Quispe Mamani');
    await user.click(screen.getAllByRole('button', { name: 'Registrar pago' })[0]);
    expect(screen.getByTestId('registrar-pago-modal')).toBeInTheDocument();
  });
});
