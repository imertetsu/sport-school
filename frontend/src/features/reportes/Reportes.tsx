import { useEffect, useMemo, useState } from 'react';
import { api, ApiError } from '@/api/client';
import type {
  AsistenciaPorCategoria,
  AsistenciaPorDeportista,
  AsistenciaReporte,
  Categoria,
  IngresosMesItem,
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
import { formatDate, formatMoney } from '@/lib/format';
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

// Las 3 series del gráfico financiero. `monto` es el nombre histórico de los
// ingresos en el contrato C1; la utilidad puede ser negativa (mes en pérdida).
const SERIES = [
  { key: 'monto', label: 'Ingresos', modificador: 'ingreso' },
  { key: 'egresos', label: 'Egresos', modificador: 'egreso' },
  { key: 'utilidad', label: 'Utilidad', modificador: 'utilidad' },
] as const;

// Escala compartida por las 3 series: una sola línea de cero para que las
// alturas sean comparables entre sí. Si alguna utilidad es negativa, el cero
// sube dentro del área de dibujo y esas barras crecen hacia abajo.
interface EscalaChart {
  span: number; // rango total (max positivo + |min negativo|)
  zeroPct: number; // posición de la línea de cero, en % desde abajo
}

function calcularEscala(meses: IngresosMesItem[]): EscalaChart {
  const valores = meses.flatMap((m) => [
    Number(m.monto) || 0,
    Number(m.egresos) || 0,
    Number(m.utilidad) || 0,
  ]);
  const maxPos = Math.max(0, ...valores);
  const minNeg = Math.min(0, ...valores);
  const span = maxPos - minNeg;
  return { span, zeroPct: span > 0 ? (-minNeg / span) * 100 : 0 };
}

// Posición/altura de una barra respecto de la línea de cero (crece hacia arriba
// si el valor es positivo, hacia abajo si es negativo).
function estiloBarra(valor: number, escala: EscalaChart): { bottom: string; height: string } {
  if (escala.span <= 0 || valor === 0) {
    return { bottom: `${escala.zeroPct}%`, height: '0%' };
  }
  const alto = (Math.abs(valor) / escala.span) * 100;
  return valor > 0
    ? { bottom: `${escala.zeroPct}%`, height: `${alto}%` }
    : { bottom: `${escala.zeroPct - alto}%`, height: `${alto}%` };
}

export function Reportes() {
  const { sucursales, selected: sucursalGlobal } = useSucursales();

  // ---- Finanzas por mes (ingresos / egresos / utilidad) ----
  const [anio, setAnio] = useState<number>(ANIO_ACTUAL);
  // Sucursal del gráfico financiero, independiente del filtro de asistencia.
  const [sucursalFin, setSucursalFin] = useState(sucursalGlobal);
  const [ingresos, setIngresos] = useState<IngresosReporte | null>(null);
  const [ingresosError, setIngresosError] = useState<string | null>(null);
  const [ingresosLoading, setIngresosLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setIngresosLoading(true);
    setIngresosError(null);
    api
      .reportesIngresos(anio, controller.signal, sucursalFin || undefined)
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
  }, [anio, sucursalFin]);

  // ---- Asistencia global ----
  const inicial = useMemo(rangoPorDefecto, []);
  const [desde, setDesde] = useState(inicial.desde);
  const [hasta, setHasta] = useState(inicial.hasta);
  // Sucursal/categoría son filtros opcionales (semilla: la sucursal del shell).
  const [sucursalId, setSucursalId] = useState(sucursalGlobal);
  const [categoriaId, setCategoriaId] = useState('');

  // Deportista cuyo detalle de fechas está desplegado (uno a la vez).
  const [detalleAbierto, setDetalleAbierto] = useState<string | null>(null);
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

  // Escala común a las 3 series (evita /0 y ubica la línea de cero).
  const escala = useMemo(
    () => calcularEscala(ingresos?.meses ?? []),
    [ingresos],
  );

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

  // Detalle del período: una fila por deportista con marcas en el rango elegido.
  // La primera columna despliega las fechas exactas (para informar al padre).
  const columnasAsistenciaDeportista = useMemo<Column<AsistenciaPorDeportista>[]>(
    () => [
      {
        key: 'deportista',
        header: 'Deportista',
        render: (r) => {
          const abierto = detalleAbierto === r.deportista.id;
          return (
            <div className="asistencia-cat">
              <button
                type="button"
                className="asistencia-cat__toggle"
                aria-expanded={abierto}
                onClick={() =>
                  setDetalleAbierto(abierto ? null : r.deportista.id)
                }
              >
                <span className="asistencia-cat__caret" aria-hidden="true">
                  {abierto ? '▾' : '▸'}
                </span>
                <span className="asistencia-cat__name">
                  {r.deportista.nombre_completo}
                </span>
              </button>
              <span className="asistencia-cat__meta">
                {[r.categoria, r.sucursal].filter(Boolean).join(' · ') || '—'}
              </span>
              {abierto && (
                <ul className="marcas">
                  {r.marcas.length === 0 ? (
                    <li className="marcas__empty">Sin marcas registradas</li>
                  ) : (
                    r.marcas.map((m, i) => (
                      <li
                        key={`${m.fecha}-${i}`}
                        className={`marcas__item marcas__item--${
                          m.estado === 'PRESENTE' ? 'presente' : 'ausente'
                        }`}
                      >
                        <span className="marcas__fecha tabular">
                          {formatDate(m.fecha)}
                        </span>
                        <span className="marcas__estado">
                          {m.estado === 'PRESENTE' ? 'Presente' : 'Ausente'}
                        </span>
                      </li>
                    ))
                  )}
                </ul>
              )}
            </div>
          );
        },
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
        key: 'ausentes',
        header: 'Ausentes',
        align: 'right',
        hideOnNarrow: true,
        render: (r) => <span className="tabular">{r.ausentes}</span>,
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
            aria-label={`Asistencia de ${r.deportista.nombre_completo}`}
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
    [detalleAbierto],
  );

  return (
    <div className="reportes">
      <header className="page-head">
        <div>
          <h1 className="page-head__title">Reportes</h1>
          <p className="page-head__subtitle">
            Ingresos, egresos y utilidad por mes + asistencia global — vista gerencial
          </p>
        </div>
      </header>

      {/* ===== Ingresos, egresos y utilidad por mes ===== */}
      <Card
        title="Ingresos, egresos y utilidad"
        actions={
          <div className="reportes__acciones">
            <SelectField
              label="Sucursal"
              value={sucursalFin}
              onChange={(e) => setSucursalFin(e.target.value)}
            >
              <option value="">Todas</option>
              {sucursales.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.nombre}
                </option>
              ))}
            </SelectField>
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
          </div>
        }
      >
        {ingresosError && (
          <div className="page-error" role="alert">
            {ingresosError}
          </div>
        )}

        {/* Totales del año: ingresos, egresos y la utilidad resultante. */}
        <div className="reportes__totales">
          <div className="reportes__total">
            <span className="reportes__total-label">Ingresos {anio}</span>
            <span className="reportes__total-value reportes__total-value--ingreso tabular">
              {ingresosLoading ? '…' : formatMoney(ingresos?.total)}
            </span>
          </div>
          <div className="reportes__total">
            <span className="reportes__total-label">Egresos {anio}</span>
            <span className="reportes__total-value reportes__total-value--egreso tabular">
              {ingresosLoading ? '…' : formatMoney(ingresos?.total_egresos)}
            </span>
          </div>
          <div className="reportes__total">
            <span className="reportes__total-label">Utilidad {anio}</span>
            <span
              className={`reportes__total-value tabular ${
                Number(ingresos?.utilidad ?? 0) < 0
                  ? 'reportes__total-value--perdida'
                  : 'reportes__total-value--utilidad'
              }`}
            >
              {ingresosLoading ? '…' : formatMoney(ingresos?.utilidad)}
            </span>
          </div>
        </div>

        <div className="barchart__legend">
          {SERIES.map((s) => (
            <span className="barchart__legend-item" key={s.key}>
              <span className={`barchart__swatch barchart__swatch--${s.modificador}`} />
              {s.label}
            </span>
          ))}
        </div>

        {ingresosLoading ? (
          <p className="moras__empty">Cargando…</p>
        ) : ingresos ? (
          <div
            className="barchart"
            role="img"
            aria-label={`Ingresos, egresos y utilidad por mes del año ${anio}`}
          >
            {ingresos.meses.map((m) => {
              const utilidad = Number(m.utilidad) || 0;
              return (
                <div className="barchart__col" key={m.mes}>
                  <span
                    className={`barchart__value tabular${
                      utilidad < 0 ? ' barchart__value--perdida' : ''
                    }`}
                  >
                    {utilidad !== 0 ? formatMoney(m.utilidad) : ''}
                  </span>
                  <span className="barchart__plot">
                    {/* Línea de cero: solo se ve cuando hay meses en pérdida. */}
                    <span
                      className="barchart__zero"
                      style={{ bottom: `${escala.zeroPct}%` }}
                      aria-hidden="true"
                    />
                    {SERIES.map((s) => {
                      const valor = Number(m[s.key]) || 0;
                      return (
                        <span className="barchart__slot" key={s.key}>
                          <span
                            className={`barchart__bar barchart__bar--${s.modificador}${
                              valor === 0 ? ' barchart__bar--empty' : ''
                            }`}
                            style={estiloBarra(valor, escala)}
                            title={`${m.etiqueta} · ${s.label}: ${formatMoney(m[s.key])}`}
                          />
                        </span>
                      );
                    })}
                  </span>
                  <span className="barchart__label">{m.etiqueta}</span>
                </div>
              );
            })}
          </div>
        ) : null}

        {sucursalFin && (
          <p className="reportes__nota">
            Filtrado por sucursal: no se incluyen los egresos registrados a nivel de
            organización (sin sucursal asignada).
          </p>
        )}
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

      {/* Detalle por deportista del mismo rango/filtros (p. ej. todo julio). */}
      <Card title="Asistencia por deportista" padded={false}>
        <DataTable
          ariaLabel="Asistencia por deportista"
          columns={columnasAsistenciaDeportista}
          rows={asistencia?.por_deportista ?? []}
          rowKey={(r) => r.deportista.id}
          loading={asistenciaLoading}
          emptyMessage="Sin marcas de asistencia en el rango seleccionado"
        />
      </Card>
    </div>
  );
}
