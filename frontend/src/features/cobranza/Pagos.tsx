import { useEffect, useMemo, useState } from 'react';
import { api, ApiError } from '@/api/client';
import type { MetodoPago, PagoListItem } from '@/api/types';
import { Badge, Button, Card, DataTable, type BadgeTone, type Column } from '@/components/ui';
import { formatDate, formatMoney } from '@/lib/format';
import { AnularPagoModal } from './AnularPagoModal';
import './Pagos.css';

const PAGE_SIZE = 20;

const METODO_LABEL: Record<MetodoPago, string> = {
  EFECTIVO: 'Efectivo',
  QR: 'QR',
};

// Etiqueta + tono del estado del PAGO (distinto del estado de la CUOTA).
// CONFIRMADO = verde; PENDIENTE = ámbar; FALLIDO = rojo; ANULADO = neutro (reversa).
const ESTADO_PAGO: Record<PagoListItem['estado'], { label: string; tone: BadgeTone }> = {
  PENDIENTE: { label: 'Pendiente', tone: 'pending' },
  CONFIRMADO: { label: 'Confirmado', tone: 'paid' },
  FALLIDO: { label: 'Fallido', tone: 'overdue' },
  ANULADO: { label: 'Anulado', tone: 'neutral' },
};

// Vista "Pagos" (epic anular-pago, C6) — SOLO ADMIN. La ruta /pagos-lista está
// gateada con RoleRoute allow={['ADMIN']}; el backend además impone require_role y
// scopea por RLS al org del token. Lista paginada (created_at DESC) que sirve de
// punto de acceso al botón "Anular" sobre pagos en efectivo CONFIRMADOS.
export function Pagos() {
  const [items, setItems] = useState<PagoListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  // Pago en proceso de anulación (abre el modal). null = modal cerrado.
  const [anulando, setAnulando] = useState<PagoListItem | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    api
      .listarPagos(page, PAGE_SIZE, undefined, controller.signal)
      .then((res) => {
        if (!active) return;
        setItems(res.items);
        setTotal(res.total);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        if (err instanceof ApiError && err.isForbidden) {
          setError('No tienes permiso para ver los pagos.');
        } else {
          setError(err instanceof ApiError ? err.message : 'No se pudieron cargar los pagos.');
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [page, reloadKey]);

  function recargar() {
    setReloadKey((k) => k + 1);
  }

  const columns = useMemo<Column<PagoListItem>[]>(
    () => [
      {
        key: 'deportista',
        header: 'Deportista',
        render: (p) => (
          <span className="pagos-cell__name">{p.deportista_nombre ?? '—'}</span>
        ),
      },
      {
        key: 'monto',
        header: 'Monto',
        align: 'right',
        render: (p) => <span className="tabular">{formatMoney(p.monto)}</span>,
      },
      {
        key: 'metodo',
        header: 'Método',
        render: (p) => METODO_LABEL[p.metodo] ?? p.metodo,
      },
      {
        key: 'estado',
        header: 'Estado',
        align: 'center',
        render: (p) => {
          const e = ESTADO_PAGO[p.estado] ?? { label: p.estado, tone: 'neutral' as BadgeTone };
          return (
            <div className="pagos-cell__estado">
              <Badge tone={e.tone}>{e.label}</Badge>
              {p.estado === 'ANULADO' && p.motivo_anulacion && (
                <span className="pagos-cell__motivo" title={p.motivo_anulacion}>
                  {p.motivo_anulacion}
                </span>
              )}
            </div>
          );
        },
      },
      {
        key: 'fecha',
        header: 'Fecha',
        hideOnNarrow: true,
        render: (p) => formatDate(p.fecha),
      },
      {
        key: 'numero_recibo',
        header: 'N° recibo',
        hideOnNarrow: true,
        render: (p) => <span className="tabular">{p.numero_recibo ?? '—'}</span>,
      },
      {
        key: 'acciones',
        header: '',
        align: 'right',
        render: (p) =>
          p.anulable ? (
            <Button variant="ghost" size="sm" onClick={() => setAnulando(p)}>
              Anular
            </Button>
          ) : null,
      },
    ],
    [],
  );

  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="pagos-lista">
      <header className="page-head">
        <div>
          <h1 className="page-head__title">Pagos</h1>
          <p className="page-head__subtitle">
            {loading
              ? 'Cargando…'
              : `${total} pago${total === 1 ? '' : 's'} registrado${total === 1 ? '' : 's'}`}
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
          ariaLabel="Lista de pagos"
          columns={columns}
          rows={items}
          rowKey={(p) => p.id}
          loading={loading}
          emptyMessage="Aún no hay pagos registrados"
        />
      </Card>

      {total > PAGE_SIZE && (
        <div className="pagos-lista__pager">
          <Button
            variant="secondary"
            size="sm"
            disabled={page <= 1 || loading}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            Anterior
          </Button>
          <span>
            Página {page} de {lastPage}
          </span>
          <Button
            variant="secondary"
            size="sm"
            disabled={page >= lastPage || loading}
            onClick={() => setPage((p) => Math.min(lastPage, p + 1))}
          >
            Siguiente
          </Button>
        </div>
      )}

      {anulando && (
        <AnularPagoModal
          pago={anulando}
          onClose={() => setAnulando(null)}
          onAnulado={() => {
            setAnulando(null);
            recargar();
          }}
        />
      )}
    </div>
  );
}
