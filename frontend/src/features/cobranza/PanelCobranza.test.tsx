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
  egresos_mes: { monto: '6450', efectivo: '5000', qr: '1450' },
  utilidad_mes: { monto: '22000', efectivo: '15000', qr: '7000' },
  por_sucursal: [
    {
      sucursal_id: 's1',
      nombre: 'Centro',
      ingresos: { monto: '18450', efectivo: '13000', qr: '5450' },
      egresos: { monto: '4000', efectivo: '3000', qr: '1000' },
      utilidad: { monto: '14450', efectivo: '10000', qr: '4450' },
    },
    {
      sucursal_id: 's2',
      nombre: 'Cala Cala',
      ingresos: { monto: '10000', efectivo: '7000', qr: '3000' },
      egresos: { monto: '2000', efectivo: '1550', qr: '450' },
      utilidad: { monto: '8000', efectivo: '5450', qr: '2550' },
    },
    // Gastos cargados sin sucursal: fila propia, cierra en pérdida.
    {
      sucursal_id: null,
      nombre: 'Sin sucursal (organización)',
      ingresos: { monto: '0', efectivo: '0', qr: '0' },
      egresos: { monto: '450', efectivo: '450', qr: '0' },
      utilidad: { monto: '-450', efectivo: '-450', qr: '0' },
    },
  ],
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

  it('muestra las KPIs de Egresos y Utilidad del mes con su desglose', async () => {
    const { container } = renderPanel();
    expect(await screen.findByText('Egresos del mes')).toBeInTheDocument();
    expect(screen.getByText('Utilidad del mes')).toBeInTheDocument();
    // Las 3 KPIs financieras (ingresos, egresos, utilidad) llevan desglose.
    expect(container.querySelectorAll('.kpi-metodo--efectivo')).toHaveLength(3);
    expect(container.querySelectorAll('.kpi-metodo--qr')).toHaveLength(3);
  });

  it('resalta la Utilidad del mes en rojo cuando el mes cierra en pérdida', async () => {
    panelMock.mockResolvedValue({
      ...PANEL,
      utilidad_mes: { monto: '-1200', efectivo: '-1200', qr: '0' },
      // Sin cuotas vencidas, para que la única card roja sea la de utilidad.
      cuotas_vencidas: { count: 0, monto: '0' },
    });
    const { container } = renderPanel();
    await screen.findByText('Utilidad del mes');
    const rojas = container.querySelectorAll('.kpi-card--overdue');
    // Cuotas vencidas (siempre roja) + Utilidad en pérdida.
    expect(rojas.length).toBe(2);
    expect(
      Array.from(rojas).some((c) => c.textContent?.includes('Utilidad del mes')),
    ).toBe(true);
  });

  it('renderiza el resumen del mes por sucursal con las 3 métricas', async () => {
    renderPanel();
    const tabla = await screen.findByRole('table', { name: 'Resumen del mes por sucursal' });
    const scoped = within(tabla);
    expect(scoped.getByText('Centro')).toBeInTheDocument();
    expect(scoped.getByText('Cala Cala')).toBeInTheDocument();
    // Los gastos sin sucursal tienen su propia fila (para que las filas sumen).
    expect(scoped.getByText('Sin sucursal (organización)')).toBeInTheDocument();
    expect(scoped.getAllByRole('columnheader').map((h) => h.textContent)).toEqual([
      'Sucursal',
      'Ingresos',
      'Egresos',
      'Utilidad',
    ]);
  });

  it('marca en rojo la utilidad negativa de una fila por sucursal', async () => {
    const { container } = renderPanel();
    await screen.findByRole('table', { name: 'Resumen del mes por sucursal' });
    // Solo la fila "Sin sucursal" cierra en pérdida (-450).
    const perdidas = container.querySelectorAll('.panel-fin__total--perdida');
    expect(perdidas.length).toBe(1);
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
    // Acotado a la tabla de cuotas: el resumen por sucursal repite los nombres.
    const cuotas = within(screen.getByRole('table', { name: 'Cuotas' }));
    expect(cuotas.getByText('Centro')).toBeInTheDocument();
    expect(cuotas.getByText('Cala Cala')).toBeInTheDocument();
    // método de la cuota pagada
    expect(cuotas.getByText('QR')).toBeInTheDocument();
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
