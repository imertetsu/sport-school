import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { DeportistasListResponse } from '@/api/types';

// Mock del cliente API: los tests no llaman a la API real (VITE_API_URL).
const deportistasMock = vi.fn();
vi.mock('@/api/client', () => ({
  api: {
    deportistas: (...args: unknown[]) => deportistasMock(...args),
    sucursales: vi.fn(() => Promise.resolve([])),
    // Catálogos de los filtros (disciplina/categoría): la lista los carga al montar.
    disciplinasCatalogo: vi.fn(() => Promise.resolve([])),
    categorias: vi.fn(() => Promise.resolve([])),
  },
  ApiError: class ApiError extends Error {},
}));

// Mock de los contextos de la shell (sucursal seleccionada + búsqueda).
vi.mock('@/components/shell/SucursalContext', () => ({
  useSucursales: () => ({
    sucursales: [],
    loading: false,
    error: null,
    selected: '',
    setSelected: vi.fn(),
  }),
}));
vi.mock('@/components/shell/SearchContext', () => ({
  useSearch: () => ({ query: '', setQuery: vi.fn() }),
}));

import { DeportistasList } from './DeportistasList';

const MOCK_RESPONSE: DeportistasListResponse = {
  page: 1,
  page_size: 50,
  total: 2,
  items: [
    {
      id: 'a1',
      ap_paterno: 'Quispe',
      ap_materno: 'Mamani',
      nombres: 'Mateo',
      nombre_completo: 'Mateo Quispe Mamani',
      ci: '9123456 LP',
      disciplina: 'Fútbol',
      categoria: { id: 'c1', nombre: 'Sub-14', nivel: 'INTERMEDIO' },
      sucursal: { id: 's1', nombre: 'Centro' },
      activo: true,
    },
    {
      id: 'a2',
      ap_paterno: 'Condori',
      ap_materno: 'Huanca',
      nombres: 'Valentina',
      nombre_completo: 'Valentina Condori Huanca',
      ci: '9876543 CB',
      disciplina: 'Natación',
      categoria: null,
      sucursal: { id: 's2', nombre: 'Cala Cala' },
      activo: true,
    },
  ],
};

function renderList() {
  return render(
    <MemoryRouter>
      <DeportistasList />
    </MemoryRouter>,
  );
}

describe('DeportistasList', () => {
  beforeEach(() => {
    deportistasMock.mockReset();
  });
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('renderiza los deportistas devueltos por la API mock', async () => {
    deportistasMock.mockResolvedValue(MOCK_RESPONSE);
    renderList();

    expect(await screen.findByText('Mateo Quispe Mamani')).toBeInTheDocument();
    expect(screen.getByText('Valentina Condori Huanca')).toBeInTheDocument();
    // categoría · disciplina
    expect(screen.getByText('Sub-14 Intermedio · Fútbol')).toBeInTheDocument();
    // deportista sin categoría
    expect(screen.getByText('Sin categoría · Natación')).toBeInTheDocument();
    // sucursales
    expect(screen.getByText('Centro')).toBeInTheDocument();
    expect(screen.getByText('Cala Cala')).toBeInTheDocument();
  });

  it('muestra el total de deportistas en el subtítulo', async () => {
    deportistasMock.mockResolvedValue(MOCK_RESPONSE);
    renderList();
    expect(await screen.findByText('2 deportistas')).toBeInTheDocument();
  });

  it('placeholder "—" en la columna estado (cobranza es otro epic)', async () => {
    deportistasMock.mockResolvedValue(MOCK_RESPONSE);
    const { container } = renderList();
    await screen.findByText('Mateo Quispe Mamani');
    const placeholders = container.querySelectorAll('.estado-placeholder');
    expect(placeholders.length).toBe(2);
  });

  it('muestra el mensaje vacío cuando no hay resultados', async () => {
    deportistasMock.mockResolvedValue({ ...MOCK_RESPONSE, items: [], total: 0 });
    renderList();
    await waitFor(() =>
      expect(screen.getByText('Aún no hay deportistas registrados')).toBeInTheDocument(),
    );
  });
});
