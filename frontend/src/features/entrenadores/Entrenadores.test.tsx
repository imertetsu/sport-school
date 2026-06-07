import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type {
  DisciplinaRef,
  EntrenadorOut,
  RecordatorioDeudoresResult,
  Sucursal,
} from '@/api/types';
import type { CedulaFields } from '@/components/ocr/parseCedula';

// Mock del cliente API: los tests usan mocks, no la API real. La factory de
// vi.mock se iza al tope; el ApiError falso (con status/isForbidden/isValidation,
// como el real) se define DENTRO de la factory y se recupera del módulo mockeado.
const listEntrenadoresMock = vi.fn();
const createEntrenadorMock = vi.fn();
const updateEntrenadorMock = vi.fn();
const enviarRecordatorioDeudoresMock = vi.fn();
const sucursalesMock = vi.fn();
const disciplinasCatalogoMock = vi.fn();

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
    api: {
      listEntrenadores: (...args: unknown[]) => listEntrenadoresMock(...args),
      createEntrenador: (...args: unknown[]) => createEntrenadorMock(...args),
      updateEntrenador: (...args: unknown[]) => updateEntrenadorMock(...args),
      enviarRecordatorioDeudores: (...args: unknown[]) =>
        enviarRecordatorioDeudoresMock(...args),
      sucursales: (...args: unknown[]) => sucursalesMock(...args),
      disciplinasCatalogo: (...args: unknown[]) => disciplinasCatalogoMock(...args),
    },
    ApiError,
  };
});

// DocumentScanner hace un dynamic import de tesseract.js (worker WASM): lo
// mockeamos por un botón que dispara onExtract con campos de prueba, para validar
// que el formulario prellena CI/nombres SIN cargar el worker real en jsdom.
let scanFields: CedulaFields = { numeroCi: '7654321', nombres: 'Coach OCR' };
vi.mock('@/components/ocr/DocumentScanner', () => ({
  DocumentScanner: ({
    onExtract,
    label,
  }: {
    onExtract?: (f: CedulaFields) => void;
    label?: string;
  }) => (
    <button type="button" onClick={() => onExtract?.(scanFields)}>
      {label ?? 'Escanear cédula'}
    </button>
  ),
}));

import { Entrenadores } from './Entrenadores';

const SUCURSALES: Sucursal[] = [
  { id: 's1', nombre: 'Centro', direccion: 'Av. Principal 123' },
  { id: 's2', nombre: 'Norte', direccion: '' },
];

const DISCIPLINAS: DisciplinaRef[] = [
  { id: 'd1', nombre: 'Fútbol' },
  { id: 'd2', nombre: 'Natación' },
];

const ENTRENADORES: EntrenadorOut[] = [
  {
    id: 'e1',
    usuario_id: 'u1',
    nombres: 'Carlos Pérez',
    email: 'carlos@escuela.com',
    ci: '1234567',
    especialidad: 'Fútbol',
    disciplinas: [{ id: 'd1', nombre: 'Fútbol' }],
    activo: true,
    telefono: '59170000000',
    sucursal_ids: ['s1'],
  },
  {
    id: 'e2',
    usuario_id: 'u2',
    nombres: 'Ana Gómez',
    email: 'ana@escuela.com',
    ci: null,
    especialidad: null,
    disciplinas: [],
    activo: true,
    telefono: null,
    sucursal_ids: ['s1', 's2'],
  },
];

