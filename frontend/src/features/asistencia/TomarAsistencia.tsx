import { useCallback, useEffect, useMemo, useState } from 'react';
import { api, ApiError } from '@/api/client';
import type {
  CategoriaAsistencia,
  EstadoAsistencia,
  RosterItem,
} from '@/api/types';
import { Avatar, Button, Card, Field, SelectField } from '@/components/ui';
import { nivelLabel } from '@/lib/format';
import './TomarAsistencia.css';

// Default de marca (decisión del agente, documentada en el HANDOFF):
// al abrir un roster SIN sesión guardada, todos los deportistas cuentan como PRESENTE.
// Tomar lista en móvil es más rápido si el entrenador solo toca a los ausentes;
// los contadores reflejan ese default desde el inicio. Si ya existe sesión, se
// respeta el estado guardado por deportista (estado != null).
const DEFAULT_ESTADO: EstadoAsistencia = 'PRESENTE';

// Fecha de hoy en formato YYYY-MM-DD (local), valor por defecto del selector.
function hoyISO(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

// Estado efectivo de un deportista aplicando el default a los que no tienen marca.
function estadoEfectivo(estado: EstadoAsistencia | null): EstadoAsistencia {
  return estado ?? DEFAULT_ESTADO;
}

export function TomarAsistencia() {
  // --- Categorías visibles por rol ---
  const [categorias, setCategorias] = useState<CategoriaAsistencia[]>([]);
  const [categoriasError, setCategoriasError] = useState<string | null>(null);
  const [categoriaId, setCategoriaId] = useState('');
  const [fecha, setFecha] = useState(hoyISO);

  // --- Roster (lista de deportistas + marcas) ---
  const [items, setItems] = useState<RosterItem[]>([]);
  const [rosterLoading, setRosterLoading] = useState(false);
  const [rosterError, setRosterError] = useState<string | null>(null);

  // --- Guardado ---
  const [guardando, setGuardando] = useState(false);
  const [guardadoOk, setGuardadoOk] = useState(false);
  const [guardarError, setGuardarError] = useState<string | null>(null);

  // Cargar categorías una vez; preselecciona la primera.
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setCategoriasError(null);
    api
      .asistenciaCategorias(controller.signal)
      .then((data) => {
        if (!active) return;
        setCategorias(data);
        setCategoriaId((prev) => prev || data[0]?.id || '');
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setCategoriasError(
          err instanceof ApiError ? err.message : 'No se pudieron cargar las categorías',
        );
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, []);

  // Cargar el roster cuando hay categoría + fecha. Al recargar refleja lo guardado.
  useEffect(() => {
    if (!categoriaId || !fecha) {
      setItems([]);
      return;
    }
    const controller = new AbortController();
    let active = true;
    setRosterLoading(true);
    setRosterError(null);
    setGuardadoOk(false);
    setGuardarError(null);
    api
      .asistenciaRoster(categoriaId, fecha, controller.signal)
      .then((data) => {
        if (active) setItems(data.items);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setItems([]);
        setRosterError(
          err instanceof ApiError ? err.message : 'No se pudo cargar la lista de asistencia',
        );
      })
      .finally(() => {
        if (active) setRosterLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [categoriaId, fecha]);

  const setEstado = useCallback((deportistaId: string, estado: EstadoAsistencia) => {
    setItems((prev) =>
      prev.map((it) => (it.deportista_id === deportistaId ? { ...it, estado } : it)),
    );
    setGuardadoOk(false);
  }, []);

  // Contadores en vivo (aplicando el default a los no marcados).
  const resumen = useMemo(() => {
    let presentes = 0;
    let ausentes = 0;
    for (const it of items) {
      if (estadoEfectivo(it.estado) === 'PRESENTE') presentes += 1;
      else ausentes += 1;
    }
    return { presentes, ausentes, total: items.length };
  }, [items]);

  const categoriaSel = useMemo(
    () => categorias.find((c) => c.id === categoriaId) ?? null,
    [categorias, categoriaId],
  );

  const handleGuardar = useCallback(() => {
    if (!categoriaId || !fecha || items.length === 0) return;
    const controller = new AbortController();
    setGuardando(true);
    setGuardadoOk(false);
    setGuardarError(null);
    api
      .asistenciaGuardar(
        {
          categoria_id: categoriaId,
          fecha,
          marcas: items.map((it) => ({
            deportista_id: it.deportista_id,
            estado: estadoEfectivo(it.estado),
          })),
        },
        controller.signal,
      )
      .then((data) => {
        // El backend devuelve el roster guardado: refleja exactamente lo persistido.
        setItems(data.items);
        setGuardadoOk(true);
      })
      .catch((err) => {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setGuardarError(
          err instanceof ApiError ? err.message : 'No se pudo guardar la asistencia',
        );
      })
      .finally(() => setGuardando(false));
  }, [categoriaId, fecha, items]);

  const meta = categoriaSel
    ? `${nivelLabel(categoriaSel.nivel)} · ${categoriaSel.sucursal.nombre}`
    : '';

  return (
    <div className="asistencia">
      <header className="page-head">
        <div>
          <h1 className="page-head__title">Asistencia</h1>
          <p className="page-head__subtitle">
            Toma de lista por sesión — marca Presente/Ausente y guarda
          </p>
        </div>
      </header>

      {categoriasError && (
        <div className="page-error" role="alert">
          {categoriasError}
        </div>
      )}

      <div className="asistencia__filtros">
        <SelectField
          label="Categoría"
          value={categoriaId}
          onChange={(e) => setCategoriaId(e.target.value)}
          disabled={categorias.length === 0}
        >
          {categorias.length === 0 && <option value="">Sin categorías</option>}
          {categorias.map((c) => (
            <option key={c.id} value={c.id}>
              {c.nombre} · {c.sucursal.nombre} ({c.total_deportistas})
            </option>
          ))}
        </SelectField>
        <Field
          label="Fecha"
          type="date"
          value={fecha}
          max={hoyISO()}
          onChange={(e) => setFecha(e.target.value)}
        />
      </div>

      <div className="asistencia__resumen" role="status" aria-label="Resumen de asistencia">
        <div className="contador contador--presentes">
          <span className="contador__valor">{resumen.presentes}</span>
          <span className="contador__label">Presentes</span>
        </div>
        <div className="contador contador--ausentes">
          <span className="contador__valor">{resumen.ausentes}</span>
          <span className="contador__label">Ausentes</span>
        </div>
        <div className="contador">
          <span className="contador__valor">{resumen.total}</span>
          <span className="contador__label">Total</span>
        </div>
      </div>

      {rosterError && (
        <div className="page-error" role="alert">
          {rosterError}
        </div>
      )}

      <Card padded={false}>
        {rosterLoading ? (
          <p className="roster__loading">Cargando lista…</p>
        ) : items.length === 0 ? (
          <p className="roster__empty">
            {categoriaId
              ? 'Esta categoría no tiene deportistas.'
              : 'Elige una categoría para tomar lista.'}
          </p>
        ) : (
          <ul className="roster" aria-label="Lista de deportistas">
            {items.map((it) => {
              const estado = estadoEfectivo(it.estado);
              return (
                <li key={it.deportista_id} className="roster__row">
                  <Avatar name={it.nombre_completo} size="md" />
                  <div className="roster__text">
                    <span className="roster__name">{it.nombre_completo}</span>
                    {meta && <span className="roster__meta">{meta}</span>}
                  </div>
                  <div
                    className="toggle-asistencia"
                    role="group"
                    aria-label={`Asistencia de ${it.nombre_completo}`}
                  >
                    <button
                      type="button"
                      className="toggle-asistencia__btn toggle-asistencia__btn--presente"
                      aria-pressed={estado === 'PRESENTE'}
                      onClick={() => setEstado(it.deportista_id, 'PRESENTE')}
                    >
                      Presente
                    </button>
                    <button
                      type="button"
                      className="toggle-asistencia__btn toggle-asistencia__btn--ausente"
                      aria-pressed={estado === 'AUSENTE'}
                      onClick={() => setEstado(it.deportista_id, 'AUSENTE')}
                    >
                      Ausente
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      <div className="asistencia__bar">
        <span className="asistencia__bar-info">
          {guardarError ? (
            <span className="asistencia__feedback asistencia__feedback--error" role="alert">
              {guardarError}
            </span>
          ) : guardadoOk ? (
            <span className="asistencia__feedback asistencia__feedback--ok" role="status">
              ✓ Asistencia guardada
            </span>
          ) : (
            `${resumen.presentes} presente${resumen.presentes === 1 ? '' : 's'} de ${
              resumen.total
            }`
          )}
        </span>
        <Button
          variant="primary"
          onClick={handleGuardar}
          disabled={guardando || rosterLoading || items.length === 0}
        >
          {guardando ? 'Guardando…' : 'Guardar'}
        </Button>
      </div>
    </div>
  );
}
