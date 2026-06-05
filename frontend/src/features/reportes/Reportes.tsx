import { useEffect, useMemo, useState } from 'react';
import { api, ApiError } from '@/api/client';
import type {
  AsistenciaPorCategoria,
  AsistenciaReporte,
  Categoria,
  IngresosReporte,
} from '@/api/types';
import {
  Badge,
  Card,
  DataTable,
  Field,
  SelectField,
  type Column,
} from '@/components/ui';
import { useSucursales } from '@/components/shell/SucursalContext';
import { formatMoney } from '@/lib/format';
import './Reportes.css';

// --- Año: selector con los últimos N años (incl. el actual). ---
const ANIO_ACTUAL = new Date().getFullYear();
const ANIOS = Array.from({ length: 5 }, (_, i) => ANIO_ACTUAL - i);

// Rango por defecto: últimos ~3 meses (coincide con el default del backend).
function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}
function rangoPorDefecto(): { desde: string; hasta: string } {
  const hasta = new Date();
  const desde = new Date();
  desde.setMonth(desde.getMonth() - 3);
  return { desde: isoDate(desde), hasta: isoDate(hasta) };
}

// Tono del badge según el % de asistencia (verde alto, ámbar medio, rojo bajo).
function tonoPct(pct: number): 'paid' | 'pending' | 'overdue' {
  if (pct >= 75) return 'paid';
  if (pct >= 50) return 'pending';
  return 'overdue';
}

