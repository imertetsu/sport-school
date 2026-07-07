import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import { ToastProvider, useToast } from './Toast';

// Botón de prueba: dispara un toast con la variante indicada al hacer click.
function Disparador({ variant }: { variant: 'success' | 'error' | 'info' | 'warning' }) {
  const toast = useToast();
  return (
    <button onClick={() => toast[variant](`msg-${variant}`)}>lanzar</button>
  );
}

describe('Toast', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  it('muestra el mensaje al dispararlo y aplica la clase de la variante', () => {
    const { container } = render(
      <ToastProvider>
        <Disparador variant="success" />
      </ToastProvider>,
    );
    act(() => {
      screen.getByText('lanzar').click();
    });
    expect(screen.getByText('msg-success')).toBeInTheDocument();
    expect(container.querySelector('.toast--success')).not.toBeNull();
  });

  it('se auto-oculta pasado el tiempo de vida', () => {
    render(
      <ToastProvider>
        <Disparador variant="info" />
      </ToastProvider>,
    );
    act(() => {
      screen.getByText('lanzar').click();
    });
    expect(screen.getByText('msg-info')).toBeInTheDocument();
    // Duración info (3600ms) + animación de salida (200ms).
    act(() => {
      vi.advanceTimersByTime(3600 + 250);
    });
    expect(screen.queryByText('msg-info')).not.toBeInTheDocument();
  });

  it('el error usa role=alert (aria-live asertivo)', () => {
    render(
      <ToastProvider>
        <Disparador variant="error" />
      </ToastProvider>,
    );
    act(() => {
      screen.getByText('lanzar').click();
    });
    expect(screen.getByRole('alert')).toHaveTextContent('msg-error');
  });

  it('useToast fuera del provider es un no-op (no revienta)', () => {
    // Sin ToastProvider: el contexto por defecto es no-op; no debe lanzar.
    expect(() =>
      render(<Disparador variant="success" />),
    ).not.toThrow();
    act(() => {
      screen.getByText('lanzar').click();
    });
    // No se renderiza ningún toast porque no hay viewport montado.
    expect(screen.queryByText('msg-success')).not.toBeInTheDocument();
  });
});
