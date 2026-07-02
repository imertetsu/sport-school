import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import type { PagoListItem, PagosListResponse } from '@/api/types';

// Mock del cliente API (mismo patrón que NuevoDeportista.test.tsx): la factory se
// iza, así que el ApiError falso (con status + getters como el real) se define
// DENTRO de la factory. Pagos.tsx y AnularPagoModal.tsx comparten este mock.
const listarPagosMock = vi.fn();
const anularPagoMock = vi.fn();

vi.mock('@/api/client', () => {
  class ApiError extends Error {
    status: number;
    detail: unknown;
    fieldErrors: { loc: (string | number)[]; msg: string }[];
    constructor(
      status: number,
      message: string,
      detail: unknown = null,
      fieldErrors: { loc: (string | number)[]; msg: string }[] = [],
    ) {
      super(message);
      this.status = status;
      this.detail = detail;
      this.fieldErrors = fieldErrors;
    }
    get isForbidden() {
      return this.status === 403;
    }
    get isValidation() {
      return this.status === 422;
    }
    get isConflict() {
      return this.status === 409;
    }
    get isNotFound() {
      return this.status === 404;
    }
  }
  return {
    api: {
      listarPagos: (...args: unknown[]) => listarPagosMock(...args),
      anularPago: (...args: unknown[]) => anularPagoMock(...args),
    },
    ApiError,
  };
});

import { ApiError } from '@/api/client';
import { Pagos } from './Pagos';

const EFECTIVO_CONFIRMADO: PagoListItem = {
  id: 'p1',
  fecha: '2026-06-20T10:00:00Z',
  metodo: 'EFECTIVO',
  estado: 'CONFIRMADO',
  monto: '250',
  deportista_nombre: 'MATEO QUISPE MAMANI',
  numero_recibo: 'REC-000123',
  anulable: true,
  motivo_anulacion: null,
  anulado_en: null,
  cuotas: [],
};

const QR_CONFIRMADO: PagoListItem = {
  id: 'p2',
  fecha: '2026-06-19T09:00:00Z',
  metodo: 'QR',
  estado: 'CONFIRMADO',
  monto: '180',
  deportista_nombre: 'VALENTINA CONDORI HUANCA',
  numero_recibo: 'REC-000122',
  anulable: false,
  motivo_anulacion: null,
  anulado_en: null,
  cuotas: [],
};

const YA_ANULADO: PagoListItem = {
  id: 'p3',
  fecha: '2026-06-18T08:00:00Z',
  metodo: 'EFECTIVO',
  estado: 'ANULADO',
  monto: '300',
  deportista_nombre: 'SOFIA MENDOZA ROJAS',
  numero_recibo: 'REC-000121',
  anulable: false,
  motivo_anulacion: 'Monto equivocado',
  anulado_en: '2026-06-18T12:00:00Z',
  cuotas: [],
};

function pagina(items: PagoListItem[]): PagosListResponse {
  return { items, total: items.length, page: 1, page_size: 20 };
}

function renderPagos() {
  return render(
    <MemoryRouter>
      <Pagos />
    </MemoryRouter>,
  );
}

describe('Pagos (lista + anular)', () => {
  beforeEach(() => {
    listarPagosMock.mockReset();
    anularPagoMock.mockReset();
    listarPagosMock.mockResolvedValue(
      pagina([EFECTIVO_CONFIRMADO, QR_CONFIRMADO, YA_ANULADO]),
    );
  });
  afterEach(() => vi.clearAllMocks());

  it('renderiza la lista de pagos con sus columnas', async () => {
    renderPagos();
    expect(await screen.findByText('MATEO QUISPE MAMANI')).toBeInTheDocument();
    expect(screen.getByText('VALENTINA CONDORI HUANCA')).toBeInTheDocument();
    expect(screen.getByText('SOFIA MENDOZA ROJAS')).toBeInTheDocument();
    expect(screen.getByText('REC-000123')).toBeInTheDocument();
    // Estado del pago ANULADO muestra el badge + el motivo.
    expect(screen.getByText('Anulado')).toBeInTheDocument();
    expect(screen.getByText('Monto equivocado')).toBeInTheDocument();
  });

  it('el botón "Anular" aparece solo en pagos anulables', async () => {
    renderPagos();
    await screen.findByText('MATEO QUISPE MAMANI');
    // Solo el pago efectivo CONFIRMADO (anulable) tiene botón "Anular": uno solo.
    const botones = screen.getAllByRole('button', { name: 'Anular' });
    expect(botones).toHaveLength(1);
  });

  it('el modal exige motivo: no llama al backend si está vacío', async () => {
    const user = userEvent.setup();
    renderPagos();
    await screen.findByText('MATEO QUISPE MAMANI');

    await user.click(screen.getByRole('button', { name: 'Anular' }));
    const dialog = await screen.findByRole('dialog', { name: 'Anular pago' });

    // Confirmar sin motivo -> error de validación local, sin llamada al backend.
    await user.click(within(dialog).getByRole('button', { name: 'Anular pago' }));
    expect(await screen.findByText('Indica el motivo de la anulación.')).toBeInTheDocument();
    expect(anularPagoMock).not.toHaveBeenCalled();
  });

  it('al confirmar con motivo llama anularPago(id, motivo) y refresca la lista', async () => {
    const user = userEvent.setup();
    anularPagoMock.mockResolvedValue({
      id: 'p1',
      estado: 'ANULADO',
      motivo_anulacion: 'Doble registro',
      anulado_en: '2026-06-21T10:00:00Z',
      credito_revertido: '0',
      cuotas_revertidas: [],
    });
    renderPagos();
    await screen.findByText('MATEO QUISPE MAMANI');

    await user.click(screen.getByRole('button', { name: 'Anular' }));
    const dialog = await screen.findByRole('dialog', { name: 'Anular pago' });

    await user.type(
      within(dialog).getByLabelText(/Motivo de la anulación/i),
      'Doble registro',
    );
    await user.click(within(dialog).getByRole('button', { name: 'Anular pago' }));

    await waitFor(() => expect(anularPagoMock).toHaveBeenCalledWith('p1', 'Doble registro'));
    // Tras anular se refresca la lista (segunda llamada a listarPagos).
    await waitFor(() => expect(listarPagosMock).toHaveBeenCalledTimes(2));
    // El modal se cierra.
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: 'Anular pago' })).not.toBeInTheDocument(),
    );
  });

  it('un 409 (crédito consumido) muestra el mensaje sin romper', async () => {
    const user = userEvent.setup();
    anularPagoMock.mockRejectedValue(new ApiError(409, 'credito_consumido', null));
    renderPagos();
    await screen.findByText('MATEO QUISPE MAMANI');

    await user.click(screen.getByRole('button', { name: 'Anular' }));
    const dialog = await screen.findByRole('dialog', { name: 'Anular pago' });

    await user.type(
      within(dialog).getByLabelText(/Motivo de la anulación/i),
      'Error de caja',
    );
    await user.click(within(dialog).getByRole('button', { name: 'Anular pago' }));

    expect(await within(dialog).findByRole('alert')).toHaveTextContent(
      /saldo a favor.*ya fue usado/i,
    );
    // El modal sigue abierto (no se cierra ante el error) y la lista NO se refresca.
    expect(screen.getByRole('dialog', { name: 'Anular pago' })).toBeInTheDocument();
    expect(listarPagosMock).toHaveBeenCalledTimes(1);
  });
});
