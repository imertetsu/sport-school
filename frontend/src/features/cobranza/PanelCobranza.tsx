import { useCallback, useEffect, useMemo, useState } from 'react';
import { api, ApiError } from '@/api/client';
import type {
  CuotaListItem,
  EstadoCuota,
  MetodoPago,
  PanelCobranza as PanelCobranzaData,
} from '@/api/types';
import {
  Avatar,
  Badge,
  Button,
  Card,
  DataTable,
  EstadoBadge,
  type Column,
} from '@/components/ui';
import { useSucursales } from '@/components/shell/SucursalContext';
import { formatDate, formatMoney } from '@/lib/format';
import { KPICard } from './KPICard';
import { RegistrarPago } from './RegistrarPago';
import './PanelCobranza.css';

// Chips de filtro por estado (design-system §1). "" = Todos.
type EstadoFiltro = '' | EstadoCuota;
const FILTROS: { value: EstadoFiltro; label: string }[] = [
  { value: '', label: 'Todos' },
  { value: 'PAGADO', label: 'Pagado' },
  { value: 'PENDIENTE', label: 'Pendiente' },
  { value: 'VENCIDO', label: 'Vencido' },
];

const METODO_LABEL: Record<MetodoPago, string> = {
  EFECTIVO: 'Efectivo',
  QR: 'QR',
};

