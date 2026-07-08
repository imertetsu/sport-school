import { useCallback, useEffect, useMemo, useState } from 'react';
import { api, ApiError } from '@/api/client';
import type {
  CuotaListItem,
  EstadoCuota,
  MetodoPago,
  MorosidadItem,
  MotivoRecordatorio,
  PanelCobranza as PanelCobranzaData,
} from '@/api/types';
import {
  Avatar,
  Badge,
  Button,
  Card,
  DataTable,
  EstadoBadge,
  useToast,
  type Column,
} from '@/components/ui';
import { useSucursales } from '@/components/shell/SucursalContext';
import { useAuth } from '@/auth/useAuth';
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
  { value: 'PARCIAL', label: 'Parcial' },
  { value: 'VENCIDO', label: 'Vencido' },
];

const METODO_LABEL: Record<MetodoPago, string> = {
  EFECTIVO: 'Efectivo',
  QR: 'QR',
};

// Aviso transitorio del recordatorio de cobro (no hay sistema de toasts: usamos
// una nota inline arriba de la tabla, con tono según el resultado del backend).
type NoticeTone = 'success' | 'info' | 'warning' | 'error';
interface Notice {
  tone: NoticeTone;
  text: string;
}

// Mapea el `motivo` que devuelve el backend a (tono visual + mensaje en español).
function recordatorioNotice(motivo: MotivoRecordatorio | null, enviado: boolean): Notice {
  switch (motivo) {
    case 'ok':
      return { tone: 'success', text: 'Recordatorio enviado.' };
    case 'ya_enviado':
      return { tone: 'info', text: 'Ya se había enviado este recordatorio.' };
    case 'sin_telefono':
      return { tone: 'warning', text: 'El tutor no tiene teléfono registrado.' };
    case 'error_envio':
      return { tone: 'error', text: 'No se pudo enviar el recordatorio.' };
    default:
      // Sin motivo conocido: nos guiamos por `enviado`.
      return enviado
        ? { tone: 'success', text: 'Recordatorio enviado.' }
        : { tone: 'error', text: 'No se pudo enviar el recordatorio.' };
  }
}

// Texto del recordatorio de mora listo para pegar en un chat de WhatsApp.
function mensajeMora(m: MorosidadItem, orgNombre: string): string {
  return [
    `Recordatorio de pago — ${orgNombre}`,
    `Deportista: ${m.nombre_completo}`,
    `Deuda vencida: ${formatMoney(m.monto)} (${m.dias_mora} día${m.dias_mora === 1 ? '' : 's'} de mora)`,
    'Por favor regularizá el pago. Te compartimos el QR de la escuela para pagar; al pagar, respondé con la captura del comprobante. ¡Gracias!',
  ].join('\n');
}

async function copiarAlPortapapeles(texto: string) {
  try {
    await navigator.clipboard.writeText(texto);
  } catch {
    const ta = document.createElement('textarea');
    ta.value = texto;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand('copy');
    } catch {
      /* si tampoco funciona, no rompemos la UI */
    }
    ta.remove();
  }
}

