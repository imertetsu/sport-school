import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DataTable, type Column } from './DataTable';

interface Row {
  id: string;
  nombre: string;
  ci: string;
}

const columns: Column<Row>[] = [
  { key: 'nombre', header: 'Nombre', render: (r) => r.nombre },
  { key: 'ci', header: 'CI', hideOnNarrow: true, render: (r) => r.ci },
];

const rows: Row[] = [
  { id: '1', nombre: 'Mateo Quispe', ci: '9123456 LP' },
  { id: '2', nombre: 'Valentina Condori', ci: '9876543 CB' },
];

describe('DataTable', () => {
  it('renderiza encabezados y filas', () => {
    render(<DataTable columns={columns} rows={rows} rowKey={(r) => r.id} />);
    expect(screen.getByText('Nombre')).toBeInTheDocument();
    expect(screen.getByText('Mateo Quispe')).toBeInTheDocument();
    expect(screen.getByText('Valentina Condori')).toBeInTheDocument();
  });

  it('muestra el mensaje vacío cuando no hay filas', () => {
    render(
      <DataTable
        columns={columns}
        rows={[]}
        rowKey={(r) => r.id}
        emptyMessage="Sin deportistas"
      />,
    );
    expect(screen.getByText('Sin deportistas')).toBeInTheDocument();
  });

  it('muestra el estado de carga', () => {
    render(<DataTable columns={columns} rows={[]} rowKey={(r) => r.id} loading />);
    expect(screen.getByText('Cargando…')).toBeInTheDocument();
  });

  it('marca columnas ocultables con la clase responsive', () => {
    const { container } = render(
      <DataTable columns={columns} rows={rows} rowKey={(r) => r.id} />,
    );
    // 1 header + 2 celdas de la columna CI = 3 elementos con col-hide-narrow.
    expect(container.querySelectorAll('.col-hide-narrow').length).toBe(3);
  });

  it('dispara onRowClick al pulsar una fila', async () => {
    const onRowClick = vi.fn();
    render(
      <DataTable
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        onRowClick={onRowClick}
      />,
    );
    await userEvent.click(screen.getByText('Mateo Quispe'));
    expect(onRowClick).toHaveBeenCalledWith(rows[0]);
  });
});
