import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import type {
  DeportistaDetail,
  DisciplinaRef,
  Sucursal,
  TutorByCi,
} from '@/api/types';

// Mock del cliente API. La factory de vi.mock se iza, así que el ApiError falso
// (con status + getters como el real) se define DENTRO de la factory.
const sucursalesMock = vi.fn();
const categoriasMock = vi.fn();
const disciplinasCatalogoMock = vi.fn();
const crearDeportistaMock = vi.fn();
const deportistaPorCiMock = vi.fn();
const tutorPorCiMock = vi.fn();

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
      sucursales: (...args: unknown[]) => sucursalesMock(...args),
      categorias: (...args: unknown[]) => categoriasMock(...args),
      disciplinasCatalogo: (...args: unknown[]) => disciplinasCatalogoMock(...args),
      crearDeportista: (...args: unknown[]) => crearDeportistaMock(...args),
      deportistaPorCi: (...args: unknown[]) => deportistaPorCiMock(...args),
      tutorPorCi: (...args: unknown[]) => tutorPorCiMock(...args),
    },
    ApiError,
  };
});

// Mock del DocumentScanner: NO carga tesseract.js en el test; expone un botón que
// dispara onExtract con campos fijos para verificar el prefill por OCR.
const OCR_FIELDS = {
  numeroCi: '9123456',
  nombres: 'Mateo',
  apellidoPaterno: 'Quispe',
  apellidoMaterno: 'Mamani',
  fechaNacimiento: '2014-03-10',
};
vi.mock('@/components/ocr/DocumentScanner', () => ({
  DocumentScanner: ({ onExtract }: { onExtract?: (f: typeof OCR_FIELDS) => void }) => (
    <button type="button" onClick={() => onExtract?.(OCR_FIELDS)}>
      [mock] Escanear cédula
    </button>
  ),
}));

import { ApiError } from '@/api/client';
import { NuevoDeportista } from './NuevoDeportista';

const SUCURSALES: Sucursal[] = [
  { id: 's1', nombre: 'Centro', direccion: 'Av. Principal 123' },
];

const DISCIPLINAS: DisciplinaRef[] = [
  { id: 'd1', nombre: 'Fútbol' },
  { id: 'd2', nombre: 'Natación' },
];

const DEPORTISTA_RECUPERADO: DeportistaDetail = {
  id: 'dep-1',
  ap_paterno: 'Condori',
  ap_materno: 'Huanca',
  nombres: 'Valentina',
  nombre_completo: 'Valentina Condori Huanca',
  ci: '9876543',
  fecha_nac: '2012-06-01',
  edad: 13,
  disciplina: 'Natación',
  contacto_emergencia: 'Mamá 70000000',
  sucursal: { id: 's1', nombre: 'Centro' },
  categoria: null,
  inscripcion: null,
  tutores: [
    {
      id: 't1',
      nombres: 'Rosa Huanca',
      telefono: '71111111',
      ci: '5550000',
      parentesco: 'Madre',
      responsable_pago: true,
    },
  ],
  consentimiento: null,
  ficha_medica: null,
};

const TUTOR_RECUPERADO: TutorByCi = {
  id: 't9',
  nombres: 'Carlos Pérez',
  telefono: '72222222',
  ci: '4440000',
};

function renderForm() {
  render(
    <MemoryRouter>
      <NuevoDeportista />
    </MemoryRouter>,
  );
}

