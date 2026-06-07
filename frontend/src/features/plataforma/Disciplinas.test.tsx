import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { Disciplina } from '@/api/types';

// Mock del cliente de plataforma (platformApi). La factory de vi.mock se iza al
// tope, así que los mocks de cada método se definen como vars-hoisted y se
// recuperan en el cuerpo del test. ApiError falso (con status/isValidation) para
// construir errores 409/422 igual que los tests existentes.
const disciplinasMock = vi.fn();
const crearDisciplinaMock = vi.fn();
const actualizarDisciplinaMock = vi.fn();

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
  }
  return {
    platformApi: {
      disciplinas: (...args: unknown[]) => disciplinasMock(...args),
      crearDisciplina: (...args: unknown[]) => crearDisciplinaMock(...args),
      actualizarDisciplina: (...args: unknown[]) => actualizarDisciplinaMock(...args),
    },
    ApiError,
  };
});

import { Disciplinas } from './Disciplinas';

const DISCIPLINAS: Disciplina[] = [
  { id: 'd1', nombre: 'Vóleibol', activo: true, created_at: '2026-01-10T12:00:00Z' },
  { id: 'd2', nombre: 'Fútbol', activo: false, created_at: '2026-01-11T12:00:00Z' },
];

describe('Disciplinas — consola de plataforma (SUPERADMIN)', () => {
  beforeEach(() => {
    disciplinasMock.mockReset();
    crearDisciplinaMock.mockReset();
    actualizarDisciplinaMock.mockReset();
    disciplinasMock.mockResolvedValue(DISCIPLINAS);
  });
  afterEach(() => vi.clearAllMocks());

  it('lista las disciplinas del catálogo (activas e inactivas)', async () => {
    render(<Disciplinas />);
    expect(await screen.findByText('Vóleibol')).toBeInTheDocument();
    expect(screen.getByText('Fútbol')).toBeInTheDocument();
    // El estado se refleja por badge: una activa, una inactiva.
    expect(screen.getByText('Activa')).toBeInTheDocument();
    expect(screen.getByText('Inactiva')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: '+ Crear disciplina' }),
    ).toBeInTheDocument();
  });

  it('alta: envía el nombre a platformApi.crearDisciplina y recarga', async () => {
    const user = userEvent.setup();
    crearDisciplinaMock.mockResolvedValue({
      id: 'd3',
      nombre: 'Básquet',
      activo: true,
      created_at: '2026-01-12T12:00:00Z',
    });
    render(<Disciplinas />);
    await screen.findByText('Vóleibol');

    await user.click(screen.getByRole('button', { name: '+ Crear disciplina' }));
    const dialog = await screen.findByRole('dialog', { name: 'Crear disciplina' });
    await user.type(within(dialog).getByLabelText(/Nombre/), 'Básquet');
    await user.click(within(dialog).getByRole('button', { name: 'Crear disciplina' }));

    await waitFor(() =>
      expect(crearDisciplinaMock).toHaveBeenCalledWith({ nombre: 'Básquet' }),
    );
    // Tras crear, recarga la lista (disciplinas() se llama de nuevo).
    await waitFor(() => expect(disciplinasMock).toHaveBeenCalledTimes(2));
  });

  it('retirar: hace soft-delete vía PUT activo=false', async () => {
    const user = userEvent.setup();
    actualizarDisciplinaMock.mockResolvedValue({
      id: 'd1',
      nombre: 'Vóleibol',
      activo: false,
      created_at: '2026-01-10T12:00:00Z',
    });
    render(<Disciplinas />);
    await screen.findByText('Vóleibol');

    // La fila activa ("Vóleibol") ofrece "Retirar"; la inactiva, "Reactivar".
    await user.click(screen.getByRole('button', { name: 'Retirar' }));

    await waitFor(() =>
      expect(actualizarDisciplinaMock).toHaveBeenCalledWith('d1', { activo: false }),
    );
  });
});