export function PanelCobranza() {
  const { selected: sucursalId } = useSucursales();

  const [panel, setPanel] = useState<PanelCobranzaData | null>(null);
  const [panelError, setPanelError] = useState<string | null>(null);

  const [cuotas, setCuotas] = useState<CuotaListItem[]>([]);
  const [cuotasTotal, setCuotasTotal] = useState(0);
  const [cuotasLoading, setCuotasLoading] = useState(true);
  const [cuotasError, setCuotasError] = useState<string | null>(null);

  const [estado, setEstado] = useState<EstadoFiltro>('');
  // Cuota preseleccionada al abrir el modal desde una fila ("Registrar pago").
  const [pagoOpen, setPagoOpen] = useState(false);
  const [cuotaSel, setCuotaSel] = useState<CuotaListItem | null>(null);

  // Token para forzar refresco tras registrar un pago.
  const [refreshKey, setRefreshKey] = useState(0);

  // --- Panel (KPIs + morosidad) ---
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setPanelError(null);
    api
      .panelCobranza(controller.signal)
      .then((data) => {
        if (active) setPanel(data);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setPanelError(
          err instanceof ApiError ? err.message : 'No se pudo cargar el panel de cobranza',
        );
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [refreshKey]);

  // --- Cuotas (tabla, filtrada por estado y sucursal) ---
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setCuotasLoading(true);
    setCuotasError(null);
    api
      .cuotas(
        {
          estado: estado || undefined,
          sucursal_id: sucursalId || undefined,
          page: 1,
          page_size: 50,
        },
        controller.signal,
      )
      .then((res) => {
        if (!active) return;
        setCuotas(res.items);
        setCuotasTotal(res.total);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setCuotasError(
          err instanceof ApiError ? err.message : 'No se pudieron cargar las cuotas',
        );
      })
      .finally(() => {
        if (active) setCuotasLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [estado, sucursalId, refreshKey]);

  const openPago = useCallback((cuota: CuotaListItem | null) => {
    setCuotaSel(cuota);
    setPagoOpen(true);
  }, []);

  const handlePagoConfirmado = useCallback(() => {
    // Un pago confirmado cambia KPIs y estados de cuota: refrescamos todo.
    setRefreshKey((k) => k + 1);
  }, []);

  const columns = useMemo<Column<CuotaListItem>[]>(
    () => [
      {
        key: 'alumno',
        header: 'Alumno',
        render: (c) => (
          <div className="cuota-cell">
            <Avatar name={c.alumno.nombre_completo} size="md" />
            <div className="cuota-cell__text">
              <span className="cuota-cell__name">{c.alumno.nombre_completo}</span>
              <span className="cuota-cell__meta">{c.categoria.nombre}</span>
            </div>
          </div>
        ),
      },
      {
        key: 'sucursal',
        header: 'Sucursal',
        hideOnNarrow: true,
        render: (c) => c.sucursal.nombre,
      },
      {
        key: 'estado',
        header: 'Estado',
        align: 'center',
        render: (c) => <EstadoBadge estado={c.estado} />,
      },
      {
        key: 'monto',
        header: 'Monto',
        align: 'right',
        render: (c) => <span className="tabular">{formatMoney(c.monto)}</span>,
      },
      {
        key: 'vence_el',
        header: 'Vencimiento',
        hideOnNarrow: true,
        render: (c) => formatDate(c.vence_el),
      },
      {
        key: 'metodo',
        header: 'Método',
        hideOnNarrow: true,
        render: (c) =>
          c.ultimo_metodo ? (
            <span className="cuota-cell__metodo">{METODO_LABEL[c.ultimo_metodo]}</span>
          ) : (
            <span className="cuota-cell__metodo cuota-cell__metodo--empty">—</span>
          ),
      },
      {
        key: 'accion',
        header: '',
        align: 'right',
        render: (c) =>
          c.estado === 'PAGADO' ? (
            <span className="cuota-cell__metodo cuota-cell__metodo--empty">—</span>
          ) : (
            <Button
              variant="secondary"
              size="sm"
              onClick={(e) => {
                e.stopPropagation();
                openPago(c);
              }}
            >
              Registrar pago
            </Button>
          ),
      },
    ],
    [openPago],
  );

  const ingresos = panel?.ingresos_mes.monto;
  const activos = panel?.alumnos_activos;
  const pendientes = panel?.cuotas_pendientes;
  const vencidas = panel?.cuotas_vencidas;

  return (
    <div className="panel-cobranza">
      <header className="page-head">
        <div>
          <h1 className="page-head__title">Panel de cobranza</h1>
          <p className="page-head__subtitle">
            Resumen · toda la escuela — estado de cuotas y pagos en tiempo real
          </p>
        </div>
        <Button variant="primary" onClick={() => openPago(null)}>
          Registrar pago
        </Button>
      </header>

      {panelError && (
        <div className="page-error" role="alert">
          {panelError}
        </div>
      )}

      <div className="kpi-grid">
        <KPICard
          label="Ingresos del mes"
          value={formatMoney(ingresos)}
          loading={!panel && !panelError}
        />
        <KPICard
          label="Alumnos activos"
          value={activos ? String(activos.count) : '—'}
          hint={
            activos
              ? `en ${activos.sucursales} sucursal${activos.sucursales === 1 ? '' : 'es'} · ${
                  activos.disciplinas
                } disciplina${activos.disciplinas === 1 ? '' : 's'}`
              : undefined
          }
          loading={!panel && !panelError}
        />
        <KPICard
          label="Cuotas pendientes"
          value={pendientes ? String(pendientes.count) : '—'}
          hint={pendientes ? `${formatMoney(pendientes.monto)} por cobrar` : undefined}
          loading={!panel && !panelError}
        />
        <KPICard
          label="Cuotas vencidas"
          value={vencidas ? String(vencidas.count) : '—'}
          hint={vencidas ? `${formatMoney(vencidas.monto)} en mora` : undefined}
          tone="overdue"
          loading={!panel && !panelError}
        />
      </div>

      <div className="panel-cobranza__cols">
        <div className="panel-cobranza__main">
          <div className="chips" role="group" aria-label="Filtrar por estado">
            {FILTROS.map((f) => (
              <button
                key={f.value || 'todos'}
                type="button"
                className={`chip${estado === f.value ? ' chip--active' : ''}`}
                aria-pressed={estado === f.value}
                onClick={() => setEstado(f.value)}
              >
                {f.label}
              </button>
            ))}
          </div>

          {cuotasError && (
            <div className="page-error" role="alert">
              {cuotasError}
            </div>
          )}

          <Card padded={false}>
            <DataTable
              ariaLabel="Cuotas"
              columns={columns}
              rows={cuotas}
              rowKey={(c) => c.id}
              loading={cuotasLoading}
              emptyMessage={
                estado || sucursalId
                  ? 'Sin cuotas para este filtro'
                  : 'Aún no hay cuotas generadas'
              }
            />
          </Card>
          {!cuotasLoading && cuotas.length > 0 && (
            <p className="panel-cobranza__count">
              {cuotasTotal} cuota{cuotasTotal === 1 ? '' : 's'}
            </p>
          )}
        </div>

        <aside className="panel-cobranza__aside">
          <Card title="Alertas de morosidad">
            {!panel ? (
              <p className="moras__empty">Cargando…</p>
            ) : panel.morosidad.length === 0 ? (
              <p className="moras__empty">Sin alumnos en mora.</p>
            ) : (
              <ul className="moras">
                {panel.morosidad.map((m) => (
                  <li key={m.alumno_id} className="moras__item">
                    <div className="moras__text">
                      <span className="moras__name">{m.nombre_completo}</span>
                      <span className="moras__meta">{m.categoria}</span>
                    </div>
                    <div className="moras__right">
                      <span className="moras__monto tabular">{formatMoney(m.monto)}</span>
                      <Badge tone="overdue">
                        {m.dias_mora} día{m.dias_mora === 1 ? '' : 's'}
                      </Badge>
                    </div>
                  </li>
                ))}
              </ul>
            )}
            <button
              type="button"
              className="moras__link"
              onClick={() => setEstado('VENCIDO')}
            >
              Ver todos los vencidos →
            </button>
          </Card>
        </aside>
      </div>

      {pagoOpen && (
        <RegistrarPago
          cuotaInicial={cuotaSel}
          onClose={() => setPagoOpen(false)}
          onConfirmado={handlePagoConfirmado}
        />
      )}
    </div>
  );
}
