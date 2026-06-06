import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { Sucursal } from '@/api/types';

// Mock del cliente API.
const crearSolicitudMock = vi.fn();
const categoriasMock = vi.fn();
vi.mock('@/api/client', () => ({
  api: {
    crearSolicitud: (...args: unknown[]) => crearSolicitudMock(...args),
    categorias: (...args: unknown[]) => categoriasMock(...args),
  },
  ApiError: class ApiError extends Error {},
}));

import { NuevaSolicitud } from './NuevaSolicitud';

const SUCURSALES: Sucursal[] = [{ id: 's1', nombre: 'Centro', direccion: '' }];

function renderForm() {
  const onClose = vi.fn();
  const onSaved = vi.fn();
  render(
    <NuevaSolicitud sucursales={SUCURSALES} onClose={onClose} onSaved={onSaved} />,
  );
  return { onClose, onSaved };
}

// Rellena alumno + tutor (mínimos) pero deja el consentimiento al criterio del test.
// "Nombres" y "CI" aparecen dos veces (alumno y tutor): se resuelven por posición.
async function llenarMinimos(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(/Apellido paterno/), 'Quispe');
  await user.type(screen.getByLabelText(/Fecha de nacimiento/), '2014-03-10');
  await user.type(screen.getByLabelText(/Disciplina/), 'Fútbol');
  // [0] = alumno, [1] = tutor.
  const nombres = screen.getAllByLabelText(/^Nombres/);
  await user.type(nombres[0], 'Luis');
  await user.type(nombres[1], 'María Quispe');
  await user.type(screen.getAllByLabelText(/^CI/)[0], '9123456 LP');
  await user.type(screen.getByLabelText(/Teléfono/), '70000000');
  await user.type(screen.getByLabelText(/Parentesco/), 'Madre');
}

describe('NuevaSolicitud — formulario de captura', () => {
  beforeEach(() => {
    crearSolicitudMock.mockReset();
    categoriasMock.mockReset();
    categoriasMock.mockResolvedValue([]);
  });
  afterEach(() => vi.clearAllMocks());

  it('NO envía si falta el consentimiento (es obligatorio)', async () => {
    const user = userEvent.setup();
    renderForm();
    await llenarMinimos(user);
    // Sin marcar el consentimiento.
    await user.click(screen.getByRole('button', { name: 'Enviar solicitud' }));
    expect(crearSolicitudMock).not.toHaveBeenCalled();
    expect(
      screen.getByText('El consentimiento del tutor es obligatorio.'),
    ).toBeInTheDocument();
  });

  it('envía con consentimiento marcado y aceptado:true en el payload', async () => {
    const user = userEvent.setup();
    crearSolicitudMock.mockResolvedValue({ id: 'sol-1' });
    const { onSaved } = renderForm();
    await llenarMinimos(user);
    // Marca el consentimiento obligatorio.
    await user.click(screen.getByRole('checkbox'));
    await user.click(screen.getByRole('button', { name: 'Enviar solicitud' }));
    await waitFor(() => expect(crearSolicitudMock).toHaveBeenCalledTimes(1));
    const payload = crearSolicitudMock.mock.calls[0][0];
    expect(payload.consentimiento).toEqual({ aceptado: true, version_terminos: 'v1' });
    expect(payload.tutor.nombres).toBe('María Quispe');
    expect(onSaved).toHaveBeenCalled();
  });
});
