import { useEffect, useMemo, useState } from 'react';
import { platformApi, ApiError } from '@/api/client';
import type { Disciplina } from '@/api/types';
import { Badge, Button, Card, DataTable, type Column } from '@/components/ui';
import { formatDate } from '@/lib/format';
import { NuevaDisciplina } from './NuevaDisciplina';
import './Plataforma.css';

// Pantalla Disciplinas (consola de plataforma, SUPERADMIN): catálogo GLOBAL.
// Lista (activas + inactivas) + alta + activar/desactivar por fila. El retiro de
// una disciplina es soft-delete (PUT activo=false), nunca hard delete (FK RESTRICT
// desde categoría). Espejo de SuperAdmins.
export function Disciplinas() {
  const [items, setItems] = useState<Disciplina[]>([]);
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
      .disciplinas(controller.signal)
      .then((res) => {
        if (active) setItems(res);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setError(err instanceof ApiError ? err.message : 'No se pudieron cargar las disciplinas');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [reloadKey]);

  async function cambiarActivo(disciplina: Disciplina) {
    const desactivar = disciplina.activo;
    setActionError(null);
    setPendingId(disciplina.id);
    try {
      // Toggle = soft-delete/reactivar vía PUT activo. El backend valida la FK
      // RESTRICT (409 si está en uso por una categoría); mostramos su mensaje.
      const res = await platformApi.actualizarDisciplina(disciplina.id, {
        activo: !desactivar,
      });
      setItems((prev) =>
        prev.map((d) => (d.id === res.id ? { ...d, activo: res.activo } : d)),
      );
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        // En uso por una categoría (FK RESTRICT): mensaje del backend.
        setActionError(err.message || 'No se puede retirar: la disciplina está en uso.');
      } else {
        setActionError(
          err instanceof ApiError
            ? err.message
            : `No se pudo ${desactivar ? 'retirar' : 'reactivar'} la disciplina.`,
        );
      }
    } finally {
      setPendingId(null);
    }
  }

  const columns = useMemo<Column<Disciplina>[]>(
    () => [
      {
        key: 'nombre',
        header: 'Nombre',
        render: (d) => <span className="plataforma-cell__strong">{d.nombre}</span>,
      },
      {
        key: 'activo',
        header: 'Estado',
        render: (d) => (
          <Badge tone={d.activo ? 'paid' : 'neutral'}>{d.activo ? 'Activa' : 'Inactiva'}</Badge>
        ),
      },
      {
        key: 'created_at',
        header: 'Creada',
        hideOnNarrow: true,
        render: (d) => <span className="tabular">{formatDate(d.created_at)}</span>,
      },
      {
        key: 'acciones',
        header: '',
        align: 'right',
        render: (d) =>
          d.activo ? (
            <Button
              variant="danger"
              size="sm"
              disabled={pendingId === d.id}
              onClick={() => cambiarActivo(d)}
            >
              {pendingId === d.id ? '…' : 'Retirar'}
            </Button>
          ) : (
            <Button
              variant="secondary"
              size="sm"
              disabled={pendingId === d.id}
              onClick={() => cambiarActivo(d)}
            >
              {pendingId === d.id ? '…' : 'Reactivar'}
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
          <h1 className="page-head__title">Disciplinas</h1>
          <p className="page-head__subtitle">
            {loading
              ? 'Cargando…'
              : `${items.length} disciplina${items.length === 1 ? '' : 's'}`}
          </p>
        </div>
        <Button variant="primary" onClick={() => setModalOpen(true)}>
          + Crear disciplina
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
          ariaLabel="Lista de disciplinas"
          columns={columns}
          rows={items}
          rowKey={(d) => d.id}
          loading={loading}
          emptyMessage="No hay disciplinas."
        />
      </Card>

      {modalOpen && (
        <NuevaDisciplina
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
