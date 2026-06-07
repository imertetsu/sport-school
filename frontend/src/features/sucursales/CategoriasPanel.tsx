import { useEffect, useMemo, useState } from 'react';
import { api, ApiError } from '@/api/client';
import type { Categoria, Nivel, Sucursal } from '@/api/types';
import { Badge, Button, Card, DataTable, type Column } from '@/components/ui';
import { NuevaCategoria, type CategoriaEditable } from './NuevaCategoria';

// Etiquetas legibles para el nivel (el valor crudo es el del CHECK de BD).
const NIVEL_LABEL: Record<Nivel, string> = {
  PRINCIPIANTE: 'Principiante',
  INTERMEDIO: 'Intermedio',
  AVANZADO: 'Avanzado',
};

export interface CategoriasPanelProps {
  // Sucursal cuyas categorías se gestionan (el alta fija sucursal_id a esta).
  sucursal: Sucursal;
}

// Gestión de categorías de una sucursal (SOLO ADMIN). Lista sus categorías
// (GET /categorias?sucursal_id=) con alta/edición/baja. La baja está protegida:
// 409 si la categoría está en uso (deportistas/horarios/sesiones) -> mensaje del
// backend inline, sin cascada. Se monta como sección dentro de Sucursales.
export function CategoriasPanel({ sucursal }: CategoriasPanelProps) {
  const [categorias, setCategorias] = useState<Categoria[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  // --- Alta / edición (modal) ---
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<CategoriaEditable | null>(null);

  // --- Baja protegida con confirmación inline ---
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    api
      .categorias(sucursal.id, controller.signal)
      .then((data) => {
        if (active) setCategorias(data);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setError(
          err instanceof ApiError ? err.message : 'No se pudieron cargar las categorías',
        );
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [sucursal.id, reloadKey]);

  function recargar() {
    setReloadKey((k) => k + 1);
  }

  function abrirNueva() {
    setEditing(null);
    setModalOpen(true);
  }

  function abrirEditar(c: Categoria) {
    setEditing({
      id: c.id,
      nombre: c.nombre,
      nivel: c.nivel,
      rango_edad: c.rango_edad,
      // Precarga la disciplina (S2): prefiere disciplina_id; si solo viene la ref
      // embebida, usa su id. null/undefined => "— Sin disciplina —".
      disciplina_id: c.disciplina_id ?? c.disciplina?.id ?? null,
    });
    setModalOpen(true);
  }

  async function eliminar(id: string) {
    setDeletingId(id);
    setError(null);
    try {
      await api.eliminarCategoria(id);
      setConfirmId(null);
      recargar();
    } catch (err) {
      // 409: la categoría está en uso (deportistas/horarios/sesiones). Mostramos el
      // mensaje del backend inline, sin borrar en cascada.
      if (err instanceof ApiError) {
        if (err.status === 409) {
          setError(err.message);
        } else if (err.isForbidden) {
          setError('No tienes permiso para eliminar categorías.');
        } else {
          setError(err.message);
        }
      } else {
        setError('No se pudo eliminar la categoría.');
      }
      setConfirmId(null);
    } finally {
      setDeletingId(null);
    }
  }

  const columns = useMemo<Column<Categoria>[]>(
    () => [
      {
        key: 'nombre',
        header: 'Categoría',
        render: (c) => <span className="cat-cell__nombre">{c.nombre}</span>,
      },
      {
        key: 'nivel',
        header: 'Nivel',
        render: (c) => <Badge tone="accent">{NIVEL_LABEL[c.nivel]}</Badge>,
      },
      {
        key: 'rango_edad',
        header: 'Rango de edad',
        hideOnNarrow: true,
        render: (c) =>
          c.rango_edad ? c.rango_edad : <span className="cat-cell__muted">—</span>,
      },
      {
        key: 'acciones',
        header: '',
        align: 'right',
        render: (c) => (
          <div className="suc-acciones">
            <Button variant="ghost" size="sm" onClick={() => abrirEditar(c)}>
              Editar
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setConfirmId(c.id)}
              disabled={deletingId === c.id}
            >
              Eliminar
            </Button>
          </div>
        ),
      },
    ],
    [deletingId],
  );

  const total = categorias.length;

  return (
    <Card
      className="sucursales__cat-panel"
      title={`Categorías de ${sucursal.nombre}`}
      actions={
        <Button variant="primary" size="sm" onClick={abrirNueva}>
          + Nueva categoría
        </Button>
      }
    >
      <p className="sucursales__cat-sub">
        {loading
          ? 'Cargando…'
          : `${total} categoría${total === 1 ? '' : 's'} en esta sucursal`}
      </p>

      {error && (
        <div className="page-error" role="alert">
          {error}
        </div>
      )}

      <DataTable
        ariaLabel={`Categorías de ${sucursal.nombre}`}
        columns={columns}
        rows={categorias}
        rowKey={(c) => c.id}
        loading={loading}
        emptyMessage="Esta sucursal aún no tiene categorías."
      />

      {confirmId && (
        <div
          className="sucursales__confirm"
          role="alertdialog"
          aria-label="Confirmar eliminación de categoría"
        >
          <span>
            ¿Eliminar la categoría “
            {categorias.find((c) => c.id === confirmId)?.nombre ?? ''}”? No se podrá
            si tiene deportistas, horarios o sesiones asociados.
          </span>
          <div className="sucursales__confirm-actions">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setConfirmId(null)}
              disabled={deletingId === confirmId}
            >
              Cancelar
            </Button>
            <Button
              variant="danger"
              size="sm"
              onClick={() => eliminar(confirmId)}
              disabled={deletingId === confirmId}
            >
              {deletingId === confirmId ? 'Eliminando…' : 'Eliminar'}
            </Button>
          </div>
        </div>
      )}

      {modalOpen && (
        <NuevaCategoria
          sucursalId={sucursal.id}
          categoria={editing}
          onClose={() => setModalOpen(false)}
          onSaved={() => {
            setModalOpen(false);
            setEditing(null);
            recargar();
          }}
        />
      )}
    </Card>
  );
}