export function Reportes() {
  const { sucursales, selected: sucursalGlobal } = useSucursales();

  // ---- Ingresos por mes ----
  const [anio, setAnio] = useState<number>(ANIO_ACTUAL);
  const [ingresos, setIngresos] = useState<IngresosReporte | null>(null);
  const [ingresosError, setIngresosError] = useState<string | null>(null);
  const [ingresosLoading, setIngresosLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setIngresosLoading(true);
    setIngresosError(null);
    api
      .reportesIngresos(anio, controller.signal)
      .then((data) => {
        if (active) setIngresos(data);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setIngresosError(
          err instanceof ApiError ? err.message : 'No se pudieron cargar los ingresos',
        );
      })
      .finally(() => {
        if (active) setIngresosLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [anio]);

  // ---- Asistencia global ----
  const inicial = useMemo(rangoPorDefecto, []);
  const [desde, setDesde] = useState(inicial.desde);
  const [hasta, setHasta] = useState(inicial.hasta);
  // Sucursal/categoría son filtros opcionales (semilla: la sucursal del shell).
  const [sucursalId, setSucursalId] = useState(sucursalGlobal);
  const [categoriaId, setCategoriaId] = useState('');

  const [asistencia, setAsistencia] = useState<AsistenciaReporte | null>(null);
  const [asistenciaError, setAsistenciaError] = useState<string | null>(null);
  const [asistenciaLoading, setAsistenciaLoading] = useState(true);

  // Categorías del filtro opcional (dependen de la sucursal elegida).
  const [categorias, setCategorias] = useState<Categoria[]>([]);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    api
      .categorias(sucursalId || undefined, controller.signal)
      .then((data) => {
        if (active) setCategorias(data);
      })
      .catch(() => {
        if (active) setCategorias([]);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [sucursalId]);

  // Si cambia la sucursal, descarta una categoría que ya no le pertenezca.
  useEffect(() => {
    if (categoriaId && !categorias.some((c) => c.id === categoriaId)) {
      setCategoriaId('');
    }
  }, [categorias, categoriaId]);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setAsistenciaLoading(true);
    setAsistenciaError(null);
    api
      .reportesAsistencia(
        {
          desde: desde || undefined,
          hasta: hasta || undefined,
          sucursalId: sucursalId || undefined,
          categoriaId: categoriaId || undefined,
        },
        controller.signal,
      )
      .then((data) => {
        if (active) setAsistencia(data);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setAsistenciaError(
          err instanceof ApiError ? err.message : 'No se pudo cargar la asistencia',
        );
      })
      .finally(() => {
        if (active) setAsistenciaLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [desde, hasta, sucursalId, categoriaId]);

  // Máximo del año para escalar la altura de las barras (evita /0).
  const maxMonto = useMemo(() => {
    if (!ingresos) return 0;
    return ingresos.meses.reduce((max, m) => Math.max(max, Number(m.monto) || 0), 0);
  }, [ingresos]);

  const columnasAsistencia = useMemo<Column<AsistenciaPorCategoria>[]>(
    () => [
      {
        key: 'categoria',
        header: 'Categoría',
        render: (r) => (
          <div className="asistencia-cat">
            <span className="asistencia-cat__name">{r.categoria.nombre}</span>
            <span className="asistencia-cat__meta">{r.sucursal.nombre}</span>
          </div>
        ),
      },
      {
        key: 'sesiones',
        header: 'Sesiones',
        align: 'right',
        hideOnNarrow: true,
        render: (r) => <span className="tabular">{r.sesiones}</span>,
      },
      {
        key: 'presentes',
        header: 'Presentes / Total',
        align: 'right',
        render: (r) => (
          <span className="tabular">
            {r.presentes} / {r.total_marcas}
          </span>
        ),
      },
      {
        key: 'pct',
        header: 'Asistencia',
        render: (r) => (
          <div
            className="progress"
            role="progressbar"
            aria-valuenow={r.pct_presente}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={`Asistencia ${r.categoria.nombre}`}
          >
            <span className="progress__track">
              <span
                className="progress__fill"
                style={{ width: `${Math.min(100, Math.max(0, r.pct_presente))}%` }}
              />
            </span>
            <span className="progress__pct tabular">{r.pct_presente}%</span>
          </div>
        ),
      },
    ],
    [],
  );

  return (
    <div className="reportes">
      <header className="page-head">
        <div>
          <h1 className="page-head__title">Reportes</h1>
          <p className="page-head__subtitle">
            Ingresos por mes y asistencia global — vista gerencial
          </p>
        </div>
      </header>

      {/* ===== Ingresos por mes ===== */}
      <Card
        title="Ingresos por mes"
        actions={
          <SelectField
            label="Año"
            value={anio}
            onChange={(e) => setAnio(Number(e.target.value))}
          >
            {ANIOS.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </SelectField>
        }
      >
        {ingresosError && (
          <div className="page-error" role="alert">
            {ingresosError}
          </div>
        )}

        <div className="reportes__total">
          <span className="reportes__total-label">Total {anio}</span>
          <span className="reportes__total-value tabular">
            {ingresosLoading ? '…' : formatMoney(ingresos?.total)}
          </span>
        </div>

        {ingresosLoading ? (
          <p className="moras__empty">Cargando…</p>
        ) : ingresos ? (
          <div
            className="barchart"
            role="img"
            aria-label={`Ingresos por mes del año ${anio}`}
          >
            {ingresos.meses.map((m) => {
              const monto = Number(m.monto) || 0;
              const altura = maxMonto > 0 ? Math.round((monto / maxMonto) * 100) : 0;
              return (
                <div className="barchart__col" key={m.mes}>
                  <span className="barchart__value tabular">
                    {monto > 0 ? formatMoney(m.monto) : ''}
                  </span>
                  <span className="barchart__bar-track">
                    <span
                      className={`barchart__bar${monto === 0 ? ' barchart__bar--empty' : ''}`}
                      style={{ height: `${monto === 0 ? 0 : altura}%` }}
                      title={`${m.etiqueta}: ${formatMoney(m.monto)} (${m.n_pagos} pago${
                        m.n_pagos === 1 ? '' : 's'
                      })`}
                    />
                  </span>
                  <span className="barchart__label">{m.etiqueta}</span>
                </div>
              );
            })}
          </div>
        ) : null}
      </Card>

      {/* ===== Asistencia global ===== */}
      <Card title="Asistencia global">
        <div className="reportes__filtros">
          <Field
            type="date"
            label="Desde"
            value={desde}
            max={hasta || undefined}
            onChange={(e) => setDesde(e.target.value)}
          />
          <Field
            type="date"
            label="Hasta"
            value={hasta}
            min={desde || undefined}
            onChange={(e) => setHasta(e.target.value)}
          />
          <SelectField
            label="Sucursal"
            value={sucursalId}
            onChange={(e) => setSucursalId(e.target.value)}
          >
            <option value="">Todas</option>
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
            <option value="">Todas</option>
            {categorias.map((c) => (
              <option key={c.id} value={c.id}>
                {c.nombre}
              </option>
            ))}
          </SelectField>
        </div>

        {asistenciaError && (
          <div className="page-error" role="alert">
            {asistenciaError}
          </div>
        )}

        <div className="asistencia-resumen">
          <div className="asistencia-kpi">
            <span className="asistencia-kpi__label">% Asistencia global</span>
            <span className="asistencia-kpi__value tabular">
              {asistenciaLoading
                ? '…'
                : asistencia
                  ? `${asistencia.global.pct_presente}%`
                  : '—'}
            </span>
            {asistencia && !asistenciaLoading && (
              <span className="asistencia-kpi__meta">
                {asistencia.global.presentes} de {asistencia.global.total_marcas} marcas ·{' '}
                {asistencia.global.sesiones} sesion
                {asistencia.global.sesiones === 1 ? '' : 'es'}
              </span>
            )}
          </div>
          {asistencia && !asistenciaLoading && (
            <Badge tone={tonoPct(asistencia.global.pct_presente)}>
              {asistencia.global.pct_presente}% presente
            </Badge>
          )}
        </div>
      </Card>

      <Card title="Asistencia por categoría" padded={false}>
        <DataTable
          ariaLabel="Asistencia por categoría"
          columns={columnasAsistencia}
          rows={asistencia?.por_categoria ?? []}
          rowKey={(r) => r.categoria.id}
          loading={asistenciaLoading}
          emptyMessage="Sin marcas de asistencia en el rango seleccionado"
        />
      </Card>
    </div>
  );
}
