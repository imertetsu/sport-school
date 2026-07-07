import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import type { CuotaListItem, PagoOut } from '@/api/types';

// Mock del cliente API: solo nos interesa el camino de pago en efectivo.
const cuotasMock = vi.fn();
const pagoEfectivoMock = vi.fn();
const pagoQrMock = vi.fn();
const pagoMock = vi.fn();
const simularMock = vi.fn();

vi.mock('@/api/client', () => ({
  api: {
    cuotas: (...a: unknown[]) => cuotasMock(...a),
    pagoEfectivo: (...a: unknown[]) => pagoEfectivoMock(...a),
    pagoQr: (...a: unknown[]) => pagoQrMock(...a),
    pago: (...a: unknown[]) => pagoMock(...a),
    simularConfirmacionQr: (...a: unknown[]) => simularMock(...a),
    // El comprobante (tras registrar) consulta estos al montar; no nos interesan
    // en estos tests, solo que existan para no romper el render.
    whatsappEstado: vi.fn(() => Promise.resolve({ estado: 'no_vinculado' })),
    deportista: vi.fn(() => Promise.resolve({ tutores: [] })),
    enviarComprobanteWhatsapp: vi.fn(),
    comprobantePdfUrl: vi.fn(() => Promise.resolve('#')),
  },
  ApiError: class ApiError extends Error {},
  comprobantePdfUrl: () => '#',
}));

// La escuela (nombre para el mensaje de WhatsApp) viene de useAuth; el componente
// solo lee `org`. Mockeamos el hook para no necesitar <AuthProvider> en el test.
vi.mock('@/auth/useAuth', () => ({
  useAuth: () => ({ org: { id: 'o1', nombre: 'Escuela Test' } }),
}));

import { RegistrarPago } from './RegistrarPago';

const CUOTA: CuotaListItem = {
  id: 'c1',
  deportista: { id: 'd1', nombre_completo: 'ANA PEREZ' },
  sucursal: null,
  categoria: null,
  periodo_inicio: '2026-06-01',
  vence_el: '2026-07-01',
  monto: '200.00',
  monto_pagado: '0.00',
  saldo: '200.00',
  estado: 'PENDIENTE',
  ultimo_metodo: null,
};

const PAGO_OK: PagoOut = {
  id: 'p1',
  estado: 'CONFIRMADO',
  metodo: 'EFECTIVO',
  monto: '250.00',
  comprobante_url: null,
  credito_generado: '50.00',
  credito_aplicado: '0.00',
  cuotas_aplicadas: [],
  numero_recibo: 'REC-000001',
};

describe('RegistrarPago — aviso de sobrepago', () => {
  beforeEach(() => {
    cuotasMock.mockReset();
    pagoEfectivoMock.mockReset();
    cuotasMock.mockResolvedValue({ items: [CUOTA], total: 1, page: 1, page_size: 50 });
    pagoEfectivoMock.mockResolvedValue(PAGO_OK);
  });
  afterEach(() => vi.clearAllMocks());

  it('al pagar de más pide confirmación y NO registra hasta confirmar', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <RegistrarPago cuotaInicial={CUOTA} onClose={() => {}} />
      </MemoryRouter>,
    );

    const monto = await screen.findByLabelText(/Monto recibido/);
    await user.type(monto, '250'); // saldo total = 200 → 50 de más

    // 1er click: NO registra; aparece el aviso de sobrepago.
    await user.click(screen.getByRole('button', { name: /Confirmar pago/ }));
    expect(pagoEfectivoMock).not.toHaveBeenCalled();
    expect(screen.getByText(/de más/)).toBeInTheDocument();

    // Confirmar de todas formas → recién ahí registra.
    await user.click(screen.getByRole('button', { name: /Registrar de todas formas/ }));
    await waitFor(() => expect(pagoEfectivoMock).toHaveBeenCalledTimes(1));
    expect(pagoEfectivoMock.mock.calls[0][0]).toMatchObject({ monto_recibido: '250' });
  });

  it('"Revisar monto" cancela el aviso sin registrar', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <RegistrarPago cuotaInicial={CUOTA} onClose={() => {}} />
      </MemoryRouter>,
    );
    const monto = await screen.findByLabelText(/Monto recibido/);
    await user.type(monto, '250');
    await user.click(screen.getByRole('button', { name: /Confirmar pago/ }));
    await user.click(screen.getByRole('button', { name: /Revisar monto/ }));
    expect(pagoEfectivoMock).not.toHaveBeenCalled();
    // Vuelve el botón normal.
    expect(
      screen.getByRole('button', { name: /Confirmar pago/ }),
    ).toBeInTheDocument();
  });

  it('si paga el monto exacto (vacío = total) registra directo, sin aviso', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <RegistrarPago cuotaInicial={CUOTA} onClose={() => {}} />
      </MemoryRouter>,
    );
    await screen.findByLabelText(/Monto recibido/);
    await user.click(screen.getByRole('button', { name: /Confirmar pago/ }));
    await waitFor(() => expect(pagoEfectivoMock).toHaveBeenCalledTimes(1));
    expect(screen.queryByText(/de más/)).not.toBeInTheDocument();
  });

  it('envía el método (QR) y la fecha de pago en el body', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <RegistrarPago cuotaInicial={CUOTA} onClose={() => {}} />
      </MemoryRouter>,
    );
    await screen.findByLabelText(/Monto recibido/);
    // Selector de método: cambiar a QR.
    await user.click(screen.getByRole('radio', { name: 'QR' }));
    await user.click(screen.getByRole('button', { name: /Confirmar pago/ }));
    await waitFor(() => expect(pagoEfectivoMock).toHaveBeenCalledTimes(1));
    const body = pagoEfectivoMock.mock.calls[0][0];
    expect(body.metodo).toBe('QR');
    expect(body.fecha_pago).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});