describe('NuevoDeportista — OCR + recuperar-por-CI + disciplina (S3)', () => {
  beforeEach(() => {
    sucursalesMock.mockReset();
    categoriasMock.mockReset();
    disciplinasCatalogoMock.mockReset();
    crearDeportistaMock.mockReset();
    deportistaPorCiMock.mockReset();
    tutorPorCiMock.mockReset();
    sucursalesMock.mockResolvedValue(SUCURSALES);
    categoriasMock.mockResolvedValue([]);
    disciplinasCatalogoMock.mockResolvedValue(DISCIPLINAS);
    // Default: el CI no existe (alta nueva). Cada test lo sobrescribe si hace falta.
    deportistaPorCiMock.mockRejectedValue(new ApiError(404, 'Deportista no encontrado', null));
    tutorPorCiMock.mockRejectedValue(new ApiError(404, 'Tutor no encontrado', null));
  });
  afterEach(() => vi.clearAllMocks());

  it('pre-rellena los campos del deportista con el OCR (mockeado)', async () => {
    const user = userEvent.setup();
    renderForm();
    await screen.findByText('Centro'); // catálogos cargados

    await user.click(screen.getByRole('button', { name: '[mock] Escanear cédula' }));

    expect((screen.getByLabelText(/Apellido paterno/) as HTMLInputElement).value).toBe(
      'Quispe',
    );
    expect((screen.getByLabelText(/Apellido materno/) as HTMLInputElement).value).toBe(
      'Mamani',
    );
    // [0] = deportista (el tutor también tiene "Nombres"/"CI").
    expect((screen.getAllByLabelText(/^Nombres/)[0] as HTMLInputElement).value).toBe('Mateo');
    expect((screen.getAllByLabelText(/^CI/)[0] as HTMLInputElement).value).toBe('9123456');
    expect((screen.getByLabelText(/Fecha de nacimiento/) as HTMLInputElement).value).toBe(
      '2014-03-10',
    );
    // El OCR dispara el recuperar-por-CI con el CI detectado.
    await waitFor(() => expect(deportistaPorCiMock).toHaveBeenCalledWith('9123456'));
  });

  it('recupera el registro anterior del deportista al ingresar un CI existente', async () => {
    const user = userEvent.setup();
    deportistaPorCiMock.mockResolvedValue(DEPORTISTA_RECUPERADO);
    renderForm();
    await screen.findByText('Centro');

    const ciInput = screen.getAllByLabelText(/^CI/)[0]; // [0] = deportista
    await user.type(ciInput, '9876543');
    await user.tab(); // onBlur dispara el lookup

    await waitFor(() => expect(deportistaPorCiMock).toHaveBeenCalledWith('9876543'));
    // Aviso de recuperación visible.
    expect(
      await screen.findByText(/Se recuperó el registro anterior del deportista/),
    ).toBeInTheDocument();
    // Los datos del registro anterior se cargaron en el form.
    expect((screen.getByLabelText(/Apellido paterno/) as HTMLInputElement).value).toBe(
      'Condori',
    );
    expect((screen.getAllByLabelText(/^Nombres/)[1] as HTMLInputElement).value).toBe(
      'Rosa Huanca',
    );
  });

  it('recupera el tutor por su CI y permite actualizar el teléfono', async () => {
    const user = userEvent.setup();
    tutorPorCiMock.mockResolvedValue(TUTOR_RECUPERADO);
    renderForm();
    await screen.findByText('Centro');

    // El CI del tutor es el segundo input "CI" ([0]=deportista, [1]=tutor).
    const tutorCi = screen.getAllByLabelText(/^CI/)[1];
    await user.type(tutorCi, '4440000');
    await user.tab();

    await waitFor(() => expect(tutorPorCiMock).toHaveBeenCalledWith('4440000'));
    expect(
      await screen.findByText(/Se recuperó el tutor\. Puedes actualizar su teléfono/),
    ).toBeInTheDocument();
    // Datos del tutor recuperado precargados.
    const tutorNombres = screen.getAllByLabelText(/^Nombres/)[1] as HTMLInputElement;
    expect(tutorNombres.value).toBe('Carlos Pérez');
    const tutorTel = screen.getByLabelText(/Teléfono/) as HTMLInputElement;
    expect(tutorTel.value).toBe('72222222');

    // El usuario actualiza el teléfono (se envía en el alta; el backend lo reaplica).
    await user.clear(tutorTel);
    await user.type(tutorTel, '79999999');
    expect(tutorTel.value).toBe('79999999');
  });

  it('el select de disciplina se puebla del catálogo y envía el nombre elegido', async () => {
    const user = userEvent.setup();
    crearDeportistaMock.mockResolvedValue({ id: 'dep-9' });
    renderForm();
    await screen.findByText('Centro');

    // Datos mínimos del deportista ([0] = deportista; el tutor comparte etiquetas).
    await user.type(screen.getByLabelText(/Apellido paterno/), 'Quispe');
    await user.type(screen.getAllByLabelText(/^Nombres/)[0], 'Mateo');
    await user.type(screen.getAllByLabelText(/^CI/)[0], '9123456');
    await user.type(screen.getByLabelText(/Fecha de nacimiento/), '2014-03-10');

    // El select de disciplina viene del catálogo (api.disciplinasCatalogo).
    const disciplinaSelect = await screen.findByLabelText(/Disciplina/);
    await user.selectOptions(disciplinaSelect, 'Fútbol');
    expect(disciplinasCatalogoMock).toHaveBeenCalled();

    await user.selectOptions(screen.getByLabelText(/Sucursal/), 's1');

    // Tutor mínimo + consentimiento.
    const tutorNombres = screen.getAllByLabelText(/^Nombres/)[1];
    await user.type(tutorNombres, 'Rosa');
    await user.click(screen.getByRole('checkbox', { name: /consentimiento/i }));

    await user.click(screen.getByRole('button', { name: 'Crear deportista' }));

    await waitFor(() => expect(crearDeportistaMock).toHaveBeenCalledTimes(1));
    const payload = crearDeportistaMock.mock.calls[0][0];
    // El contrato usa el string `disciplina` (no disciplina_id): se envía el NOMBRE.
    expect(payload.disciplina).toBe('Fútbol');
    expect(payload.sucursal_id).toBe('s1');
    expect(payload.tutores[0].nombres).toBe('Rosa');
    expect(payload.consentimiento).toEqual({ version_terminos: 'v1', canal: 'WEB' });
  });

  it('maneja el 409 (CI duplicado) del alta con un mensaje claro (sin crash)', async () => {
    const user = userEvent.setup();
    crearDeportistaMock.mockRejectedValue(
      new ApiError(409, 'Ya existe un deportista con ese CI en esta organización', null),
    );
    renderForm();
    await screen.findByText('Centro');

    await user.type(screen.getByLabelText(/Apellido paterno/), 'Quispe');
    await user.type(screen.getAllByLabelText(/^Nombres/)[0], 'Mateo');
    await user.type(screen.getAllByLabelText(/^CI/)[0], '9123456');
    await user.type(screen.getByLabelText(/Fecha de nacimiento/), '2014-03-10');
    await user.selectOptions(await screen.findByLabelText(/Disciplina/), 'Fútbol');
    await user.selectOptions(screen.getByLabelText(/Sucursal/), 's1');
    await user.type(screen.getAllByLabelText(/^Nombres/)[1], 'Rosa');
    await user.click(screen.getByRole('checkbox', { name: /consentimiento/i }));

    await user.click(screen.getByRole('button', { name: 'Crear deportista' }));

    await waitFor(() => expect(crearDeportistaMock).toHaveBeenCalledTimes(1));
    expect(
      await screen.findByText(/Ya hay un deportista registrado con ese CI/),
    ).toBeInTheDocument();
  });

  it('no envía si falta el consentimiento (obligatorio, RF-USR-04)', async () => {
    const user = userEvent.setup();
    renderForm();
    await screen.findByText('Centro');

    await user.type(screen.getByLabelText(/Apellido paterno/), 'Quispe');
    await user.type(screen.getAllByLabelText(/^Nombres/)[0], 'Mateo');
    await user.type(screen.getAllByLabelText(/^CI/)[0], '9123456');
    await user.type(screen.getByLabelText(/Fecha de nacimiento/), '2014-03-10');
    await user.selectOptions(await screen.findByLabelText(/Disciplina/), 'Fútbol');
    await user.selectOptions(screen.getByLabelText(/Sucursal/), 's1');
    await user.type(screen.getAllByLabelText(/^Nombres/)[1], 'Rosa');

    await user.click(screen.getByRole('button', { name: 'Crear deportista' }));
    expect(crearDeportistaMock).not.toHaveBeenCalled();
    expect(
      screen.getByText('El consentimiento del tutor es obligatorio.'),
    ).toBeInTheDocument();
  });
});
