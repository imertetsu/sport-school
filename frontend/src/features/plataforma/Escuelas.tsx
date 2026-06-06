import { useEffect, useMemo, useState } from 'react';
import { platformApi, ApiError } from '@/api/client';
import type { Escuela } from '@/api/types';
import { Badge, Button, Card, DataTable, type Column } from '@/components/ui';
import { formatDate } from '@/lib/format';
import { NuevaEscuela } from './NuevaEscuela';
import './Plataforma.css';

// Pantalla Escuelas de la consola de plataforma: lista todas las orgs con su
// estado + alta (org + primer admin) + suspender/reactivar por fila. La verdad la
// impone el backend; aquí gateamos la UI según el estado.
export function Escuelas() {
  const [items, setItems] = useState<Escuela[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [modalOpen, setModalOpen] = useState(false);
  // id de la escuela cuyo cambio de estado está en curso (deshabilita su acción).
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    platformApi
      .escuelas(controller.signal)
      .then((res) => {
        if (active) setItems(res);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setError(err instanceof ApiError ? err.message : 'No se pudieron cargar las escuelas');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [reloadKey]);

  async function cambiarEstado(escuela: Escuela) {
    const suspender = escuela.estado === 'ACTIVA';
    const verbo = suspender ? 'suspender' : 'reactivar';
    const ok = window.confirm(
      suspender
        ? `¿Suspender "${escuela.nombre}"? Se bloqueará el acceso de la escuela y se pausará su cobranza.`
        : `¿Reactivar "${escuela.nombre}"? Volverá a tener acceso y cobranza.`,
    );
    if (!ok) return;

    setActionError(null);
    setPendingId(escuela.id);
    try {
      const res = suspender
        ? await platformApi.suspenderEscuela(escuela.id)
        : await platformApi.reactivarEscuela(escuela.id);
      // Actualiza el estado de esa fila en memoria (idempotente en el backend).
      setItems((prev) =>
        prev.map((e) => (e.id === res.id ? { ...e, estado: res.estado } : e)),
      );
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : `No se pudo ${verbo} la escuela.`,
      );
    } finally {
      setPendingId(null);
    }
  }

  const columns = useMemo<Column<Escuela>[]>(
    () => [
      {
        key: 'nombre',
        header: 'Escuela',
        render: (e) => <span className="plataforma-cell__strong">{e.nombre}</span>,
      },
      {
        key: 'pais',
        header: 'País',
        hideOnNarrow: true,
        render: (e) => e.pais ?? <span className="plataforma-cell__muted">—</span>,
      },
      {
        key: 'moneda',
        header: 'Moneda',
        hideOnNarrow: true,
        render: (e) => e.moneda ?? <span className="plataforma-cell__muted">—</span>,
      },
      {
        key: 'estado',
        header: 'Estado',
        render: (e) => (
          <Badge tone={e.estado === 'ACTIVA' ? 'paid' : 'overdue'}>
            {e.estado === 'ACTIVA' ? 'Activa' : 'Suspendida'}
          </Badge>
        ),
      },
      {
        key: 'created_at',
        header: 'Creada',
        hideOnNarrow: true,
        render: (e) => <span className="tabular">{formatDate(e.created_at)}</span>,
      },
      {
        key: 'acciones',
        header: '',
        align: 'right',
        render: (e) =>
          e.estado === 'ACTIVA' ? (
            <Button
              variant="danger"
              size="sm"
              disabled={pendingId === e.id}
              onClick={() => cambiarEstado(e)}
            >
              {pendingId === e.id ? '…' : 'Suspender'}
            </Button>
          ) : (
            <Button
              variant="secondary"
              size="sm"
              disabled={pendingId === e.id}
              onClick={() => cambiarEstado(e)}
            >
              {pendingId === e.id ? '…' : 'Reactivar'}
            </Button>
          ),
      },
    ],
    // cambiarEstado se recrea por render; las columnas solo dependen de pendingId.
    [pendingId],
  );

  return (
    <div className="plataforma-page">
      <header className="page-head">
        <div>
          <h1 className="page-head__title">Escuelas</h1>
          <p className="page-head__subtitle">
            {loading
              ? 'Cargando…'
              : `${items.length} escuela${items.length === 1 ? '' : 's'} registrada${
                  items.length === 1 ? '' : 's'
                }`}
          </p>
        </div>
        <Button variant="primary" onClick={() => setModalOpen(true)}>
          + Crear escuela
        </Button>
      </header>

      {error && (
        <div className="page-error" role="alert">
          {error}
        </div>
      )}
      {actionError && (
        <div className="page-error" role="alert">
          {actionError}
        </div>
      )}

      <Card padded={false}>
        <DataTable
          ariaLabel="Lista de escuelas"
          columns={columns}
          rows={items}
          rowKey={(e) => e.id}
          loading={loading}
          emptyMessage="Aún no hay escuelas. Crea la primera."
        />
      </Card>

      {modalOpen && (
        <NuevaEscuela
          onClose={() => setModalOpen(false)}
          onCreated={() => {
            setModalOpen(false);
            setReloadKey((k) => k + 1);
          }}
        />
      )}
    </div>
  );
}
