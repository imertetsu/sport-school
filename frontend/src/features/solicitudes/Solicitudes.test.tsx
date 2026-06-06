import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import type { Role, SolicitudesPage } from '@/api/types';

// Mock del cliente API: los tests usan mocks, no la API real.
const solicitudesMock = vi.fn();
const crearSolicitudMock = vi.fn();
const aprobarSolicitudMock = vi.fn();
const rechazarSolicitudMock = vi.fn();
const categoriasMock = vi.fn();
vi.mock('@/api/client', () => ({
  api: {
    solicitudes: (...args: unknown[]) => solicitudesMock(...args),
    crearSolicitud: (...args: unknown[]) => crearSolicitudMock(...args),
    aprobarSolicitud: (...args: unknown[]) => aprobarSolicitudMock(...args),
    rechazarSolicitud: (...args: unknown[]) => rechazarSolicitudMock(...args),
    categorias: (...args: unknown[]) => categoriasMock(...args),
  },
  ApiError: class ApiError extends Error {},
}));

// Sucursales del alcance (entrenador: solo las suyas → mock las da ya filtradas).
vi.mock('@/components/shell/SucursalContext', () => ({
  useSucursales: () => ({
    sucursales: [{ id: 's1', nombre: 'Centro', direccion: '' }],
    loading: false,
    error: null,
    selected: '',
    setSelected: vi.fn(),
  }),
}));

// viewRole es la verdad de la UI; lo controlamos por test.
let mockRole: Role = 'ADMIN';
vi.mock('@/auth/useAuth', () => ({
  useAuth: () => ({ viewRole: mockRole }),
}));

import { Solicitudes } from './Solicitudes';

const PAGE: SolicitudesPage = {
  page: 1,
  page_size: 20,
  total: 1,
  items: [
    {
      id: 'sol-1',
      estado: 'PENDIENTE',
      ap_paterno: 'Quispe',
      ap_materno: 'Mamani',
      nombres: 'Luis',
      ci: '9123456 LP',
      fecha_nac: '2014-03-10',
      disciplina: 'Fútbol',
      contacto_emergencia: null,
      ficha_medica: null,
      tutor: { nombres: 'María Quispe', telefono: '70000000', ci: null, parentesco: 'Madre' },
      sucursal_sugerida: { id: 's1', nombre: 'Centro' },
      categoria_sugerida: null,
      creado_por_nombre: 'Carlos Coach',
      created_at: '2026-06-05T10:00:00Z',
      alumno_id: null,
      motivo_rechazo: null,
    },
  ],
};

function renderSolicitudes() {
  return render(
    <MemoryRouter>
      <Solicitudes />
    </MemoryRouter>,
  );
}

describe('Solicitudes — cola de auto-registro', () => {
  beforeEach(() => {
    mockRole = 'ADMIN';
    solicitudesMock.mockReset();
    crearSolicitudMock.mockReset();
    aprobarSolicitudMock.mockReset();
    rechazarSolicitudMock.mockReset();
    categoriasMock.mockReset();
    solicitudesMock.mockResolvedValue(PAGE);
    categoriasMock.mockResolvedValue([]);
  });
  afterEach(() => vi.clearAllMocks());

  it('renderiza la cola con los datos del mock', async () => {
    renderSolicitudes();
    expect(await screen.findByText('Quispe Mamani, Luis')).toBeInTheDocument();
    expect(screen.getByText('María Quispe')).toBeInTheDocument();
    expect(screen.getByText('Pendiente')).toBeInTheDocument();
  });

  it('muestra Aprobar/Rechazar en filas PENDIENTE si role ADMIN', async () => {
    renderSolicitudes();
    await screen.findByText('Quispe Mamani, Luis');
    expect(screen.getByRole('button', { name: 'Aprobar' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Rechazar' })).toBeInTheDocument();
  });

  it('NO muestra Aprobar/Rechazar si role ENTRENADOR (solo lectura)', async () => {
    mockRole = 'ENTRENADOR';
    renderSolicitudes();
    await screen.findByText('Quispe Mamani, Luis');
    expect(screen.queryByRole('button', { name: 'Aprobar' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Rechazar' })).toBeNull();
    // El entrenador SÍ puede capturar nuevas solicitudes.
    expect(screen.getByRole('button', { name: '+ Nueva solicitud' })).toBeInTheDocument();
  });

  it('abre el modal de rechazo y exige motivo antes de llamar a la API', async () => {
    const user = userEvent.setup();
    renderSolicitudes();
    await screen.findByText('Quispe Mamani, Luis');
    await user.click(screen.getByRole('button', { name: 'Rechazar' }));
    // Submit sin motivo -> no llama a la API y muestra el error.
    await user.click(screen.getByRole('button', { name: 'Rechazar solicitud' }));
    expect(rechazarSolicitudMock).not.toHaveBeenCalled();
    expect(screen.getByText('Indica el motivo del rechazo.')).toBeInTheDocument();
  });

  it('rechaza con motivo válido (llama a la API con el id y el motivo)', async () => {
    const user = userEvent.setup();
    rechazarSolicitudMock.mockResolvedValue({ ...PAGE.items[0], estado: 'RECHAZADA' });
    renderSolicitudes();
    await screen.findByText('Quispe Mamani, Luis');
    await user.click(screen.getByRole('button', { name: 'Rechazar' }));
    await user.type(screen.getByLabelText(/Motivo/), 'Datos incompletos');
    await user.click(screen.getByRole('button', { name: 'Rechazar solicitud' }));
    await waitFor(() =>
      expect(rechazarSolicitudMock).toHaveBeenCalledWith('sol-1', 'Datos incompletos'),
    );
  });
});
