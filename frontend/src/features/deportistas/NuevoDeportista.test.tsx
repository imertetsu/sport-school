import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
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
const deportistaMock = vi.fn();
const actualizarDeportistaMock = vi.fn();

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
      deportista: (...args: unknown[]) => deportistaMock(...args),
      actualizarDeportista: (...args: unknown[]) => actualizarDeportistaMock(...args),
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
  // FK canónico (S3): el backend lo expone para precargar el select al recuperar.
  disciplina_id: 'd2',
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
  activo: true,
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

// Monta el formulario en modo EDICIÓN (ruta con :id). El destino de navegación
// tras guardar (/deportistas/:id) se captura con una ruta espía simple.
function renderEdit(depId = 'dep-1') {
  render(
    <MemoryRouter initialEntries={[`/deportistas/${depId}/editar`]}>
      <Routes>
        <Route path="/deportistas/:id/editar" element={<NuevoDeportista />} />
        <Route path="/deportistas/:id" element={<div>PERFIL {depId}</div>} />
      </Routes>
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
    deportistaMock.mockReset();
    actualizarDeportistaMock.mockReset();
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
    // El select de disciplina se precarga con el FK canónico devuelto (disciplina_id).
    const disciplinaSelect = screen.getByLabelText(/Disciplina/) as HTMLSelectElement;
    expect(disciplinaSelect.value).toBe('d2');
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

  it('el select de disciplina se puebla del catálogo y envía el FK disciplina_id', async () => {
    const user = userEvent.setup();
    crearDeportistaMock.mockResolvedValue({ id: 'dep-9' });
    renderForm();
    await screen.findByText('Centro');

    // Datos mínimos del deportista ([0] = deportista; el tutor comparte etiquetas).
    await user.type(screen.getByLabelText(/Apellido paterno/), 'Quispe');
    await user.type(screen.getAllByLabelText(/^Nombres/)[0], 'Mateo');
    await user.type(screen.getAllByLabelText(/^CI/)[0], '9123456');
    await user.type(screen.getByLabelText(/Fecha de nacimiento/), '2014-03-10');

    // El select de disciplina viene del catálogo (api.disciplinasCatalogo); cada
    // opción usa el id (FK canónico) como value.
    const disciplinaSelect = await screen.findByLabelText(/Disciplina/);
    await user.selectOptions(disciplinaSelect, 'd1');
    expect(disciplinasCatalogoMock).toHaveBeenCalled();

    await user.selectOptions(screen.getByLabelText(/Sucursal/), 's1');

    // Tutor mínimo + consentimiento.
    const tutorNombres = screen.getAllByLabelText(/^Nombres/)[1];
    await user.type(tutorNombres, 'Rosa');
    await user.click(screen.getByRole('checkbox', { name: /consentimiento/i }));

    // Inscripción (cobro): obligatoria desde el formulario.
    await user.type(screen.getByLabelText(/Cuota mensual/), '150');
    await user.type(screen.getByLabelText(/Fecha de inscripción/), '2024-01-15');

    await user.click(screen.getByRole('button', { name: 'Crear deportista' }));

    await waitFor(() => expect(crearDeportistaMock).toHaveBeenCalledTimes(1));
    const payload = crearDeportistaMock.mock.calls[0][0];
    // El contrato canónico (S3) envía el FK `disciplina_id` (no el nombre legacy).
    expect(payload.disciplina_id).toBe('d1');
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
    await user.selectOptions(await screen.findByLabelText(/Disciplina/), 'd1');
    await user.selectOptions(screen.getByLabelText(/Sucursal/), 's1');
    await user.type(screen.getAllByLabelText(/^Nombres/)[1], 'Rosa');
    await user.click(screen.getByRole('checkbox', { name: /consentimiento/i }));
    await user.type(screen.getByLabelText(/Cuota mensual/), '150');
    await user.type(screen.getByLabelText(/Fecha de inscripción/), '2024-01-15');

    await user.click(screen.getByRole('button', { name: 'Crear deportista' }));

    await waitFor(() => expect(crearDeportistaMock).toHaveBeenCalledTimes(1));
    expect(
      await screen.findByText(/Ya hay un deportista registrado con ese CI/),
    ).toBeInTheDocument();
  });

  it('no envía si falta el CI del deportista (obligatorio) y muestra el error', async () => {
    const user = userEvent.setup();
    renderForm();
    await screen.findByText('Centro');

    // Todo lo demás válido, pero SIN CI del deportista.
    await user.type(screen.getByLabelText(/Apellido paterno/), 'Quispe');
    await user.type(screen.getAllByLabelText(/^Nombres/)[0], 'Mateo');
    await user.type(screen.getByLabelText(/Fecha de nacimiento/), '2014-03-10');
    await user.selectOptions(await screen.findByLabelText(/Disciplina/), 'd1');
    await user.selectOptions(screen.getByLabelText(/Sucursal/), 's1');
    await user.type(screen.getAllByLabelText(/^Nombres/)[1], 'Rosa');
    await user.click(screen.getByRole('checkbox', { name: /consentimiento/i }));

    await user.click(screen.getByRole('button', { name: 'Crear deportista' }));

    expect(crearDeportistaMock).not.toHaveBeenCalled();
    expect(
      screen.getByText('El CI del deportista es obligatorio.'),
    ).toBeInTheDocument();
  });

  it('envía cuando el CI del deportista está presente (CI de tutor opcional)', async () => {
    const user = userEvent.setup();
    crearDeportistaMock.mockResolvedValue({ id: 'dep-7' });
    renderForm();
    await screen.findByText('Centro');

    await user.type(screen.getByLabelText(/Apellido paterno/), 'Quispe');
    await user.type(screen.getAllByLabelText(/^Nombres/)[0], 'Mateo');
    await user.type(screen.getAllByLabelText(/^CI/)[0], '9123456');
    await user.type(screen.getByLabelText(/Fecha de nacimiento/), '2014-03-10');
    await user.selectOptions(await screen.findByLabelText(/Disciplina/), 'd1');
    await user.selectOptions(screen.getByLabelText(/Sucursal/), 's1');
    // Tutor con nombre pero SIN CI (opcional): no debe bloquear el envío.
    await user.type(screen.getAllByLabelText(/^Nombres/)[1], 'Rosa');
    await user.click(screen.getByRole('checkbox', { name: /consentimiento/i }));
    await user.type(screen.getByLabelText(/Cuota mensual/), '150');
    await user.type(screen.getByLabelText(/Fecha de inscripción/), '2024-01-15');

    await user.click(screen.getByRole('button', { name: 'Crear deportista' }));

    await waitFor(() => expect(crearDeportistaMock).toHaveBeenCalledTimes(1));
    const payload = crearDeportistaMock.mock.calls[0][0];
    expect(payload.ci).toBe('9123456');
    expect(payload.tutores[0].nombres).toBe('Rosa');
    // El CI del tutor quedó vacío (opcional) y no impidió el envío.
    expect(payload.tutores[0].ci).toBe('');
  });

  it('no envía si falta el consentimiento (obligatorio, RF-USR-04)', async () => {
    const user = userEvent.setup();
    renderForm();
    await screen.findByText('Centro');

    await user.type(screen.getByLabelText(/Apellido paterno/), 'Quispe');
    await user.type(screen.getAllByLabelText(/^Nombres/)[0], 'Mateo');
    await user.type(screen.getAllByLabelText(/^CI/)[0], '9123456');
    await user.type(screen.getByLabelText(/Fecha de nacimiento/), '2014-03-10');
    await user.selectOptions(await screen.findByLabelText(/Disciplina/), 'd1');
    await user.selectOptions(screen.getByLabelText(/Sucursal/), 's1');
    await user.type(screen.getAllByLabelText(/^Nombres/)[1], 'Rosa');

    await user.click(screen.getByRole('button', { name: 'Crear deportista' }));
    expect(crearDeportistaMock).not.toHaveBeenCalled();
    expect(
      screen.getByText('El consentimiento del tutor es obligatorio.'),
    ).toBeInTheDocument();
  });
});