describe('Entrenadores — alta/edición + resumen de deudores (ADMIN)', () => {
  beforeEach(() => {
    listEntrenadoresMock.mockReset();
    createEntrenadorMock.mockReset();
    updateEntrenadorMock.mockReset();
    enviarRecordatorioDeudoresMock.mockReset();
    sucursalesMock.mockReset();
    disciplinasCatalogoMock.mockReset();
    scanFields = { numeroCi: '7654321', nombres: 'Coach OCR' };
    listEntrenadoresMock.mockResolvedValue(ENTRENADORES);
    sucursalesMock.mockResolvedValue(SUCURSALES);
    disciplinasCatalogoMock.mockResolvedValue(DISCIPLINAS);
  });
  afterEach(() => vi.clearAllMocks());

  it('lista los entrenadores', async () => {
    render(<Entrenadores />);
    expect(await screen.findByText('Carlos Pérez')).toBeInTheDocument();
    expect(screen.getByText('Ana Gómez')).toBeInTheDocument();
  });

  it('alta: envía ci, disciplina_ids, telefono y sucursal_ids al cliente', async () => {
    const user = userEvent.setup();
    createEntrenadorMock.mockResolvedValue({
      ...ENTRENADORES[0],
      id: 'e9',
      nombres: 'Nuevo Coach',
      email: 'nuevo@escuela.com',
    });
    render(<Entrenadores />);
    await screen.findByText('Carlos Pérez');

    await user.click(screen.getByRole('button', { name: '+ Nuevo entrenador' }));
    const dialog = await screen.findByRole('dialog', { name: 'Nuevo entrenador' });

    await user.type(within(dialog).getByLabelText(/Nombres/), 'Nuevo Coach');
    await user.type(within(dialog).getByLabelText(/Email/), 'nuevo@escuela.com');
    await user.type(within(dialog).getByLabelText(/^CI/), '9988776');
    await user.type(within(dialog).getByLabelText(/Contraseña/), 'secreto123');
    await user.type(within(dialog).getByLabelText(/Teléfono/), '59171111111');

    // Multiselect de disciplinas (catálogo global S2): marca una.
    await user.click(within(dialog).getByRole('checkbox', { name: 'Natación' }));

    // Multiselect de sucursales (poblado con GET /sucursales): marca dos.
    await user.click(within(dialog).getByRole('checkbox', { name: 'Centro' }));
    await user.click(within(dialog).getByRole('checkbox', { name: 'Norte' }));

    await user.click(within(dialog).getByRole('button', { name: 'Crear entrenador' }));

    await waitFor(() =>
      expect(createEntrenadorMock).toHaveBeenCalledWith(
        expect.objectContaining({
          nombres: 'Nuevo Coach',
          email: 'nuevo@escuela.com',
          password: 'secreto123',
          ci: '9988776',
          disciplina_ids: ['d2'],
          telefono: '59171111111',
          sucursal_ids: ['s1', 's2'],
        }),
      ),
    );
  });

  it('alta: el escáner OCR prellena CI y nombres (editables)', async () => {
    const user = userEvent.setup();
    createEntrenadorMock.mockResolvedValue({
      ...ENTRENADORES[0],
      id: 'e9',
    });
    render(<Entrenadores />);
    await screen.findByText('Carlos Pérez');

    await user.click(screen.getByRole('button', { name: '+ Nuevo entrenador' }));
    const dialog = await screen.findByRole('dialog', { name: 'Nuevo entrenador' });

    // El DocumentScanner mockeado dispara onExtract con campos de prueba.
    await user.click(within(dialog).getByRole('button', { name: 'Escanear cédula' }));

    expect(within(dialog).getByLabelText(/^CI/)).toHaveValue('7654321');
    expect(within(dialog).getByLabelText(/Nombres/)).toHaveValue('Coach OCR');

    // Sigue editable a mano tras el escaneo.
    await user.clear(within(dialog).getByLabelText(/^CI/));
    await user.type(within(dialog).getByLabelText(/^CI/), '1112223');
    expect(within(dialog).getByLabelText(/^CI/)).toHaveValue('1112223');
  });

  it('alta: 409 con mención de CI marca el campo CI y guía a editar', async () => {
    const user = userEvent.setup();
    const { ApiError } = await import('@/api/client');
    createEntrenadorMock.mockRejectedValue(
      new ApiError(
        409,
        'Ya existe un entrenador con ese CI en tu organización',
        'Ya existe un entrenador con ese CI en tu organización',
      ),
    );
    render(<Entrenadores />);
    await screen.findByText('Carlos Pérez');

    await user.click(screen.getByRole('button', { name: '+ Nuevo entrenador' }));
    const dialog = await screen.findByRole('dialog', { name: 'Nuevo entrenador' });

    await user.type(within(dialog).getByLabelText(/Nombres/), 'Dup Coach');
    await user.type(within(dialog).getByLabelText(/Email/), 'dup@escuela.com');
    await user.type(within(dialog).getByLabelText(/^CI/), '1234567');
    await user.type(within(dialog).getByLabelText(/Contraseña/), 'secreto123');

    await user.click(within(dialog).getByRole('button', { name: 'Crear entrenador' }));

    expect(
      await within(dialog).findByText('Ya existe un entrenador con ese CI'),
    ).toBeInTheDocument();
    expect(within(dialog).getByText(/Edita el entrenador existente/i)).toBeInTheDocument();
  });

  it('edición: precarga sucursales y envía telefono + sucursal_ids (reemplaza el set)', async () => {
    const user = userEvent.setup();
    updateEntrenadorMock.mockResolvedValue(ENTRENADORES[1]);
    render(<Entrenadores />);
    await screen.findByText('Ana Gómez');

    // Edita a Ana (segunda fila): tiene s1 y s2 asignadas.
    await user.click(screen.getAllByRole('button', { name: 'Editar' })[1]);
    const dialog = await screen.findByRole('dialog', { name: 'Editar entrenador' });

    // Precarga: ambas sucursales marcadas; Ana no tiene disciplinas asignadas.
    expect(within(dialog).getByRole('checkbox', { name: 'Centro' })).toBeChecked();
    expect(within(dialog).getByRole('checkbox', { name: 'Norte' })).toBeChecked();
    expect(within(dialog).getByRole('checkbox', { name: 'Fútbol' })).not.toBeChecked();
    expect(within(dialog).getByRole('checkbox', { name: 'Natación' })).not.toBeChecked();

    // Desmarca Norte (el set resultante reemplaza al anterior), añade una
    // disciplina del catálogo y teléfono.
    await user.click(within(dialog).getByRole('checkbox', { name: 'Norte' }));
    await user.click(within(dialog).getByRole('checkbox', { name: 'Fútbol' }));
    await user.type(within(dialog).getByLabelText(/Teléfono/), '59172222222');

    await user.click(within(dialog).getByRole('button', { name: 'Guardar cambios' }));

    await waitFor(() =>
      expect(updateEntrenadorMock).toHaveBeenCalledWith(
        'e2',
        expect.objectContaining({
          telefono: '59172222222',
          disciplina_ids: ['d1'],
          sucursal_ids: ['s1'],
        }),
      ),
    );
  });

  it('edición: precarga las disciplinas asignadas (chips del catálogo)', async () => {
    const user = userEvent.setup();
    render(<Entrenadores />);
    await screen.findByText('Carlos Pérez');

    // Carlos (primera fila) tiene la disciplina Fútbol (d1) asignada.
    await user.click(screen.getAllByRole('button', { name: 'Editar' })[0]);
    const dialog = await screen.findByRole('dialog', { name: 'Editar entrenador' });

    expect(within(dialog).getByRole('checkbox', { name: 'Fútbol' })).toBeChecked();
    expect(within(dialog).getByRole('checkbox', { name: 'Natación' })).not.toBeChecked();
    // El CI también precarga.
    expect(within(dialog).getByLabelText(/^CI/)).toHaveValue('1234567');
  });

  it('lista: muestra los chips de disciplinas por nombre', async () => {
    render(<Entrenadores />);
    await screen.findByText('Carlos Pérez');
    // El chip de la disciplina del catálogo (objeto {id,nombre}) muestra el nombre.
    const chips = screen.getAllByText('Fútbol');
    expect(chips.length).toBeGreaterThan(0);
  });

  it('botón "Enviar resumen de deudores": llama al endpoint y renderiza el resumen', async () => {
    const user = userEvent.setup();
    const resultado: RecordatorioDeudoresResult = {
      entrenador_id: 'e1',
      periodo: 'MANUAL-20260607T120000',
      enviados: 1,
      sucursales: [
        {
          sucursal_id: 's1',
          sucursal_nombre: 'Centro',
          num_deudores: 3,
          monto_total: '450.00',
          estado: 'ENVIADO',
        },
        {
          sucursal_id: 's2',
          sucursal_nombre: 'Norte',
          num_deudores: 0,
          monto_total: '0',
          estado: 'SIN_DEUDORES',
        },
      ],
    };
    enviarRecordatorioDeudoresMock.mockResolvedValue(resultado);
    render(<Entrenadores />);
    await screen.findByText('Carlos Pérez');

    await user.click(
      screen.getAllByRole('button', { name: 'Enviar resumen de deudores' })[0],
    );

    await waitFor(() =>
      expect(enviarRecordatorioDeudoresMock).toHaveBeenCalledWith('e1'),
    );

    // Render del resumen: por sucursal, nº de deudores y estado.
    const dialog = await screen.findByRole('dialog', {
      name: 'Resumen de deudores enviado',
    });
    expect(within(dialog).getByText('Centro')).toBeInTheDocument();
    expect(within(dialog).getByText('Enviado')).toBeInTheDocument();
    expect(within(dialog).getByText(/3 deudores/)).toBeInTheDocument();
    expect(within(dialog).getByText('Norte')).toBeInTheDocument();
    expect(within(dialog).getByText('Sin deudores')).toBeInTheDocument();
  });

  it('entrenador sin teléfono: muestra el aviso claro cuando todas las sucursales fallan', async () => {
    const user = userEvent.setup();
    const resultado: RecordatorioDeudoresResult = {
      entrenador_id: 'e2',
      periodo: 'MANUAL-20260607T120100',
      enviados: 0,
      sucursales: [
        {
          sucursal_id: 's1',
          sucursal_nombre: 'Centro',
          num_deudores: 2,
          monto_total: '200.00',
          estado: 'FALLIDO',
        },
        {
          sucursal_id: 's2',
          sucursal_nombre: 'Norte',
          num_deudores: 1,
          monto_total: '100.00',
          estado: 'FALLIDO',
        },
      ],
    };
    enviarRecordatorioDeudoresMock.mockResolvedValue(resultado);
    render(<Entrenadores />);
    await screen.findByText('Ana Gómez');

    // Ana (segunda fila) no tiene teléfono.
    await user.click(
      screen.getAllByRole('button', { name: 'Enviar resumen de deudores' })[1],
    );

    const dialog = await screen.findByRole('dialog', {
      name: 'Resumen de deudores enviado',
    });
    expect(
      within(dialog).getByText(/no tiene teléfono registrado/i),
    ).toBeInTheDocument();
  });
});
