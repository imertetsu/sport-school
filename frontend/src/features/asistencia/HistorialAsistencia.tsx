import { useEffect, useMemo, useState } from 'react';
import { api, ApiError } from '@/api/client';
import type { SesionHistorialItem } from '@/api/types';
import { Badge, Card, DataTable, type Column } from '@/components/ui';
import { formatDate } from '@/lib/format';

export interface HistorialAsistenciaProps {
  // Categoría de la que se listan las sesiones (GET /asistencia/sesiones).
  categoriaId: string;
  pageSize?: number;
}

// Lista de sesiones de asistencia ya tomadas para una categoría.
export function HistorialAsistencia({ categoriaId, pageSize = 20 }: HistorialAsistenciaProps) {
  const [items, setItems] = useState<SesionHistorialItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!categoriaId) {
      setItems([]);
      return;
    }
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    api
      .asistenciaSesiones(categoriaId, { page: 1, page_size: pageSize }, controller.signal)
      .then((res) => {
        if (active) setItems(res.items);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setItems([]);
        setError(
          err instanceof ApiError ? err.message : 'No se pudo cargar el historial de sesiones',
        );
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [categoriaId, pageSize]);

  const columns = useMemo<Column<SesionHistorialItem>[]>(
    () => [
      {
        key: 'fecha',
        header: 'Fecha',
        render: (s) => (
          <span>
            {formatDate(s.fecha)}
            {s.hora ? ` · ${s.hora}` : ''}
          </span>
        ),
      },
      {
        key: 'presentes',
        header: 'Presentes',
        align: 'center',
        render: (s) => <Badge tone="paid">{s.presentes}</Badge>,
      },
      {
        key: 'ausentes',
        header: 'Ausentes',
        align: 'center',
        render: (s) => <Badge tone="overdue">{s.ausentes}</Badge>,
      },
      {
        key: 'total',
        header: 'Total',
        align: 'right',
        render: (s) => <span className="tabular">{s.total}</span>,
      },
    ],
    [],
  );

  return (
    <>
      {error && (
        <div className="page-error" role="alert">
          {error}
        </div>
      )}
      <Card padded={false}>
        <DataTable
          ariaLabel="Historial de sesiones"
          columns={columns}
          rows={items}
          rowKey={(s) => s.id}
          loading={loading}
          emptyMessage="Aún no hay sesiones registradas para esta categoría"
        />
      </Card>
    </>
  );
}
