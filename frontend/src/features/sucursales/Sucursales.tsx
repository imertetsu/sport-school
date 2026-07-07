import { useEffect, useMemo, useState } from 'react';
import { api, ApiError } from '@/api/client';
import type { Sucursal } from '@/api/types';
import { Button, Card, DataTable, useToast, type Column } from '@/components/ui';
import { NuevaSucursal, type SucursalEditable } from './NuevaSucursal';
import { CategoriasPanel } from './CategoriasPanel';
import './Sucursales.css';

// Gestión de sucursales y categorías (epic Sucursales-Recibo, Sesión C). SOLO
// ADMIN: la ruta está gateada con RoleRoute allow={['ADMIN']} y el backend
// impone require_role (403 para ENTRENADOR). Lista + alta/edición/baja, con baja
// protegida (409 si la sucursal está en uso) reflejada inline. Al elegir una
// sucursal se despliega la gestión de sus categorías.
export function Sucursales() {
  const toast = useToast();
  const [sucursales, setSucursales] = useState<Sucursal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  // --- Alta / edición (modal) ---
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<SucursalEditable | null>(null);

  // --- Baja protegida con confirmación inline ---
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  // --- Sucursal seleccionada para gestionar sus categorías ---
  const [activeId, setActiveId] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    api
      .sucursales(controller.signal)
      .then((data) => {
        if (!active) return;
        setSucursales(data);
        // Si la sucursal activa ya no existe, cierra su panel de categorías.
        setActiveId((prev) => (prev && data.some((s) => s.id === prev) ? prev : null));
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setError(
          err instanceof ApiError ? err.message : 'No se pudieron cargar las sucursales',
        );
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [reloadKey]);

  function recargar() {
    setReloadKey((k) => k + 1);
  }

  function abrirNueva() {
    setEditing(null);
    setModalOpen(true);
  }

  function abrirEditar(s: Sucursal) {
    setEditing({ id: s.id, nombre: s.nombre, direccion: s.direccion });
    setModalOpen(true);
  }

  async function eliminar(id: string) {
    setDeletingId(id);
    setError(null);
    try {
      await api.eliminarSucursal(id);
      toast.success('Sucursal eliminada');
      setConfirmId(null);
      if (activeId === id) setActiveId(null);
      recargar();
    } catch (err) {
      // 409: la sucursal está en uso (categorías/deportistas). Mostramos el mensaje
      // del backend ("…tiene N categorías / M deportistas…") sin borrar en cascada.
      let msg: string;
      if (err instanceof ApiError) {
        if (err.status === 409) {
          msg = err.message;
        } else if (err.isForbidden) {
          msg = 'No tienes permiso para eliminar sucursales.';
        } else {
          msg = err.message;
        }
      } else {
        msg = 'No se pudo eliminar la sucursal.';
      }
      setError(msg);
      toast.error(msg);
      setConfirmId(null);
    } finally {
      setDeletingId(null);
    }
  }

  const columns = useMemo<Column<Sucursal>[]>(
    () => [
      {
        key: 'nombre',
        header: 'Sucursal',
        render: (s) => (
          <div className="suc-cell">
            <span className="suc-cell__nombre">{s.nombre}</span>
            {s.direccion ? (
              <span className="suc-cell__dir">{s.direccion}</span>
            ) : (
              <span className="suc-cell__muted">Sin dirección</span>
            )}
          </div>
        ),
      },
      {
        key: 'acciones',
        header: '',
        align: 'right',
        render: (s) => (
          <div className="suc-acciones">
            <Button
              variant={activeId === s.id ? 'primary' : 'secondary'}
              size="sm"
              onClick={() => setActiveId((prev) => (prev === s.id ? null : s.id))}
            >
              {activeId === s.id ? 'Ocultar categorías' : 'Categorías'}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => abrirEditar(s)}>
              Editar
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setConfirmId(s.id)}
              disabled={deletingId === s.id}
            >
              Eliminar
            </Button>
          </div>
        ),
      },
    ],
    [activeId, deletingId],
  );

  const total = sucursales.length;
  const activa = activeId ? sucursales.find((s) => s.id === activeId) ?? null : null;

  return (
    <div className="sucursales">
      <header className="page-head">
        <div>
          <h1 className="page-head__title">Sucursales</h1>
          <p className="page-head__subtitle">
            {loading
              ? 'Cargando…'
              : `${total} sucursal${total === 1 ? '' : 'es'}`}
          </p>
        </div>
        <Button variant="primary" onClick={abrirNueva}>
          + Nueva sucursal
        </Button>
      </header>

      {error && (
        <div className="page-error" role="alert">
          {error}
        </div>
      )}

      <Card padded={false}>
        <DataTable
          ariaLabel="Lista de sucursales"
          columns={columns}
          rows={sucursales}
          rowKey={(s) => s.id}
          loading={loading}
          emptyMessage="Aún no hay sucursales. Crea la primera."
        />
      </Card>

      {confirmId && (
        <div
          className="sucursales__confirm"
          role="alertdialog"
          aria-label="Confirmar eliminación de sucursal"
        >
          <span>
            ¿Eliminar la sucursal “
            {sucursales.find((s) => s.id === confirmId)?.nombre ?? ''}”? No se podrá
            si tiene categorías o deportistas asignados.
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

      {activa && <CategoriasPanel sucursal={activa} />}

      {modalOpen && (
        <NuevaSucursal
          sucursal={editing}
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
