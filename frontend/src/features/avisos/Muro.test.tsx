import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import type { AvisosPage, Role } from '@/api/types';

// Mock del cliente API: los tests usan mocks, no la API real.
const avisosMock = vi.fn();
const crearAvisoMock = vi.fn();
const actualizarAvisoMock = vi.fn();
const eliminarAvisoMock = vi.fn();
const categoriasMock = vi.fn();
vi.mock('@/api/client', () => ({
  api: {
    avisos: (...args: unknown[]) => avisosMock(...args),
    crearAviso: (...args: unknown[]) => crearAvisoMock(...args),
    actualizarAviso: (...args: unknown[]) => actualizarAvisoMock(...args),
    eliminarAviso: (...args: unknown[]) => eliminarAvisoMock(...args),
    categorias: (...args: unknown[]) => categoriasMock(...args),
  },
  ApiError: class ApiError extends Error {},
}));

// Sucursales del alcance (para el selector del modal).
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

import { Muro } from './Muro';

const PAGE: AvisosPage = {
  page: 1,
  page_size: 20,
  total: 3,
  items: [
    {
      id: 'av-org',
      titulo: 'Inscripciones abiertas',
      cuerpo: 'Ya puedes inscribir a tus hijos para la nueva temporada.',
      alcance: 'ORG',
      sucursal: null,
      categoria: null,
      publicado_en: '2026-06-01T10:00:00Z',
      vigente_hasta: null,
      creado_por_nombre: 'Ana Admin',
      expirado: false,
    },
    {
      id: 'av-suc',
      titulo: 'Cancha en mantenimiento',
      cuerpo: 'La cancha del Centro estará cerrada el sábado.',
      alcance: 'SUCURSAL',
      sucursal: { id: 's1', nombre: 'Centro' },
      categoria: null,
      publicado_en: '2026-06-02T10:00:00Z',
      vigente_hasta: '2026-06-30',
      creado_por_nombre: 'Ana Admin',
      expirado: false,
    },
    {
      id: 'av-cat',
      titulo: 'Convocatoria Sub-14',
      cuerpo: 'Entrenamiento extra el viernes.',
      alcance: 'CATEGORIA',
      sucursal: null,
      categoria: { id: 'c1', nombre: 'Sub-14 Intermedio', nivel: 'INTERMEDIO' },
      publicado_en: '2026-06-03T10:00:00Z',
      vigente_hasta: null,
      creado_por_nombre: 'Carlos Coach',
      expirado: false,
    },
  ],
};

function renderMuro() {
  return render(
    <MemoryRouter>
      <Muro />
    </MemoryRouter>,
  );
}

describe('Muro de avisos', () => {
  beforeEach(() => {
    mockRole = 'ADMIN';
    avisosMock.mockReset();
    crearAvisoMock.mockReset();
    actualizarAvisoMock.mockReset();
    eliminarAvisoMock.mockReset();
    categoriasMock.mockReset();
    avisosMock.mockResolvedValue(PAGE);
    categoriasMock.mockResolvedValue([]);
    eliminarAvisoMock.mockResolvedValue(undefined);
  });
  afterEach(() => vi.clearAllMocks());

  it('renderiza el feed de avisos del mock', async () => {
    renderMuro();
    expect(await screen.findByText('Inscripciones abiertas')).toBeInTheDocument();
    expect(screen.getByText('Cancha en mantenimiento')).toBeInTheDocument();
    expect(screen.getByText('Convocatoria Sub-14')).toBeInTheDocument();
  });

  it('muestra el badge de alcance correcto por tarjeta', async () => {
    renderMuro();
    // ORG -> "Toda la escuela"; SUCURSAL -> nombre sucursal; CATEGORIA -> nombre categoría.
    expect(await screen.findByText('Toda la escuela')).toBeInTheDocument();
    expect(screen.getByText('Centro')).toBeInTheDocument();
    expect(screen.getByText('Sub-14 Intermedio')).toBeInTheDocument();
  });

  it('muestra "Vence" solo cuando hay vigente_hasta', async () => {
    renderMuro();
    await screen.findByText('Cancha en mantenimiento');
    // El aviso de sucursal tiene vigencia; los otros dos no.
    expect(screen.getAllByText(/^Vence /)).toHaveLength(1);
  });

  it('muestra acciones de admin (Nuevo aviso, Editar, Eliminar) si role ADMIN', async () => {
    renderMuro();
    expect(await screen.findByRole('button', { name: '+ Nuevo aviso' })).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Editar' })).toHaveLength(3);
    expect(screen.getAllByRole('button', { name: 'Eliminar' })).toHaveLength(3);
  });

  it('NO muestra acciones de admin si role ENTRENADOR (solo lectura)', async () => {
    mockRole = 'ENTRENADOR';
    renderMuro();
    await screen.findByText('Inscripciones abiertas');
    expect(screen.queryByRole('button', { name: '+ Nuevo aviso' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Editar' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Eliminar' })).toBeNull();
    // Tampoco el toggle de "mostrar vencidos".
    expect(screen.queryByText('Mostrar avisos vencidos')).toBeNull();
  });

  it('elimina (soft-delete) tras confirmar', async () => {
    const user = userEvent.setup();
    renderMuro();
    await screen.findByText('Inscripciones abiertas');
    // Pide confirmación antes de llamar a la API.
    await user.click(screen.getAllByRole('button', { name: 'Eliminar' })[0]);
    expect(eliminarAvisoMock).not.toHaveBeenCalled();
    // Confirma -> DELETE del primer aviso (soft-delete vía backend).
    const confirmar = screen
      .getAllByRole('button', { name: 'Eliminar' })
      .find((b) => b.className.includes('btn--danger'))!;
    await user.click(confirmar);
    await waitFor(() => expect(eliminarAvisoMock).toHaveBeenCalledWith('av-org'));
  });
});
