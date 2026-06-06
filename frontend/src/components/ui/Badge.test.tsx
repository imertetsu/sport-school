import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Badge, EstadoBadge } from './Badge';

describe('Badge', () => {
  it('renderiza el contenido con el tono indicado', () => {
    const { container } = render(<Badge tone="overdue">Vencido</Badge>);
    expect(screen.getByText('Vencido')).toBeInTheDocument();
    expect(container.querySelector('.badge--overdue')).not.toBeNull();
  });

  it('usa el tono neutral por defecto', () => {
    const { container } = render(<Badge>—</Badge>);
    expect(container.querySelector('.badge--neutral')).not.toBeNull();
  });
});

describe('EstadoBadge', () => {
  it.each([
    ['PAGADO', 'Pagado', 'badge--paid'],
    ['PENDIENTE', 'Pendiente', 'badge--pending'],
    ['PARCIAL', 'Parcial', 'badge--pending'],
    ['VENCIDO', 'Vencido', 'badge--overdue'],
  ] as const)('mapea %s a etiqueta %s y clase %s', (estado, label, cls) => {
    const { container } = render(<EstadoBadge estado={estado} />);
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(container.querySelector(`.${cls}`)).not.toBeNull();
  });
});
