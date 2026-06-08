import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { AvisoOut, PreviewNotificacionOut, Sucursal } from '@/api/types';

// Mock del cliente API: los tests usan mocks, no la API real.
const crearAvisoMock = vi.fn();
const actualizarAvisoMock = vi.fn();
const categoriasMock = vi.fn();
const previewMock = vi.fn();
vi.mock('@/api/client', () => ({
  api: {
    crearAviso: (...args: unknown[]) => crearAvisoMock(...args),
    actualizarAviso: (...args: unknown[]) => actualizarAvisoMock(...args),
    categorias: (...args: unknown[]) => categoriasMock(...args),
    previewNotificacionAviso: (...args: unknown[]) => previewMock(...args),
  },
  // ApiError mínimo con los getters que usa el formulario.
  ApiError: class ApiError extends Error {
    status: number;
    fieldErrors: { loc: (string | number)[]; msg: string }[];
    constructor(status = 500, message = '', fieldErrors: never[] = []) {
      super(message);
      this.status = status;
      this.fieldErrors = fieldErrors;
    }
    get isValidation() {
      return this.status === 422;
    }
    get isForbidden() {
      return this.status === 403;
    }
  },
}));

import { NuevoAviso } from './NuevoAviso';

const SUCURSALES: Sucursal[] = [{ id: 's1', nombre: 'Centro', direccion: '' }];

const AVISO_CREADO: AvisoOut = {
  id: 'av-1',
  titulo: 'Inscripciones',
  cuerpo: 'Texto del aviso',
  alcance: 'ORG',
  sucursal: null,
  categoria: null,
  publicado_en: '2026-06-01T10:00:00Z',
  vigente_hasta: null,
  creado_por_nombre: 'Ana Admin',
  expirado: false,
};

const PREVIEW: PreviewNotificacionOut = {
  entrenadores: 3,
  tutores: 12,
  total: 15,
  sin_telefono: 2,
};

function renderNuevo(aviso?: AvisoOut | null) {
  const onClose = vi.fn();
  const onSaved = vi.fn();
  render(
    <NuevoAviso sucursales={SUCURSALES} aviso={aviso} onClose={onClose} onSaved={onSaved} />,
  );
  return { onClose, onSaved };
}

async function llenarFormulario(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(/Título/), 'Inscripciones');
  await user.type(screen.getByLabelText(/Cuerpo/), 'Texto del aviso');
}