// Detalle precargado en modo EDICIÓN: 2 tutores (con id) + consentimiento ya
// otorgado + ficha médica visible.
const DEPORTISTA_EDIT: DeportistaDetail = {
  id: 'dep-1',
  ap_paterno: 'Condori',
  ap_materno: 'Huanca',
  nombres: 'Valentina',
  nombre_completo: 'Valentina Condori Huanca',
  ci: '9876543',
  fecha_nac: '2012-06-01',
  edad: 13,
  disciplina: 'Natación',
  disciplina_id: 'd2',
  contacto_emergencia: 'Mamá 70000000',
  domicilio: 'Calle Falsa 123',
  lugar_nacimiento: 'La Paz',
  sucursal: { id: 's1', nombre: 'Centro' },
  categoria: null,
  // Con inscripción: el form de edición precarga cuota mensual + fecha (ahora
  // obligatorias), de modo que "Guardar cambios" pase la validación.
  inscripcion: {
    fecha_inscripcion: '2024-01-15',
    monto_mensual: '150.00',
    disciplina: '',
    estado: 'ACTIVA',
  },
  tutores: [
    {
      id: 't1',
      nombres: 'Rosa Huanca',
      telefono: '71111111',
      ci: '5550000',
      parentesco: 'Madre',
      responsable_pago: true,
    },
    {
      id: 't2',
      nombres: 'Juan Condori',
      telefono: '72222222',
      ci: '5551111',
      parentesco: 'Padre',
      responsable_pago: false,
    },
  ],
  consentimiento: { aceptado_en: '2024-01-01T00:00:00Z', version_terminos: 'v1', canal: 'WEB' },
  ficha_medica: { tipo_sangre: 'O+', alergias: 'Polen', condiciones: '' },
  activo: true,
};

