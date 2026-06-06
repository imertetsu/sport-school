import { useEffect, useMemo, useState } from 'react';
import { api, ApiError } from '@/api/client';
import type { EntrenadorOut } from '@/api/types';
import { Badge, Button, Card, DataTable, type Column } from '@/components/ui';
import { NuevoEntrenador } from './NuevoEntrenador';
import './Entrenadores.css';

// Pantalla de gestión de entrenadores (Epic B). SOLO ADMIN (la ruta y el item de
// nav ya están gateados; el backend da 403 a ENTRENADOR en las escrituras).
// Lista (nombres, email, especialidad, chips de disciplinas, badge activo) +
// alta + edición (incl. baja/reactivación con activo).
export function Entrenadores() {
  const [items, setItems] = useState<EntrenadorOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filtro: mostrar también los dados de baja (activo=false).
  const [soloActivos, setSoloActivos] = useState(false);

  // Alta/edición + recarga.
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<EntrenadorOut | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    api
      .listEntrenadores(soloActivos || undefined, controller.signal)
      .then((data) => {
        if (active) setItems(data);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setError(
          err instanceof ApiError ? err.message : 'No se pudieron cargar los entrenadores',
        );
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [soloActivos, reloadKey]);

  function recargar() {
    setReloadKey((k) => k + 1);
  }

  function abrirNuevo() {
    setEditing(null);
    setModalOpen(true);
  }

  function abrirEditar(entrenador: EntrenadorOut) {
    setEditing(entrenador);
    setModalOpen(true);
  }

  const total = items.length;

  const columns = useMemo<Column<EntrenadorOut>[]>(
    () => [
      {
        key: 'nombres',
        header: 'Entrenador',
        render: (e) => (
          <div className="entrenador-cell">
            <span className="entrenador-cell__nombre">{e.nombres}</span>
            <span className="entrenador-cell__email">{e.email}</span>
          </div>
        ),
      },
      {
        key: 'especialidad',
        header: 'Especialidad',
        hideOnNarrow: true,
        render: (e) =>
          e.especialidad ? (
            e.especialidad
          ) : (
            <span className="entrenador-cell__muted">—</span>
          ),
      },
      {
        key: 'disciplinas',
        header: 'Disciplinas',
        render: (e) =>
          e.disciplinas.length > 0 ? (
            <div className="entrenador-chips">
              {e.disciplinas.map((d) => (
                <Badge key={d} tone="accent">
                  {d}
                </Badge>
              ))}
            </div>
          ) : (
            <span className="entrenador-cell__muted">—</span>
          ),
      },
      {
        key: 'activo',
        header: 'Estado',
        align: 'center',
        render: (e) =>
          e.activo ? (
            <Badge tone="paid">Activo</Badge>
          ) : (
            <Badge tone="neutral">Inactivo</Badge>
          ),
      },
      {
        key: 'acciones',
        header: '',
        align: 'right',
        render: (e) => (
          <div className="entrenadores__acciones">
            <Button variant="ghost" size="sm" onClick={() => abrirEditar(e)}>
              Editar
            </Button>
          </div>
        ),
      },
    ],
    [],
  );

  return (
    <div className="entrenadores">
      <header className="page-head">
        <div>
          <h1 className="page-head__title">Entrenadores</h1>
          <p className="page-head__subtitle">
            {loading
              ? 'Cargando…'
              : `${total} entrenador${total === 1 ? '' : 'es'}`}
          </p>
        </div>
        <Button variant="primary" onClick={abrirNuevo}>
          + Nuevo entrenador
        </Button>
      </header>

      {error && (
        <div className="page-error" role="alert">
          {error}
        </div>
      )}

      <label className="entrenadores__toggle">
        <input
          type="checkbox"
          checked={soloActivos}
          onChange={(e) => setSoloActivos(e.target.checked)}
        />
        Mostrar solo activos
      </label>

      <Card padded={false}>
        <DataTable
          ariaLabel="Lista de entrenadores"
          columns={columns}
          rows={items}
          rowKey={(e) => e.id}
          loading={loading}
          emptyMessage="Aún no hay entrenadores registrados"
        />
      </Card>

      {modalOpen && (
        <NuevoEntrenador
          entrenador={editing}
          onClose={() => setModalOpen(false)}
          onSaved={() => {
            setModalOpen(false);
            setEditing(null);
            recargar();
          }}
        />
      )}
    </div>
  );
}
