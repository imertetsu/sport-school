import { useEffect, useMemo, useState } from 'react';
import { api, ApiError } from '@/api/client';
import type {
  Categoria,
  ClaseSemana,
  DiaSemana,
  SemanaOut,
} from '@/api/types';
import { Badge, Button, Card, SelectField } from '@/components/ui';
import { useSucursales } from '@/components/shell/SucursalContext';
import { useAuth } from '@/auth/useAuth';
import { formatTime } from '@/lib/format';
import { NuevoHorario, type HorarioEditable } from './NuevoHorario';
import './Horarios.css';

// Datos del bloque sobre los que actúa la edición/eliminación: la clase de la
// rejilla + el día al que pertenece (la rejilla no repite dia_semana por clase).
interface BloqueRef {
  clase: ClaseSemana;
  dia_semana: DiaSemana;
}

// Programación de clases (epic Fase 2 — C4): rejilla semanal por categoría y/o
// sucursal, scoped por rol en el backend. ADMIN: alta + editar/eliminar (soft)
// por bloque. ENTRENADOR: solo lectura (sus sucursales).
export function Horarios() {
  const { sucursales } = useSucursales();
  // viewRole es la verdad de la UI (respeta el toggle del prototipo); el backend
  // impone los permisos reales (require_role) en las escrituras.
  const { viewRole } = useAuth();
  const isAdmin = viewRole === 'ADMIN';

  // --- Filtros (categoría y/o sucursal) ---
  const [sucursalId, setSucursalId] = useState('');
  const [categoriaId, setCategoriaId] = useState('');
  const [categorias, setCategorias] = useState<Categoria[]>([]);

  // --- Rejilla semanal ---
  const [semana, setSemana] = useState<SemanaOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  // --- Alta / edición (modal, ADMIN) ---
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<HorarioEditable | null>(null);

  // --- Eliminación (soft-delete) con confirmación inline ---
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  // Cargar categorías (scoped por rol/sucursal en el backend) para el filtro.
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    api
      .categorias(sucursalId || undefined, controller.signal)
      .then((data) => {
        if (!active) return;
        setCategorias(data);
        // Si la categoría seleccionada ya no está en la lista, la limpiamos.
        setCategoriaId((prev) => (data.some((c) => c.id === prev) ? prev : ''));
      })
      .catch((err) => {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        // El filtro de categoría quedará vacío; no bloquea la rejilla.
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [sucursalId]);

  // Cargar la rejilla semanal cuando cambian los filtros o se recarga.
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    api
      .horariosSemana(
        { sucursalId: sucursalId || undefined, categoriaId: categoriaId || undefined },
        controller.signal,
      )
      .then((res) => {
        if (active) setSemana(res);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setError(
          err instanceof ApiError ? err.message : 'No se pudieron cargar los horarios',
        );
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [sucursalId, categoriaId, reloadKey]);

  function recargar() {
    setReloadKey((k) => k + 1);
  }

  function abrirNuevo() {
    setEditing(null);
    setModalOpen(true);
  }

  function abrirEditar(b: BloqueRef) {
    setEditing({
      id: b.clase.id,
      categoria_id: b.clase.categoria.id,
      dia_semana: b.dia_semana,
      hora_inicio: b.clase.hora_inicio,
      hora_fin: b.clase.hora_fin,
      entrenador_id: b.clase.entrenador?.id ?? null,
    });
    setModalOpen(true);
  }

  async function eliminar(id: string) {
    setDeletingId(id);
    setError(null);
    try {
      await api.eliminarHorario(id);
      setConfirmId(null);
      recargar();
    } catch (err) {
      if (err instanceof ApiError) {
        setError(
          err.isForbidden ? 'No tienes permiso para eliminar horarios.' : err.message,
        );
      } else {
        setError('No se pudo eliminar el horario.');
      }
    } finally {
      setDeletingId(null);
    }
  }

  const dias = useMemo(() => semana?.dias ?? [], [semana]);
  const totalClases = useMemo(
    () => dias.reduce((acc, d) => acc + d.clases.length, 0),
    [dias],
  );

  return (
    <div className="horarios">
      <header className="page-head">
        <div>
          <h1 className="page-head__title">Horarios</h1>
          <p className="page-head__subtitle">
            {loading
              ? 'Cargando…'
              : `${totalClases} clase${totalClases === 1 ? '' : 's'} en la semana`}
          </p>
        </div>
        {isAdmin && (
          <Button variant="primary" onClick={abrirNuevo}>
            + Nuevo horario
          </Button>
        )}
      </header>

      {error && (
        <div className="page-error" role="alert">
          {error}
        </div>
      )}

      <div className="horarios__filtros">
        <SelectField
          label="Sucursal"
          value={sucursalId}
          onChange={(e) => setSucursalId(e.target.value)}
        >
          <option value="">Todas las sucursales</option>
          {sucursales.map((s) => (
            <option key={s.id} value={s.id}>
              {s.nombre}
            </option>
          ))}
        </SelectField>
        <SelectField
          label="Categoría"
          value={categoriaId}
          onChange={(e) => setCategoriaId(e.target.value)}
        >
          <option value="">Todas las categorías</option>
          {categorias.map((c) => (
            <option key={c.id} value={c.id}>
              {c.nombre}
            </option>
          ))}
        </SelectField>
      </div>

      {loading && dias.length === 0 ? (
        <Card>
          <p className="horarios__empty">Cargando horarios…</p>
        </Card>
      ) : (
        <div className="horarios__grid" role="grid" aria-label="Rejilla semanal de clases">
          {dias.map((dia) => (
            <section
              key={dia.dia_semana}
              className="horarios__col"
              role="gridcell"
              aria-label={dia.dia_label}
            >
              <h2 className="horarios__col-titulo">{dia.dia_label}</h2>
              {dia.clases.length === 0 ? (
                <p className="horarios__col-vacio">Sin clases</p>
              ) : (
                dia.clases.map((clase) => (
                  <article key={clase.id} className="horario-bloque">
                    <div className="horario-bloque__head">
                      <span className="horario-bloque__hora">
                        {`${formatTime(clase.hora_inicio)}–${formatTime(clase.hora_fin)}`}
                      </span>
                    </div>
                    <p className="horario-bloque__categoria">{clase.categoria.nombre}</p>
                    {clase.entrenador ? (
                      <Badge tone="accent">{clase.entrenador.nombres}</Badge>
                    ) : (
                      <Badge tone="neutral">Sin entrenador</Badge>
                    )}

                    {isAdmin && (
                      <div className="horario-bloque__acciones">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() =>
                            abrirEditar({ clase, dia_semana: dia.dia_semana })
                          }
                        >
                          Editar
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setConfirmId(clase.id)}
                        >
                          Eliminar
                        </Button>
                      </div>
                    )}

                    {confirmId === clase.id && (
                      <div
                        className="horario-bloque__confirm"
                        role="alertdialog"
                        aria-label="Confirmar eliminación"
                      >
                        <span>¿Eliminar este horario? Dejará de programar clases.</span>
                        <div className="horario-bloque__confirm-actions">
                          <Button
                            variant="secondary"
                            size="sm"
                            onClick={() => setConfirmId(null)}
                            disabled={deletingId === clase.id}
                          >
                            Cancelar
                          </Button>
                          <Button
                            variant="danger"
                            size="sm"
                            onClick={() => eliminar(clase.id)}
                            disabled={deletingId === clase.id}
                          >
                            {deletingId === clase.id ? 'Eliminando…' : 'Eliminar'}
                          </Button>
                        </div>
                      </div>
                    )}
                  </article>
                ))
              )}
            </section>
          ))}
        </div>
      )}

      {modalOpen && (
        <NuevoHorario
          horario={editing}
          sucursalId={sucursalId || undefined}
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
