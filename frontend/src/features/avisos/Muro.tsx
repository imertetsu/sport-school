import { useEffect, useState } from 'react';
import { api, ApiError } from '@/api/client';
import type { AvisoOut } from '@/api/types';
import { Badge, Button, Card } from '@/components/ui';
import { useSucursales } from '@/components/shell/SucursalContext';
import { useAuth } from '@/auth/useAuth';
import { formatDate } from '@/lib/format';
import { NuevoAviso } from './NuevoAviso';
import './Muro.css';

const PAGE_SIZE = 20;

// Etiqueta del alcance para el Badge: "Toda la escuela" / nombre sucursal /
// nombre categoría. Tono neutro para ORG, acento para los focalizados.
function alcanceBadge(a: AvisoOut) {
  if (a.alcance === 'SUCURSAL') {
    return { tone: 'accent' as const, label: a.sucursal?.nombre ?? 'Sucursal' };
  }
  if (a.alcance === 'CATEGORIA') {
    return { tone: 'accent' as const, label: a.categoria?.nombre ?? 'Categoría' };
  }
  return { tone: 'neutral' as const, label: 'Toda la escuela' };
}

// Muro de avisos (RF-COM-01): feed de tarjetas, scoped por rol en el backend.
// ADMIN: publica + edita/elimina (soft-delete). ENTRENADOR: solo lectura.
export function Muro() {
  const { sucursales } = useSucursales();
  // viewRole es la verdad de la UI (respeta el toggle del prototipo); el
  // backend impone los permisos reales (require_role) en las escrituras.
  const { viewRole } = useAuth();
  const isAdmin = viewRole === 'ADMIN';

  const [items, setItems] = useState<AvisoOut[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [incluirExpirados, setIncluirExpirados] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Alta/edición + recarga.
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<AvisoOut | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  // Eliminación (soft-delete) con confirmación inline.
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  // Cambiar el filtro de expirados vuelve a la primera página.
  useEffect(() => {
    setPage(1);
  }, [incluirExpirados]);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    api
      .avisos(
        { incluirExpirados, page, page_size: PAGE_SIZE },
        controller.signal,
      )
      .then((res) => {
        if (!active) return;
        setItems(res.items);
        setTotal(res.total);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setError(err instanceof ApiError ? err.message : 'No se pudieron cargar los avisos');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [incluirExpirados, page, reloadKey]);

  function recargar() {
    setPage(1);
    setReloadKey((k) => k + 1);
  }

  function abrirNuevo() {
    setEditing(null);
    setModalOpen(true);
  }

  function abrirEditar(aviso: AvisoOut) {
    setEditing(aviso);
    setModalOpen(true);
  }

  async function eliminar(id: string) {
    setDeletingId(id);
    setError(null);
    try {
      await api.eliminarAviso(id);
      setConfirmId(null);
      recargar();
    } catch (err) {
      if (err instanceof ApiError) {
        setError(
          err.isForbidden ? 'No tienes permiso para eliminar avisos.' : err.message,
        );
      } else {
        setError('No se pudo eliminar el aviso.');
      }
    } finally {
      setDeletingId(null);
    }
  }

  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="avisos">
      <header className="page-head">
        <div>
          <h1 className="page-head__title">Avisos</h1>
          <p className="page-head__subtitle">
            {loading
              ? 'Cargando…'
              : `${total} aviso${total === 1 ? '' : 's'} en el muro`}
          </p>
        </div>
        {isAdmin && (
          <Button variant="primary" onClick={abrirNuevo}>
            + Nuevo aviso
          </Button>
        )}
      </header>

      {error && (
        <div className="page-error" role="alert">
          {error}
        </div>
      )}

      {isAdmin && (
        <label className="avisos__toggle">
          <input
            type="checkbox"
            checked={incluirExpirados}
            onChange={(e) => setIncluirExpirados(e.target.checked)}
          />
          Mostrar avisos vencidos
        </label>
      )}

      {!loading && items.length === 0 && (
        <Card>
          <p className="avisos__empty">No hay avisos en el muro por ahora.</p>
        </Card>
      )}

      <div className="avisos__feed">
        {items.map((a) => {
          const badge = alcanceBadge(a);
          return (
            <Card
              key={a.id}
              className={`aviso${a.expirado ? ' aviso--expirado' : ''}`}
            >
              <div className="aviso__head">
                <div className="aviso__meta">
                  <Badge tone={badge.tone}>{badge.label}</Badge>
                  {a.expirado && <Badge tone="overdue">Vencido</Badge>}
                </div>
                {isAdmin && (
                  <div className="aviso__acciones">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => abrirEditar(a)}
                    >
                      Editar
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setConfirmId(a.id)}
                    >
                      Eliminar
                    </Button>
                  </div>
                )}
              </div>

              <h2 className="aviso__titulo">{a.titulo}</h2>
              <p className="aviso__cuerpo">{a.cuerpo}</p>

              <div className="aviso__footer">
                <span className="aviso__fecha">
                  Publicado {formatDate(a.publicado_en)}
                </span>
                {a.vigente_hasta && (
                  <span className="aviso__vence">
                    Vence {formatDate(a.vigente_hasta)}
                  </span>
                )}
                {a.creado_por_nombre && (
                  <span className="aviso__autor">por {a.creado_por_nombre}</span>
                )}
              </div>

              {confirmId === a.id && (
                <div className="aviso__confirm" role="alertdialog" aria-label="Confirmar eliminación">
                  <span>¿Eliminar este aviso? Dejará de mostrarse en el muro.</span>
                  <div className="aviso__confirm-actions">
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => setConfirmId(null)}
                      disabled={deletingId === a.id}
                    >
                      Cancelar
                    </Button>
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={() => eliminar(a.id)}
                      disabled={deletingId === a.id}
                    >
                      {deletingId === a.id ? 'Eliminando…' : 'Eliminar'}
                    </Button>
                  </div>
                </div>
              )}
            </Card>
          );
        })}
      </div>

      {total > PAGE_SIZE && (
        <div className="avisos__pager">
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

      {modalOpen && (
        <NuevoAviso
          sucursales={sucursales}
          aviso={editing}
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
