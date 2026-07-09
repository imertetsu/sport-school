import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { CategoriaAsistencia, RosterOut } from '@/api/types';

// Mock del cliente API: los tests usan mocks, no la API real.
const categoriasMock = vi.fn();
const rosterMock = vi.fn();
const guardarMock = vi.fn();
vi.mock('@/api/client', () => ({
  api: {
    asistenciaCategorias: (...args: unknown[]) => categoriasMock(...args),
    asistenciaRoster: (...args: unknown[]) => rosterMock(...args),
    asistenciaGuardar: (...args: unknown[]) => guardarMock(...args),
    // Catálogo de disciplinas para el filtro (se carga al montar).
    disciplinasCatalogo: vi.fn(() => Promise.resolve([])),
  },
  ApiError: class ApiError extends Error {},
}));

import { TomarAsistencia } from './TomarAsistencia';

const CATEGORIAS: CategoriaAsistencia[] = [
  {
    id: 'cat1',
    nombre: 'Sub-14 Intermedio',
    nivel: 'INTERMEDIO',
    sucursal: { id: 's1', nombre: 'Centro' },
    total_deportistas: 3,
  },
];

// Roster fresco: sin sesión guardada (estado=null por deportista).
const ROSTER_FRESCO: RosterOut = {
  sesion_id: null,
  categoria: { id: 'cat1', nombre: 'Sub-14 Intermedio' },
  fecha: '2026-06-05',
  items: [
    { deportista_id: 'a1', nombre_completo: 'Mateo Quispe Mamani', estado: null },
    { deportista_id: 'a2', nombre_completo: 'Valentina Condori Huanca', estado: null },
    { deportista_id: 'a3', nombre_completo: 'Santiago Vargas Apaza', estado: null },
  ],
  resumen: { presentes: 0, ausentes: 0, total: 3 },
};

// Roster con sesión ya guardada (refleja lo guardado al recargar).
const ROSTER_GUARDADO: RosterOut = {
  sesion_id: 'ses1',
  categoria: { id: 'cat1', nombre: 'Sub-14 Intermedio' },
  fecha: '2026-06-05',
  items: [
    { deportista_id: 'a1', nombre_completo: 'Mateo Quispe Mamani', estado: 'PRESENTE' },
    { deportista_id: 'a2', nombre_completo: 'Valentina Condori Huanca', estado: 'AUSENTE' },
    { deportista_id: 'a3', nombre_completo: 'Santiago Vargas Apaza', estado: 'PRESENTE' },
  ],
  resumen: { presentes: 2, ausentes: 1, total: 3 },
};

function contador(label: string): string {
  // El contador es: <valor/> + <label/> dentro del mismo bloque .contador.
  const labelEl = screen.getByText(label);
  const block = labelEl.closest('.contador');
  return block?.querySelector('.contador__valor')?.textContent ?? '';
}

describe('TomarAsistencia', () => {
  beforeEach(() => {
    categoriasMock.mockReset();
    rosterMock.mockReset();
    guardarMock.mockReset();
    categoriasMock.mockResolvedValue(CATEGORIAS);
    rosterMock.mockResolvedValue(ROSTER_FRESCO);
    guardarMock.mockResolvedValue(ROSTER_GUARDADO);
  });
  afterEach(() => vi.clearAllMocks());

  it('default Presente: roster sin sesión cuenta a todos como presentes', async () => {
    render(<TomarAsistencia />);
    // Espera a que cargue la lista.
    expect(await screen.findByText('Mateo Quispe Mamani')).toBeInTheDocument();
    // Default de marca: 3 presentes, 0 ausentes, total 3.
    expect(contador('Presentes')).toBe('3');
    expect(contador('Ausentes')).toBe('0');
    expect(contador('Total')).toBe('3');
  });

  it('toggle Ausente actualiza los contadores en vivo', async () => {
    const user = userEvent.setup();
    render(<TomarAsistencia />);
    await screen.findByText('Mateo Quispe Mamani');

    // Marca a Mateo como Ausente.
    const fila = screen.getByText('Mateo Quispe Mamani').closest('.roster__row')!;
    await user.click(within(fila as HTMLElement).getByRole('button', { name: 'Ausente' }));

    expect(contador('Presentes')).toBe('2');
    expect(contador('Ausentes')).toBe('1');
    // El toggle queda marcado como Ausente (aria-pressed).
    expect(
      within(fila as HTMLElement).getByRole('button', { name: 'Ausente' }),
    ).toHaveAttribute('aria-pressed', 'true');
  });

  it('al recargar refleja lo guardado (presente/ausente por deportista)', async () => {
    // El roster ya tiene una sesión guardada.
    rosterMock.mockResolvedValue(ROSTER_GUARDADO);
    render(<TomarAsistencia />);
    await screen.findByText('Valentina Condori Huanca');
    // 2 presentes, 1 ausente según lo persistido.
    expect(contador('Presentes')).toBe('2');
    expect(contador('Ausentes')).toBe('1');
    const filaVal = screen
      .getByText('Valentina Condori Huanca')
      .closest('.roster__row')!;
    expect(
      within(filaVal as HTMLElement).getByRole('button', { name: 'Ausente' }),
    ).toHaveAttribute('aria-pressed', 'true');
  });

  it('Guardar envía las marcas efectivas y muestra feedback', async () => {
    const user = userEvent.setup();
    render(<TomarAsistencia />);
    await screen.findByText('Mateo Quispe Mamani');

    await user.click(screen.getByRole('button', { name: 'Guardar' }));

    await waitFor(() => expect(guardarMock).toHaveBeenCalledTimes(1));
    const body = guardarMock.mock.calls[0][0];
    expect(body.categoria_id).toBe('cat1');
    expect(body.marcas).toHaveLength(3);
    // Default Presente aplicado a todos los no marcados.
    expect(body.marcas.every((m: { estado: string }) => m.estado === 'PRESENTE')).toBe(true);
    // Feedback de guardado.
    expect(await screen.findByText('✓ Asistencia guardada')).toBeInTheDocument();
  });
});
