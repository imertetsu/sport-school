import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import type { Role, SemanaOut } from '@/api/types';

// Mock del cliente API: los tests usan mocks, no la API real.
const horariosSemanaMock = vi.fn();
const categoriasMock = vi.fn();
const crearHorarioMock = vi.fn();
const actualizarHorarioMock = vi.fn();
const eliminarHorarioMock = vi.fn();
vi.mock('@/api/client', () => ({
  api: {
    horariosSemana: (...args: unknown[]) => horariosSemanaMock(...args),
    categorias: (...args: unknown[]) => categoriasMock(...args),
    crearHorario: (...args: unknown[]) => crearHorarioMock(...args),
    actualizarHorario: (...args: unknown[]) => actualizarHorarioMock(...args),
    eliminarHorario: (...args: unknown[]) => eliminarHorarioMock(...args),
  },
  ApiError: class ApiError extends Error {},
}));

// Sucursales del filtro.
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

import { Horarios } from './Horarios';

// Rejilla semanal: 7 días (0..6). Lunes tiene una clase; el resto vacíos.
const SEMANA: SemanaOut = {
  dias: [
    {
      dia_semana: 0,
      dia_label: 'Lunes',
      clases: [
        {
          id: 'h1',
          categoria: { id: 'c1', nombre: 'Sub-14 Intermedio' },
          sucursal: { id: 's1', nombre: 'Centro' },
          hora_inicio: '16:00',
          hora_fin: '17:30',
          entrenador: { id: 'e1', nombres: 'Carlos Coach' },
        },
      ],
    },
    { dia_semana: 1, dia_label: 'Martes', clases: [] },
    { dia_semana: 2, dia_label: 'Miércoles', clases: [] },
    {
      dia_semana: 3,
      dia_label: 'Jueves',
      clases: [
        {
          id: 'h2',
          categoria: { id: 'c2', nombre: 'Sub-10 Principiante' },
          sucursal: { id: 's2', nombre: 'Zona Sur' },
          hora_inicio: '15:00',
          hora_fin: '16:00',
          entrenador: null,
        },
      ],
    },
    { dia_semana: 4, dia_label: 'Viernes', clases: [] },
    { dia_semana: 5, dia_label: 'Sábado', clases: [] },
    { dia_semana: 6, dia_label: 'Domingo', clases: [] },
  ],
};

function renderHorarios() {
  return render(
    <MemoryRouter>
      <Horarios />
    </MemoryRouter>,
  );
}

describe('Horarios — rejilla semanal', () => {
  beforeEach(() => {
    mockRole = 'ADMIN';
    horariosSemanaMock.mockReset();
    categoriasMock.mockReset();
    crearHorarioMock.mockReset();
    actualizarHorarioMock.mockReset();
    eliminarHorarioMock.mockReset();
    horariosSemanaMock.mockResolvedValue(SEMANA);
    categoriasMock.mockResolvedValue([]);
    eliminarHorarioMock.mockResolvedValue(undefined);
  });
  afterEach(() => vi.clearAllMocks());

  it('renderiza las 7 columnas (Lun..Dom) de la rejilla', async () => {
    renderHorarios();
    expect(await screen.findByText('Lunes')).toBeInTheDocument();
    for (const dia of [
      'Martes',
      'Miércoles',
      'Jueves',
      'Viernes',
      'Sábado',
      'Domingo',
    ]) {
      expect(screen.getByText(dia)).toBeInTheDocument();
    }
  });

  it('muestra los bloques de clase con su hora y entrenador', async () => {
    renderHorarios();
    expect(await screen.findByText('Sub-14 Intermedio')).toBeInTheDocument();
    // Hora_inicio–hora_fin formateado vía lib/format (24h).
    expect(screen.getByText('16:00–17:30')).toBeInTheDocument();
    expect(screen.getByText('Carlos Coach')).toBeInTheDocument();
    // Clase sin entrenador -> badge "Sin entrenador".
    expect(screen.getByText('Sub-10 Principiante')).toBeInTheDocument();
    expect(screen.getByText('Sin entrenador')).toBeInTheDocument();
    // Cada bloque muestra a qué sucursal pertenece la clase.
    expect(screen.getByText('Zona Sur')).toBeInTheDocument();
  });

  it('muestra las acciones de admin (Nuevo horario, Editar, Eliminar) si role ADMIN', async () => {
    renderHorarios();
    expect(
      await screen.findByRole('button', { name: '+ Nuevo horario' }),
    ).toBeInTheDocument();
    // Un bloque por cada clase (2) -> 2 botones Editar y 2 Eliminar.
    expect(screen.getAllByRole('button', { name: 'Editar' })).toHaveLength(2);
    expect(screen.getAllByRole('button', { name: 'Eliminar' })).toHaveLength(2);
  });

  it('NO muestra acciones de admin si role ENTRENADOR (solo lectura)', async () => {
    mockRole = 'ENTRENADOR';
    renderHorarios();
    await screen.findByText('Sub-14 Intermedio');
    expect(screen.queryByRole('button', { name: '+ Nuevo horario' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Editar' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Eliminar' })).toBeNull();
  });

  it('elimina (soft-delete) un horario tras confirmar', async () => {
    const user = userEvent.setup();
    renderHorarios();
    await screen.findByText('Sub-14 Intermedio');
    // Pide confirmación antes de llamar a la API.
    await user.click(screen.getAllByRole('button', { name: 'Eliminar' })[0]);
    expect(eliminarHorarioMock).not.toHaveBeenCalled();
    // Confirma -> DELETE del primer horario (soft-delete vía backend).
    const confirmar = screen
      .getAllByRole('button', { name: 'Eliminar' })
      .find((b) => b.className.includes('btn--danger'))!;
    await user.click(confirmar);
    await waitFor(() => expect(eliminarHorarioMock).toHaveBeenCalledWith('h1'));
  });
});