describe('NuevoDeportista — modo EDICIÓN (Fase 3)', () => {
  beforeEach(() => {
    sucursalesMock.mockReset();
    categoriasMock.mockReset();
    disciplinasCatalogoMock.mockReset();
    crearDeportistaMock.mockReset();
    deportistaPorCiMock.mockReset();
    tutorPorCiMock.mockReset();
    deportistaMock.mockReset();
    actualizarDeportistaMock.mockReset();
    sucursalesMock.mockResolvedValue(SUCURSALES);
    categoriasMock.mockResolvedValue([]);
    disciplinasCatalogoMock.mockResolvedValue(DISCIPLINAS);
    deportistaMock.mockResolvedValue(DEPORTISTA_EDIT);
    actualizarDeportistaMock.mockResolvedValue(DEPORTISTA_EDIT);
  });
  afterEach(() => vi.clearAllMocks());

  it('precarga datos, tutores y ficha; el escáner OCR no se muestra', async () => {
    renderEdit();
    // Título de edición y carga del detalle.
    expect(await screen.findByText('Editar deportista')).toBeInTheDocument();
    await waitFor(() => expect(deportistaMock).toHaveBeenCalledWith('dep-1', expect.anything()));

    // Datos básicos precargados.
    expect((screen.getByLabelText(/Apellido paterno/) as HTMLInputElement).value).toBe(
      'Condori',
    );
    expect((screen.getAllByLabelText(/^CI/)[0] as HTMLInputElement).value).toBe('9876543');
    // Ficha médica precargada.
    expect((screen.getByLabelText(/Grupo sanguíneo/) as HTMLInputElement).value).toBe('O+');
    // Los 2 tutores precargados (nombres del tutor: índices 1 y 2 de "Nombres").
    expect((screen.getAllByLabelText(/^Nombres/)[1] as HTMLInputElement).value).toBe(
      'Rosa Huanca',
    );
    expect((screen.getAllByLabelText(/^Nombres/)[2] as HTMLInputElement).value).toBe(
      'Juan Condori',
    );
    // El escáner OCR NO aparece en edición.
    expect(screen.queryByText(/Escanea ambos lados/)).not.toBeInTheDocument();
    // El consentimiento se informa como ya otorgado (no hay checkbox).
    expect(screen.getByText(/ya fue otorgado y se conserva/)).toBeInTheDocument();
    expect(
      screen.queryByRole('checkbox', { name: /consentimiento/i }),
    ).not.toBeInTheDocument();
  });

  it('guarda con PUT incluyendo los tutores con su id y navega al perfil', async () => {
    const user = userEvent.setup();
    renderEdit();
    await screen.findByText('Editar deportista');
    await waitFor(() => expect(deportistaMock).toHaveBeenCalled());

    // Edita un campo y el teléfono de un tutor.
    const nombres = screen.getAllByLabelText(/^Nombres/)[0];
    await user.clear(nombres);
    await user.type(nombres, 'Valentina Sofía');

    await user.click(screen.getByRole('button', { name: 'Guardar cambios' }));

    await waitFor(() => expect(actualizarDeportistaMock).toHaveBeenCalledTimes(1));
    const [calledId, payload] = actualizarDeportistaMock.mock.calls[0];
    expect(calledId).toBe('dep-1');
    expect(payload.nombres).toBe('Valentina Sofía');
    // Los tutores van con su id (reconciliación por id) y NO se manda consentimiento.
    expect(payload.tutores).toHaveLength(2);
    expect(payload.tutores[0].id).toBe('t1');
    expect(payload.tutores[1].id).toBe('t2');
    expect(payload.consentimiento).toBeUndefined();
    // Ficha médica incluida (tenía datos).
    expect(payload.ficha_medica.tipo_sangre).toBe('O+');
    // Navegó al perfil del deportista.
    expect(await screen.findByText('PERFIL dep-1')).toBeInTheDocument();
  });

  it('permite quitar un tutor cuando hay más de uno (invariante UX: no el último)', async () => {
    const user = userEvent.setup();
    renderEdit();
    await screen.findByText('Editar deportista');
    await waitFor(() => expect(deportistaMock).toHaveBeenCalled());

    // Con 2 tutores hay botón "Quitar"; quita el segundo.
    const quitar = screen.getAllByRole('button', { name: /Quitar tutor/i });
    expect(quitar).toHaveLength(2);
    await user.click(quitar[1]);

    // Ya solo queda 1 tutor: el botón "Quitar" desaparece (no se puede dejar 0).
    expect(screen.queryByRole('button', { name: /Quitar tutor/i })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Guardar cambios' }));
    await waitFor(() => expect(actualizarDeportistaMock).toHaveBeenCalledTimes(1));
    const payload = actualizarDeportistaMock.mock.calls[0][1];
    expect(payload.tutores).toHaveLength(1);
    expect(payload.tutores[0].id).toBe('t1');
  });

  it('muestra el mensaje 422 del backend (invariante de menores) sin crash', async () => {
    const user = userEvent.setup();
    // fieldErrors es el 4º argumento del ApiError (el 3º es `detail`). El backend
    // ata el invariante de menores a `loc: ['body', 'tutores']`.
    actualizarDeportistaMock.mockRejectedValue(
      new ApiError(422, 'No se puede quitar al tutor del consentimiento.', null, [
        { loc: ['body', 'tutores'], msg: 'No se puede quitar al tutor del consentimiento.' },
      ]),
    );
    renderEdit();
    await screen.findByText('Editar deportista');
    await waitFor(() => expect(deportistaMock).toHaveBeenCalled());

    await user.click(screen.getByRole('button', { name: 'Guardar cambios' }));

    await waitFor(() => expect(actualizarDeportistaMock).toHaveBeenCalledTimes(1));
    expect(
      await screen.findByText('No se puede quitar al tutor del consentimiento.'),
    ).toBeInTheDocument();
  });

  it('corta el render con un error si el deportista no existe (404)', async () => {
    deportistaMock.mockRejectedValue(new ApiError(404, 'Deportista no encontrado', null));
    renderEdit('dep-x');
    expect(await screen.findByText('Deportista no encontrado.')).toBeInTheDocument();
    // No se renderiza el formulario de edición.
    expect(screen.queryByText('Editar deportista')).not.toBeInTheDocument();
  });
});
