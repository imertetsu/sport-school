import type { ReactNode } from 'react';
import './DataTable.css';

export interface Column<T> {
  key: string;
  header: ReactNode;
  // Renderiza la celda para una fila.
  render: (row: T) => ReactNode;
  // Si true, la columna se oculta en anchos medianos/estrechos (responsive).
  hideOnNarrow?: boolean;
  align?: 'left' | 'right' | 'center';
  width?: string;
}

export interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  loading?: boolean;
  emptyMessage?: ReactNode;
  ariaLabel?: string;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  loading = false,
  emptyMessage = 'Sin resultados',
  ariaLabel,
}: DataTableProps<T>) {
  return (
    <div className="datatable-wrap">
      <table className="datatable" aria-label={ariaLabel}>
        <thead>
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                className={[
                  col.hideOnNarrow ? 'col-hide-narrow' : '',
                  col.align ? `align-${col.align}` : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
                style={col.width ? { width: col.width } : undefined}
                scope="col"
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {loading ? (
            <tr>
              <td className="datatable__state" colSpan={columns.length}>
                Cargando…
              </td>
            </tr>
          ) : rows.length === 0 ? (
            <tr>
              <td className="datatable__state" colSpan={columns.length}>
                {emptyMessage}
              </td>
            </tr>
          ) : (
            rows.map((row) => (
              <tr
                key={rowKey(row)}
                className={onRowClick ? 'datatable__row--clickable' : undefined}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                tabIndex={onRowClick ? 0 : undefined}
                onKeyDown={
                  onRowClick
                    ? (e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          onRowClick(row);
                        }
                      }
                    : undefined
                }
              >
                {columns.map((col) => (
                  <td
                    key={col.key}
                    className={[
                      col.hideOnNarrow ? 'col-hide-narrow' : '',
                      col.align ? `align-${col.align}` : '',
                    ]
                      .filter(Boolean)
                      .join(' ')}
                  >
                    {col.render(row)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
