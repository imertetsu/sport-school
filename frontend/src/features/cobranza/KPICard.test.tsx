import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { KPICard } from './KPICard';

describe('KPICard', () => {
  it('renderiza etiqueta, valor y pista', () => {
    render(<KPICard label="Ingresos del mes" value="Bs 28.450" hint="vs mayo" />);
    expect(screen.getByText('Ingresos del mes')).toBeInTheDocument();
    expect(screen.getByText('Bs 28.450')).toBeInTheDocument();
    expect(screen.getByText('vs mayo')).toBeInTheDocument();
  });

  it('resalta en rojo la card de cuotas vencidas (tone=overdue)', () => {
    const { container } = render(
      <KPICard label="Cuotas vencidas" value="7" tone="overdue" />,
    );
    expect(container.querySelector('.kpi-card--overdue')).not.toBeNull();
  });

  it('muestra placeholder mientras carga y oculta la pista', () => {
    render(<KPICard label="Alumnos activos" value="142" hint="en 2 sucursales" loading />);
    expect(screen.getByText('…')).toBeInTheDocument();
    expect(screen.queryByText('en 2 sucursales')).not.toBeInTheDocument();
  });
});
