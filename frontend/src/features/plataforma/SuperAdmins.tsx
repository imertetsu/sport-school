import { useEffect, useMemo, useState } from 'react';
import { platformApi, ApiError } from '@/api/client';
import type { SuperAdmin } from '@/api/types';
import { Badge, Button, Card, DataTable, type Column } from '@/components/ui';
import { formatDate } from '@/lib/format';
import { NuevoSuperAdmin } from './NuevoSuperAdmin';
import './Plataforma.css';

// Pantalla Super Admins: lista + alta + activar/desactivar por fila. El backend
// impone la salvaguarda de >=1 super admin activo (409 al intentar desactivar al
// último); aquí mostramos ese mensaje tal cual lo manda el backend.
export function SuperAdmins() {
  const [items, setItems] = useState<SuperAdmin[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [modalOpen, setModalOpen] = useState(false);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    platformApi
      .admins(controller.signal)
      .then((res) => {
        if (active) setItems(res);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setError(err instanceof ApiError ? err.message : 'No se pudieron cargar los super admins');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [reloadKey]);

  async function cambiarActivo(admin: SuperAdmin) {
    const desactivar = admin.activo;
    setActionError(null);
    setPendingId(admin.id);
    try {
      const res = desactivar
        ? await platformApi.desactivarAdmin(admin.id)
        : await platformApi.activarAdmin(admin.id);
      setItems((prev) =>
        prev.map((a) => (a.id === res.id ? { ...a, activo: res.activo } : a)),
      );
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        // Salvaguarda de >=1 super admin activo: mensaje del backend.
        setActionError(err.message || 'Debe quedar al menos un super admin activo.');
      } else {
        setActionError(
          err instanceof ApiError
            ? err.message
            : `No se pudo ${desactivar ? 'desactivar' : 'activar'} el super admin.`,
        );
      }
    } finally {
      setPendingId(null);
    }
  }

  const columns = useMemo<Column<SuperAdmin>[]>(
    () => [
      {
        key: 'nombre',
        header: 'Nombre',
        render: (a) => <span className="plataforma-cell__strong">{a.nombre}</span>,
      },
      {
        key: 'email',
        header: 'Correo',
        render: (a) => <span className="tabular">{a.email}</span>,
      },
      {
        key: 'activo',
        header: 'Estado',
        render: (a) => (
          <Badge tone={a.activo ? 'paid' : 'neutral'}>{a.activo ? 'Activo' : 'Inactivo'}</Badge>
        ),
      },
      {
        key: 'created_at',
        header: 'Creado',
        hideOnNarrow: true,
        render: (a) => <span className="tabular">{formatDate(a.created_at)}</span>,
      },
      {
        key: 'acciones',
        header: '',
        align: 'right',
        render: (a) =>
          a.activo ? (
            <Button
              variant="danger"
              size="sm"
              disabled={pendingId === a.id}
              onClick={() => cambiarActivo(a)}
            >
              {pendingId === a.id ? '…' : 'Desactivar'}
            </Button>
          ) : (
            <Button
              variant="secondary"
              size="sm"
              disabled={pendingId === a.id}
              onClick={() => cambiarActivo(a)}
            >
              {pendingId === a.id ? '…' : 'Activar'}
            </Button>
          ),
      },
    ],
    [pendingId],
  );

  return (
    <div className="plataforma-page">
      <header className="page-head">
        <div>
          <h1 className="page-head__title">Super Admins</h1>
          <p className="page-head__subtitle">
            {loading
              ? 'Cargando…'
              : `${items.length} super admin${items.length === 1 ? '' : 's'}`}
          </p>
        </div>
        <Button variant="primary" onClick={() => setModalOpen(true)}>
          + Crear super admin
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
          ariaLabel="Lista de super admins"
          columns={columns}
          rows={items}
          rowKey={(a) => a.id}
          loading={loading}
          emptyMessage="No hay super admins."
        />
      </Card>

      {modalOpen && (
        <NuevoSuperAdmin
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
