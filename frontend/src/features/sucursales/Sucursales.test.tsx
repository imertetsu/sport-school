import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { Categoria, Sucursal } from '@/api/types';

// Mock del cliente API: los tests usan mocks, no la API real. La factory de
// vi.mock se iza al tope, así que el ApiError falso (con status/isForbidden/
// isValidation, como el real) se define DENTRO de la factory y se recupera del
// módulo mockeado para construir errores 409/403/422 en los tests.
const sucursalesMock = vi.fn();
const categoriasMock = vi.fn();
const crearSucursalMock = vi.fn();
const actualizarSucursalMock = vi.fn();
const eliminarSucursalMock = vi.fn();
const crearCategoriaMock = vi.fn();
const actualizarCategoriaMock = vi.fn();
const eliminarCategoriaMock = vi.fn();

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
      sucursales: (...args: unknown[]) => sucursalesMock(...args),
      categorias: (...args: unknown[]) => categoriasMock(...args),
      crearSucursal: (...args: unknown[]) => crearSucursalMock(...args),
      actualizarSucursal: (...args: unknown[]) => actualizarSucursalMock(...args),
      eliminarSucursal: (...args: unknown[]) => eliminarSucursalMock(...args),
      crearCategoria: (...args: unknown[]) => crearCategoriaMock(...args),
      actualizarCategoria: (...args: unknown[]) => actualizarCategoriaMock(...args),
      eliminarCategoria: (...args: unknown[]) => eliminarCategoriaMock(...args),
    },
    ApiError,
  };
});

import { ApiError } from '@/api/client';
import { Sucursales } from './Sucursales';

const SUCURSALES: Sucursal[] = [
  { id: 's1', nombre: 'Centro', direccion: 'Av. Principal 123' },
  { id: 's2', nombre: 'Norte', direccion: '' },
];

const CATEGORIAS_S1: Categoria[] = [
  {
    id: 'c1',
    nombre: 'Sub-12',
    nivel: 'PRINCIPIANTE',
    rango_edad: '10-12 años',
    sucursal_id: 's1',
  },
];

