import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import type { CuotasListResponse, PanelCobranza as PanelData } from '@/api/types';

// Mock del cliente API: los tests usan mocks, no la API real.
const panelMock = vi.fn();
const cuotasMock = vi.fn();
const recordatorioMock = vi.fn();
const recordatorioMoraMock = vi.fn();
vi.mock('@/api/client', () => ({
  api: {
    panelCobranza: (...args: unknown[]) => panelMock(...args),
    cuotas: (...args: unknown[]) => cuotasMock(...args),
    enviarRecordatorio: (...args: unknown[]) => recordatorioMock(...args),
    enviarRecordatorioMora: (...args: unknown[]) => recordatorioMoraMock(...args),
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

// Rol de la vista. Por defecto ADMIN (ve la acción de recordatorio). Los tests
// que necesiten ENTRENADOR sobrescriben este valor.
let viewRoleMock: 'ADMIN' | 'ENTRENADOR' = 'ADMIN';
vi.mock('@/auth/useAuth', () => ({
  useAuth: () => ({ viewRole: viewRoleMock }),
}));

// El modal de pago tiene su propio fetch; lo stubeamos para aislar el panel.
vi.mock('./RegistrarPago', () => ({
  RegistrarPago: () => <div data-testid="registrar-pago-modal">modal</div>,
}));

import { PanelCobranza } from './PanelCobranza';

const PANEL: PanelData = {
  ingresos_mes: { monto: '28450', efectivo: '20000', qr: '8450' },
  deportistas_activos: { count: 142, sucursales: 2, disciplinas: 3 },
  cuotas_pendientes: { count: 23, monto: '5290' },
  cuotas_vencidas: { count: 7, monto: '1680' },
  credito_total: '0',
  morosidad: [
    {
      deportista_id: 'a1',
      nombre_completo: 'Mateo Quispe Mamani',
      categoria: 'Sub-14 Intermedio',
      monto: '250',
      dias_mora: 12,
      meses: ['MAYO', 'JUNIO'],
      vence_mas_antiguo: '2026-05-30',
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
      deportista: { id: 'a1', nombre_completo: 'Mateo Quispe Mamani' },
      disciplina: 'Futsal',
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
      deportista: { id: 'a2', nombre_completo: 'Valentina Condori Huanca' },
      disciplina: 'Voleibol',
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
    recordatorioMock.mockReset();
    viewRoleMock = 'ADMIN';
    panelMock.mockResolvedValue(PANEL);
    cuotasMock.mockResolvedValue(CUOTAS);
  });
  afterEach(() => vi.clearAllMocks());

  it('muestra los 4 KPIs con datos del panel', async () => {
    renderPanel();
    expect(await screen.findByText('Ingresos del mes')).toBeInTheDocument();
    expect(screen.getByText('Deportistas activos')).toBeInTheDocument();
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

  it('ADMIN ve "Enviar WhatsApp" solo en cuotas no pagadas', async () => {
    renderPanel();
    await screen.findAllByText('Mateo Quispe Mamani');
    // q1 (VENCIDO) tiene el botón; q2 (PAGADO) no -> exactamente 1 EN LA TABLA
    // (la tarjeta de morosidad tiene el suyo aparte; por eso acotamos a la tabla).
    const tabla = within(screen.getByRole('table', { name: 'Cuotas' }));
    expect(
      tabla.getAllByRole('button', { name: 'Enviar WhatsApp' }),
    ).toHaveLength(1);
  });

  it('ENTRENADOR no ve la acción de recordatorio en la tabla', async () => {
    viewRoleMock = 'ENTRENADOR';
    renderPanel();
    await screen.findAllByText('Mateo Quispe Mamani');
    const tabla = within(screen.getByRole('table', { name: 'Cuotas' }));
    expect(
      tabla.queryByRole('button', { name: 'Enviar WhatsApp' }),
    ).not.toBeInTheDocument();
  });

  it('envía el recordatorio y muestra el aviso de éxito (motivo ok)', async () => {
    recordatorioMock.mockResolvedValue({
      enviado: true,
      cuota_id: 'q1',
      provider_message_id: 'wamid.1',
      motivo: 'ok',
    });
    const user = userEvent.setup();
    renderPanel();
    await screen.findAllByText('Mateo Quispe Mamani');
    const tabla = within(screen.getByRole('table', { name: 'Cuotas' }));
    await user.click(tabla.getByRole('button', { name: 'Enviar WhatsApp' }));
    await waitFor(() => expect(recordatorioMock).toHaveBeenCalledWith('q1'));
    expect(await screen.findByText(/Recordatorio enviado\./)).toBeInTheDocument();
  });

  it('refleja motivo "sin_telefono" como advertencia', async () => {
    recordatorioMock.mockResolvedValue({
      enviado: false,
      cuota_id: 'q1',
      provider_message_id: null,
      motivo: 'sin_telefono',
    });
    const user = userEvent.setup();
    renderPanel();
    await screen.findAllByText('Mateo Quispe Mamani');
    const tabla = within(screen.getByRole('table', { name: 'Cuotas' }));
    await user.click(tabla.getByRole('button', { name: 'Enviar WhatsApp' }));
    expect(
      await screen.findByText(/El tutor no tiene teléfono registrado\./),
    ).toBeInTheDocument();
  });

  it('refleja motivo "ya_enviado" como info', async () => {
    recordatorioMock.mockResolvedValue({
      enviado: false,
      cuota_id: 'q1',
      provider_message_id: null,
      motivo: 'ya_enviado',
    });
    const user = userEvent.setup();
    renderPanel();
    await screen.findAllByText('Mateo Quispe Mamani');
    const tabla = within(screen.getByRole('table', { name: 'Cuotas' }));
    await user.click(tabla.getByRole('button', { name: 'Enviar WhatsApp' }));
    expect(
      await screen.findByText(/Ya se había enviado este recordatorio\./),
    ).toBeInTheDocument();
  });
});