describe('NuevoAviso — notificación por WhatsApp', () => {
  beforeEach(() => {
    crearAvisoMock.mockReset();
    actualizarAvisoMock.mockReset();
    categoriasMock.mockReset();
    previewMock.mockReset();
    crearAvisoMock.mockResolvedValue(AVISO_CREADO);
    actualizarAvisoMock.mockResolvedValue(AVISO_CREADO);
    categoriasMock.mockResolvedValue([]);
    previewMock.mockResolvedValue(PREVIEW);
  });
  afterEach(() => vi.clearAllMocks());

  it('muestra los checkboxes desmarcados por defecto en el alta', () => {
    renderNuevo();
    const entrenadores = screen.getByLabelText('Entrenadores') as HTMLInputElement;
    const tutores = screen.getByLabelText('Tutores') as HTMLInputElement;
    expect(entrenadores.checked).toBe(false);
    expect(tutores.checked).toBe(false);
  });

  it('NO muestra los checkboxes en modo edición', () => {
    renderNuevo(AVISO_CREADO);
    expect(screen.queryByLabelText('Entrenadores')).toBeNull();
    expect(screen.queryByLabelText('Tutores')).toBeNull();
  });

  it('alta sin notificación: crea directo sin preview ni confirmación', async () => {
    const user = userEvent.setup();
    const { onSaved } = renderNuevo();
    await llenarFormulario(user);
    await user.click(screen.getByRole('button', { name: 'Publicar aviso' }));

    await waitFor(() => expect(crearAvisoMock).toHaveBeenCalledTimes(1));
    expect(previewMock).not.toHaveBeenCalled();
    const payload = crearAvisoMock.mock.calls[0][0];
    expect(payload.notificar_entrenadores).toBe(false);
    expect(payload.notificar_tutores).toBe(false);
    expect(onSaved).toHaveBeenCalledWith(AVISO_CREADO);
  });

  it('con grupo marcado: pide preview y muestra el conteo antes de crear', async () => {
    const user = userEvent.setup();
    renderNuevo();
    await llenarFormulario(user);
    await user.click(screen.getByLabelText('Entrenadores'));
    await user.click(screen.getByLabelText('Tutores'));
    await user.click(screen.getByRole('button', { name: 'Publicar aviso' }));

    await waitFor(() => expect(previewMock).toHaveBeenCalledTimes(1));
    expect(previewMock.mock.calls[0][0]).toMatchObject({
      alcance: 'ORG',
      sucursal_id: null,
      categoria_id: null,
      notificar_entrenadores: true,
      notificar_tutores: true,
    });
    // No crea todavía: espera confirmación.
    expect(crearAvisoMock).not.toHaveBeenCalled();
    expect(await screen.findByText(/15/)).toBeInTheDocument();
    expect(screen.getByText(/3 entrenadores/)).toBeInTheDocument();
    expect(screen.getByText(/12 tutores/)).toBeInTheDocument();
    expect(screen.getByText(/2 personas sin teléfono/)).toBeInTheDocument();
  });

  it('confirmar el envío crea el aviso con las flags', async () => {
    const user = userEvent.setup();
    const { onSaved } = renderNuevo();
    await llenarFormulario(user);
    await user.click(screen.getByLabelText('Entrenadores'));
    await user.click(screen.getByRole('button', { name: 'Publicar aviso' }));

    await screen.findByText(/¿Confirmar\?/);
    await user.click(screen.getByRole('button', { name: 'Confirmar y publicar' }));

    await waitFor(() => expect(crearAvisoMock).toHaveBeenCalledTimes(1));
    const payload = crearAvisoMock.mock.calls[0][0];
    expect(payload.notificar_entrenadores).toBe(true);
    expect(payload.notificar_tutores).toBe(false);
    expect(onSaved).toHaveBeenCalledWith(AVISO_CREADO);
  });

  it('cancelar en la confirmación NO crea el aviso', async () => {
    const user = userEvent.setup();
    renderNuevo();
    await llenarFormulario(user);
    await user.click(screen.getByLabelText('Tutores'));
    await user.click(screen.getByRole('button', { name: 'Publicar aviso' }));

    await screen.findByText(/¿Confirmar\?/);
    await user.click(screen.getByRole('button', { name: 'Cancelar' }));

    // Vuelve al formulario; sin crear nada.
    expect(crearAvisoMock).not.toHaveBeenCalled();
    expect(await screen.findByLabelText('Tutores')).toBeInTheDocument();
  });

  it('si el preview falla, permite publicar igual (no bloquea el alta)', async () => {
    previewMock.mockRejectedValue(new Error('boom'));
    const user = userEvent.setup();
    const { onSaved } = renderNuevo();
    await llenarFormulario(user);
    await user.click(screen.getByLabelText('Entrenadores'));
    await user.click(screen.getByRole('button', { name: 'Publicar aviso' }));

    // Muestra el aviso de fallo del conteo pero sigue ofreciendo publicar.
    expect(
      await screen.findByText(/No se pudo calcular el número de destinatarios/),
    ).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Confirmar y publicar' }));

    await waitFor(() => expect(crearAvisoMock).toHaveBeenCalledTimes(1));
    expect(crearAvisoMock.mock.calls[0][0].notificar_entrenadores).toBe(true);
    expect(onSaved).toHaveBeenCalledWith(AVISO_CREADO);
  });
});
