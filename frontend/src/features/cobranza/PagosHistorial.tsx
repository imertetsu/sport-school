import { useEffect, useMemo, useState } from 'react';
import { api, ApiError } from '@/api/client';
import type { CuotaListItem, MetodoPago } from '@/api/types';
import {
  Avatar,
  Card,
  DataTable,
  EstadoBadge,
  type Column,
} from '@/components/ui';
import { useSucursales } from '@/components/shell/SucursalContext';
import { formatDate, formatMoney } from '@/lib/format';
import './PanelCobranza.css';

const METODO_LABEL: Record<MetodoPago, string> = {
  EFECTIVO: 'Efectivo',
  QR: 'QR',
};

// Historial simple de pagos: cuotas PAGADO (las que tienen método registrado).
export function PagosHistorial() {
  const { selected: sucursalId } = useSucursales();
  const [items, setItems] = useState<CuotaListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    api
      .cuotas(
        {
          estado: 'PAGADO',
          sucursal_id: sucursalId || undefined,
          page: 1,
          page_size: 50,
        },
        controller.signal,
      )
      .then((res) => {
        if (active) setItems(res.items);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setError(err instanceof ApiError ? err.message : 'No se pudieron cargar los pagos');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [sucursalId]);

  const columns = useMemo<Column<CuotaListItem>[]>(
    () => [
      {
        key: 'alumno',
        header: 'Alumno',
        render: (c) => (
          <div className="cuota-cell">
            <Avatar name={c.alumno.nombre_completo} size="md" />
            <div className="cuota-cell__text">
              <span className="cuota-cell__name">{c.alumno.nombre_completo}</span>
              <span className="cuota-cell__meta">{c.categoria.nombre}</span>
            </div>
          </div>
        ),
      },
      {
        key: 'sucursal',
        header: 'Sucursal',
        hideOnNarrow: true,
        render: (c) => c.sucursal.nombre,
      },
      {
        key: 'estado',
        header: 'Estado',
        align: 'center',
        render: (c) => <EstadoBadge estado={c.estado} />,
      },
      {
        key: 'monto',
        header: 'Monto',
        align: 'right',
        render: (c) => <span className="tabular">{formatMoney(c.monto)}</span>,
      },
      {
        key: 'vence_el',
        header: 'Período vence',
        hideOnNarrow: true,
        render: (c) => formatDate(c.vence_el),
      },
      {
        key: 'metodo',
        header: 'Método',
        render: (c) =>
          c.ultimo_metodo ? (
            <span className="cuota-cell__metodo">{METODO_LABEL[c.ultimo_metodo]}</span>
          ) : (
            <span className="cuota-cell__metodo cuota-cell__metodo--empty">—</span>
          ),
      },
    ],
    [],
  );

  return (
    <div className="panel-cobranza">
      <header className="page-head">
        <div>
          <h1 className="page-head__title">Pagos</h1>
          <p className="page-head__subtitle">
            {loading ? 'Cargando…' : `${items.length} pago${items.length === 1 ? '' : 's'} registrado${items.length === 1 ? '' : 's'}`}
          </p>
        </div>
      </header>

      {error && (
        <div className="page-error" role="alert">
          {error}
        </div>
      )}

      <Card padded={false}>
        <DataTable
          ariaLabel="Historial de pagos"
          columns={columns}
          rows={items}
          rowKey={(c) => c.id}
          loading={loading}
          emptyMessage="Aún no hay pagos registrados"
        />
      </Card>
    </div>
  );
}