describe('Sucursales — CRUD (ADMIN)', () => {
  beforeEach(() => {
    sucursalesMock.mockReset();
    categoriasMock.mockReset();
    crearSucursalMock.mockReset();
    actualizarSucursalMock.mockReset();
    eliminarSucursalMock.mockReset();
    crearCategoriaMock.mockReset();
    actualizarCategoriaMock.mockReset();
    eliminarCategoriaMock.mockReset();
    sucursalesMock.mockResolvedValue(SUCURSALES);
    categoriasMock.mockResolvedValue(CATEGORIAS_S1);
  });
  afterEach(() => vi.clearAllMocks());

  it('lista las sucursales (ADMIN ve la pantalla)', async () => {
    render(<Sucursales />);
    expect(await screen.findByText('Centro')).toBeInTheDocument();
    expect(screen.getByText('Norte')).toBeInTheDocument();
    expect(screen.getByText('Av. Principal 123')).toBeInTheDocument();
    // La sucursal sin dirección muestra el placeholder.
    expect(screen.getByText('Sin dirección')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: '+ Nueva sucursal' }),
    ).toBeInTheDocument();
  });

  it('alta de sucursal: envía el body al cliente y recarga', async () => {
    const user = userEvent.setup();
    crearSucursalMock.mockResolvedValue({
      id: 's3',
      nombre: 'Sur',
      direccion: 'Calle 9',
    });
    render(<Sucursales />);
    await screen.findByText('Centro');

    await user.click(screen.getByRole('button', { name: '+ Nueva sucursal' }));
    const dialog = await screen.findByRole('dialog', { name: 'Nueva sucursal' });
    await user.type(within(dialog).getByLabelText(/Nombre/), 'Sur');
    await user.type(within(dialog).getByLabelText(/Dirección/), 'Calle 9');
    await user.click(within(dialog).getByRole('button', { name: 'Crear sucursal' }));

    await waitFor(() =>
      expect(crearSucursalMock).toHaveBeenCalledWith({
        nombre: 'Sur',
        direccion: 'Calle 9',
      }),
    );
    // Tras crear, recarga la lista (sucursales() se llama de nuevo).
    await waitFor(() => expect(sucursalesMock).toHaveBeenCalledTimes(2));
  });

  it('baja con 409 (en uso): muestra el aviso del backend y no borra en cascada', async () => {
    const user = userEvent.setup();
    eliminarSucursalMock.mockRejectedValue(
      new ApiError(409, 'La sucursal tiene 2 categorías / 5 deportistas asignados', null),
    );
    render(<Sucursales />);
    await screen.findByText('Centro');

    // Eliminar la primera sucursal: pide confirmación antes de llamar a la API.
    await user.click(screen.getAllByRole('button', { name: 'Eliminar' })[0]);
    expect(eliminarSucursalMock).not.toHaveBeenCalled();

    const confirmDialog = await screen.findByRole('alertdialog', {
      name: 'Confirmar eliminación de sucursal',
    });
    await user.click(
      within(confirmDialog).getByRole('button', { name: 'Eliminar' }),
    );

    await waitFor(() => expect(eliminarSucursalMock).toHaveBeenCalledWith('s1'));
    // El mensaje del backend (409) aparece en el aviso inline (role=alert).
    const alerts = await screen.findAllByRole('alert');
    expect(
      alerts.some((a) =>
        a.textContent?.includes('La sucursal tiene 2 categorías / 5 deportistas asignados'),
      ),
    ).toBe(true);
  });

  it('despliega la gestión de categorías de una sucursal', async () => {
    const user = userEvent.setup();
    render(<Sucursales />);
    await screen.findByText('Centro');

    // Abre el panel de categorías de "Centro".
    await user.click(screen.getAllByRole('button', { name: 'Categorías' })[0]);
    expect(await screen.findByText('Categorías de Centro')).toBeInTheDocument();
    expect(await screen.findByText('Sub-12')).toBeInTheDocument();
    expect(screen.getByText('10-12 años')).toBeInTheDocument();
    expect(screen.getByText('Principiante')).toBeInTheDocument();
    // El cliente filtró por la sucursal seleccionada.
    await waitFor(() =>
      expect(categoriasMock).toHaveBeenCalledWith('s1', expect.anything()),
    );
  });

  it('alta de categoría: envía nivel y sucursal_id al cliente', async () => {
    const user = userEvent.setup();
    crearCategoriaMock.mockResolvedValue({
      id: 'c9',
      nombre: 'Sub-14',
      nivel: 'INTERMEDIO',
      rango_edad: '13-14 años',
      sucursal_id: 's1',
    });
    render(<Sucursales />);
    await screen.findByText('Centro');
    await user.click(screen.getAllByRole('button', { name: 'Categorías' })[0]);
    await screen.findByText('Categorías de Centro');

    await user.click(screen.getByRole('button', { name: '+ Nueva categoría' }));
    const dialog = await screen.findByRole('dialog', { name: 'Nueva categoría' });
    await user.type(within(dialog).getByLabelText(/Nombre/), 'Sub-14');
    await user.selectOptions(within(dialog).getByLabelText(/Nivel/), 'INTERMEDIO');
    await user.type(within(dialog).getByLabelText(/Rango de edad/), '13-14 años');
    await user.click(within(dialog).getByRole('button', { name: 'Crear categoría' }));

    await waitFor(() =>
      expect(crearCategoriaMock).toHaveBeenCalledWith({
        nombre: 'Sub-14',
        nivel: 'INTERMEDIO',
        rango_edad: '13-14 años',
        sucursal_id: 's1',
      }),
    );
  });

  it('baja de categoría con 409: muestra el aviso del backend', async () => {
    const user = userEvent.setup();
    eliminarCategoriaMock.mockRejectedValue(
      new ApiError(409, 'La categoría tiene 3 deportistas asignados', null),
    );
    render(<Sucursales />);
    await screen.findByText('Centro');
    await user.click(screen.getAllByRole('button', { name: 'Categorías' })[0]);
    await screen.findByText('Sub-12');

    // Dentro del panel de categorías: Eliminar la fila de la categoría (la tabla
    // de categorías tiene aria-label propio, para no chocar con la de sucursales).
    const catTable = screen.getByRole('table', { name: 'Categorías de Centro' });
    await user.click(within(catTable).getByRole('button', { name: 'Eliminar' }));
    const confirmDialog = await screen.findByRole('alertdialog', {
      name: 'Confirmar eliminación de categoría',
    });
    await user.click(
      within(confirmDialog).getByRole('button', { name: 'Eliminar' }),
    );

    await waitFor(() => expect(eliminarCategoriaMock).toHaveBeenCalledWith('c1'));
    const alerts = await screen.findAllByRole('alert');
    expect(
      alerts.some((a) =>
        a.textContent?.includes('La categoría tiene 3 deportistas asignados'),
      ),
    ).toBe(true);
  });
});