// Acciones por deportista en mora: copiar el recordatorio para pegarlo a mano, o
// enviarlo por WhatsApp (adjunta el QR de cobro de la escuela; solo ADMIN).
function MoraAcciones({
  item,
  orgNombre,
  isAdmin,
}: {
  item: MorosidadItem;
  orgNombre: string;
  isAdmin: boolean;
}) {
  const toast = useToast();
  const [enviando, setEnviando] = useState(false);
  const [enviado, setEnviado] = useState(false);

  async function copiar() {
    await copiarAlPortapapeles(mensajeMora(item, orgNombre));
    toast.success('Mensaje copiado');
  }

  async function enviar() {
    setEnviando(true);
    try {
      const res = await api.enviarRecordatorioMora(item.deportista_id);
      if (res.enviado) {
        setEnviado(true);
        toast.success(`Recordatorio enviado a ${item.nombre_completo}`);
      } else if (res.motivo === 'sin_telefono') {
        toast.error('El tutor no tiene un teléfono registrado.');
      } else {
        toast.error('No se pudo enviar el recordatorio por WhatsApp.');
      }
    } catch (err) {
      toast.error(
        err instanceof ApiError && err.isForbidden
          ? 'No tenés permiso para enviar recordatorios.'
          : 'No se pudo enviar por WhatsApp.',
      );
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="moras__acciones">
      <Button variant="ghost" size="sm" onClick={copiar}>
        Copiar
      </Button>
      {isAdmin && (
        <Button
          variant="ghost"
          size="sm"
          onClick={enviar}
          disabled={enviando || enviado}
          title="Enviar el recordatorio al tutor por WhatsApp (adjunta el QR de cobro)"
        >
          {enviado ? '✓ Enviado' : enviando ? 'Enviando…' : 'Enviar WhatsApp'}
        </Button>
      )}
    </div>
  );
}

export function PanelCobranza() {
  const { selected: sucursalId } = useSucursales();
  // viewRole es la verdad de la UI; el backend impone el permiso real (ADMIN).
  const { viewRole, org } = useAuth();
  const isAdmin = viewRole === 'ADMIN';
  const orgNombre = org?.nombre ?? 'LATINOSPORT';

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

  // Recordatorio de cobro por WhatsApp: id de la cuota en vuelo (deshabilita su
  // botón) + aviso transitorio del resultado.
  const [recordatorioEnvio, setRecordatorioEnvio] = useState<string | null>(null);
  const [recordatorioNota, setRecordatorioNota] = useState<Notice | null>(null);

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

  // Dispara el recordatorio de cobro por WhatsApp de UNA cuota (RNF-07: tiene
  // costo; el backend impone idempotencia y toggles). No reintentamos en bucle:
  // el botón queda deshabilitado mientras va la petición.
  const enviarRecordatorio = useCallback(
    async (cuota: CuotaListItem) => {
      if (recordatorioEnvio) return; // ya hay uno en vuelo
      setRecordatorioEnvio(cuota.id);
      setRecordatorioNota(null);
      try {
        const res = await api.enviarRecordatorio(cuota.id);
        const base = recordatorioNotice(res.motivo, res.enviado);
        setRecordatorioNota({
          ...base,
          text: `${cuota.deportista.nombre_completo}: ${base.text}`,
        });
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        const text =
          err instanceof ApiError
            ? err.isForbidden
              ? 'No tienes permiso para enviar recordatorios.'
              : err.status === 404
                ? 'La cuota ya no existe.'
                : err.message
            : 'No se pudo enviar el recordatorio.';
        setRecordatorioNota({ tone: 'error', text });
      } finally {
        setRecordatorioEnvio(null);
      }
    },
    [recordatorioEnvio],
  );

  const columns = useMemo<Column<CuotaListItem>[]>(
    () => [
      {
        key: 'deportista',
        header: 'Deportista',
        render: (c) => (
          <div className="cuota-cell">
            <Avatar name={c.deportista.nombre_completo} size="md" />
            <div className="cuota-cell__text">
              <span className="cuota-cell__name">{c.deportista.nombre_completo}</span>
              <span className="cuota-cell__meta">{c.categoria?.nombre ?? 'Sin categoría'}</span>
            </div>
          </div>
        ),
      },
      {
        key: 'sucursal',
        header: 'Sucursal',
        hideOnNarrow: true,
        render: (c) => c.sucursal?.nombre ?? '—',
      },
      {
        key: 'estado',
        header: 'Estado',
        align: 'center',
        render: (c) => <EstadoBadge estado={c.estado} />,
      },
      {
        key: 'monto',
        header: 'Saldo',
        align: 'right',
        // Abonos: mostramos el SALDO pendiente (lo que falta cobrar). Si hay un
        // abono parcial, el monto nominal de la cuota va como contexto debajo.
        render: (c) => {
          const tieneAbono = c.estado === 'PARCIAL' || Number(c.monto_pagado) > 0;
          return (
            <span className="cuota-cell__saldo">
              <span className="tabular">{formatMoney(c.saldo)}</span>
              {tieneAbono && c.saldo !== c.monto && (
                <span className="cuota-cell__saldo-de tabular">de {formatMoney(c.monto)}</span>
              )}
            </span>
          );
        },
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
            <div className="cuota-cell__acciones">
              {/* Recordatorio de cobro por WhatsApp — solo ADMIN (el backend lo exige). */}
              {isAdmin && (
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={recordatorioEnvio === c.id}
                  onClick={(e) => {
                    e.stopPropagation();
                    void enviarRecordatorio(c);
                  }}
                >
                  {recordatorioEnvio === c.id ? 'Enviando…' : 'Enviar WhatsApp'}
                </Button>
              )}
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
            </div>
          ),
      },
    ],
    [openPago, isAdmin, enviarRecordatorio, recordatorioEnvio],
  );

  const ingresos = panel?.ingresos_mes.monto;
  const ingresosMes = panel?.ingresos_mes;
  const activos = panel?.deportistas_activos;
  const pendientes = panel?.cuotas_pendientes;
  const vencidas = panel?.cuotas_vencidas;
  // Abonos: saldo a favor acumulado (Σ credito.saldo de la org). Solo se muestra
  // si hay crédito; si es 0/ausente no aporta y no abulta la grilla.
  const creditoTotal = panel?.credito_total;
  const tieneCredito = creditoTotal != null && Number(creditoTotal) > 0;

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
          hint={
            ingresosMes ? (
              <>
                <span className="kpi-metodo kpi-metodo--efectivo">
                  Efectivo {formatMoney(ingresosMes.efectivo)}
                </span>
                {' · '}
                <span className="kpi-metodo kpi-metodo--qr">
                  QR {formatMoney(ingresosMes.qr)}
                </span>
              </>
            ) : undefined
          }
          loading={!panel && !panelError}
        />
        <KPICard
          label="Deportistas activos"
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
        {tieneCredito && (
          <KPICard
            label="Crédito a favor"
            value={formatMoney(creditoTotal)}
            hint="saldo de abonos por aplicar"
            loading={!panel && !panelError}
          />
        )}
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

          {recordatorioNota && (
            <div
              className={`cobro-notice cobro-notice--${recordatorioNota.tone}`}
              role="status"
            >
              <span>{recordatorioNota.text}</span>
              <button
                type="button"
                className="cobro-notice__close"
                aria-label="Cerrar aviso"
                onClick={() => setRecordatorioNota(null)}
              >
                ✕
              </button>
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
              <p className="moras__empty">Sin deportistas en mora.</p>
            ) : (
              <ul className="moras">
                {panel.morosidad.map((m) => (
                  <li key={m.deportista_id} className="moras__item">
                    <div className="moras__row">
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
                    </div>
                    <MoraAcciones item={m} orgNombre={orgNombre} isAdmin={isAdmin} />
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
