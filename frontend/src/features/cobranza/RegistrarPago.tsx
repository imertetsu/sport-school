import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, ApiError, comprobantePdfUrl } from '@/api/client';
import type {
  CuotaListItem,
  EstadoPago,
  PagoOut,
  QrResponse,
} from '@/api/types';
import { Badge, Button, Card, EstadoBadge, Tabs, type TabItem } from '@/components/ui';
import { formatDate, formatMoney } from '@/lib/format';
import './RegistrarPago.css';

// Polling del estado del pago QR (C3): GET /cobranza/pagos/{id}.
const POLL_INTERVAL_MS = 2500;

export interface RegistrarPagoProps {
  // Cuota preseleccionada al abrir desde una fila; null = elegir alumno + cuota(s).
  cuotaInicial?: CuotaListItem | null;
  onClose: () => void;
  // Se invoca cuando un pago queda CONFIRMADO (refresca panel/tabla).
  onConfirmado?: () => void;
}

export function RegistrarPago({ cuotaInicial, onClose, onConfirmado }: RegistrarPagoProps) {
  // --- Selección de alumno + cuotas ---
  const [busqueda, setBusqueda] = useState('');
  const [cuotasAlumno, setCuotasAlumno] = useState<CuotaListItem[]>([]);
  const [cargandoCuotas, setCargandoCuotas] = useState(false);
  // Cuota(s) elegida(s) para cobrar (ids).
  const [seleccion, setSeleccion] = useState<string[]>(
    cuotaInicial ? [cuotaInicial.id] : [],
  );
  // Catálogo de cuotas conocidas (para resolver monto/etiqueta por id).
  const [catalogo, setCatalogo] = useState<CuotaListItem[]>(
    cuotaInicial ? [cuotaInicial] : [],
  );

  // Cargar cuotas pendientes del alumno de la cuota inicial (para multi-cuota).
  useEffect(() => {
    if (!cuotaInicial) return;
    const controller = new AbortController();
    let active = true;
    setCargandoCuotas(true);
    api
      .cuotas(
        { alumno_id: cuotaInicial.alumno.id, page: 1, page_size: 50 },
        controller.signal,
      )
      .then((res) => {
        if (!active) return;
        // Solo cobrables (no PAGADO). Mantén la inicial aunque venga filtrada.
        const cobrables = res.items.filter((c) => c.estado !== 'PAGADO');
        const merged = cobrables.some((c) => c.id === cuotaInicial.id)
          ? cobrables
          : [cuotaInicial, ...cobrables];
        setCuotasAlumno(merged);
        setCatalogo(merged);
      })
      .catch(() => {
        if (active) setCuotasAlumno([cuotaInicial]);
      })
      .finally(() => {
        if (active) setCargandoCuotas(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [cuotaInicial]);

  // Búsqueda de cuotas por nombre de alumno cuando se abre sin cuota inicial.
  useEffect(() => {
    if (cuotaInicial) return;
    const q = busqueda.trim();
    if (!q) {
      setCuotasAlumno([]);
      return;
    }
    const controller = new AbortController();
    let active = true;
    const t = setTimeout(() => {
      setCargandoCuotas(true);
      api
        .cuotas({ page: 1, page_size: 100 }, controller.signal)
        .then((res) => {
          if (!active) return;
          const cobrables = res.items.filter(
            (c) =>
              c.estado !== 'PAGADO' &&
              c.alumno.nombre_completo.toLowerCase().includes(q.toLowerCase()),
          );
          setCuotasAlumno(cobrables);
          setCatalogo((prev) => {
            const byId = new Map(prev.map((c) => [c.id, c]));
            for (const c of cobrables) byId.set(c.id, c);
            return [...byId.values()];
          });
        })
        .catch(() => {
          if (active) setCuotasAlumno([]);
        })
        .finally(() => {
          if (active) setCargandoCuotas(false);
        });
    }, 300);
    return () => {
      active = false;
      clearTimeout(t);
      controller.abort();
    };
  }, [busqueda, cuotaInicial]);

  const toggleCuota = useCallback((id: string) => {
    setSeleccion((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  }, []);

  const montoTotal = useMemo(() => {
    const byId = new Map(catalogo.map((c) => [c.id, c]));
    return seleccion.reduce((sum, id) => {
      const c = byId.get(id);
      return sum + (c ? Number(c.monto) : 0);
    }, 0);
  }, [seleccion, catalogo]);

  const listaCuotas = cuotaInicial ? cuotasAlumno : cuotasAlumno;

  const selector = (
    <div className="rp-selector">
      {!cuotaInicial && (
        <label className="rp-search">
          <span className="rp-search__label">Alumno</span>
          <input
            className="field__input"
            type="search"
            value={busqueda}
            onChange={(e) => setBusqueda(e.target.value)}
            placeholder="Buscar alumno…"
            autoFocus
          />
        </label>
      )}
      {cuotaInicial && (
        <p className="rp-alumno">
          <strong>{cuotaInicial.alumno.nombre_completo}</strong>
          <span className="rp-alumno__meta">
            {cuotaInicial.categoria.nombre} · {cuotaInicial.sucursal.nombre}
          </span>
        </p>
      )}

      <span className="rp-section-label">Cuota(s) a cobrar</span>
      {cargandoCuotas ? (
        <p className="rp-empty">Buscando…</p>
      ) : listaCuotas.length === 0 ? (
        <p className="rp-empty">
          {cuotaInicial || busqueda.trim()
            ? 'Sin cuotas por cobrar.'
            : 'Escribe el nombre de un alumno.'}
        </p>
      ) : (
        <ul className="rp-cuotas">
          {listaCuotas.map((c) => (
            <li key={c.id}>
              <label className="rp-cuota">
                <input
                  type="checkbox"
                  checked={seleccion.includes(c.id)}
                  onChange={() => toggleCuota(c.id)}
                />
                <span className="rp-cuota__body">
                  <span className="rp-cuota__top">
                    {!cuotaInicial && (
                      <span className="rp-cuota__alumno">{c.alumno.nombre_completo}</span>
                    )}
                    <EstadoBadge estado={c.estado} />
                  </span>
                  <span className="rp-cuota__meta">
                    Vence {formatDate(c.vence_el)}
                  </span>
                </span>
                <span className="rp-cuota__monto tabular">{formatMoney(c.monto)}</span>
              </label>
            </li>
          ))}
        </ul>
      )}

      <div className="rp-total">
        <span>Total a cobrar</span>
        <span className="rp-total__monto tabular">{formatMoney(montoTotal)}</span>
      </div>
    </div>
  );

  const tabs: TabItem[] = [
    {
      id: 'efectivo',
      label: 'Efectivo',
      content: <PagoEfectivo cuotaIds={seleccion} onConfirmado={onConfirmado} />,
    },
    {
      id: 'qr',
      label: 'QR',
      content: <PagoQr cuotaIds={seleccion} onConfirmado={onConfirmado} />,
    },
  ];

  return (
    <div className="rp-overlay" role="dialog" aria-modal="true" aria-label="Registrar pago">
      <div className="rp-modal">
        <header className="rp-modal__head">
          <h2 className="rp-modal__title">Registrar pago</h2>
          <button
            type="button"
            className="rp-modal__close"
            aria-label="Cerrar"
            onClick={onClose}
          >
            ✕
          </button>
        </header>
        <div className="rp-modal__body">
          {selector}
          <Tabs items={tabs} />
        </div>
      </div>
    </div>
  );
}

// --- Pago en efectivo: confirma y muestra comprobante (PDF + WhatsApp visual) ---
function PagoEfectivo({
  cuotaIds,
  onConfirmado,
}: {
  cuotaIds: string[];
  onConfirmado?: () => void;
}) {
  const [pago, setPago] = useState<PagoOut | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function confirmar() {
    if (cuotaIds.length === 0) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await api.pagoEfectivo({ cuota_ids: cuotaIds });
      setPago(res);
      onConfirmado?.();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : 'No se pudo registrar el pago en efectivo.',
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (pago) {
    return <Comprobante pago={pago} />;
  }

  return (
    <div className="rp-method">
      <p className="rp-method__hint">
        Registra el cobro en efectivo. Se aplicará a la(s) cuota(s) seleccionada(s) y se
        generará el comprobante.
      </p>
      {error && (
        <div className="page-error" role="alert">
          {error}
        </div>
      )}
      <Button
        variant="primary"
        onClick={confirmar}
        disabled={submitting || cuotaIds.length === 0}
      >
        {submitting ? 'Registrando…' : 'Confirmar pago en efectivo'}
      </Button>
    </div>
  );
}

// --- Pago por QR: muestra el QR y hace polling del estado (C3) ---
function PagoQr({
  cuotaIds,
  onConfirmado,
}: {
  cuotaIds: string[];
  onConfirmado?: () => void;
}) {
  const [qr, setQr] = useState<QrResponse | null>(null);
  const [estado, setEstado] = useState<EstadoPago | null>(null);
  const [pago, setPago] = useState<PagoOut | null>(null);
  const [generando, setGenerando] = useState(false);
  const [simulando, setSimulando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const onConfirmadoRef = useRef(onConfirmado);
  onConfirmadoRef.current = onConfirmado;

  const pagoId = qr?.pago_id ?? null;

  async function generarQr() {
    if (cuotaIds.length === 0) return;
    setGenerando(true);
    setError(null);
    try {
      const res = await api.pagoQr({ cuota_ids: cuotaIds });
      setQr(res);
      setEstado(res.estado);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'No se pudo generar el QR.');
    } finally {
      setGenerando(false);
    }
  }

  // Polling mientras el pago siga PENDIENTE (C3).
  useEffect(() => {
    if (!pagoId || estado !== 'PENDIENTE') return;
    const controller = new AbortController();
    let active = true;
    const timer = setInterval(() => {
      api
        .pago(pagoId, controller.signal)
        .then((p) => {
          if (!active) return;
          setEstado(p.estado);
          if (p.estado === 'CONFIRMADO') {
            setPago(p);
            onConfirmadoRef.current?.();
          }
        })
        .catch(() => {
          /* reintenta en el siguiente tick */
        });
    }, POLL_INTERVAL_MS);
    return () => {
      active = false;
      controller.abort();
      clearInterval(timer);
    };
  }, [pagoId, estado]);

  async function simular() {
    if (!pagoId) return;
    setSimulando(true);
    setError(null);
    try {
      const p = await api.simularConfirmacionQr(pagoId);
      setEstado(p.estado);
      if (p.estado === 'CONFIRMADO') {
        setPago(p);
        onConfirmadoRef.current?.();
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'No se pudo simular el pago.');
    } finally {
      setSimulando(false);
    }
  }

  if (pago && estado === 'CONFIRMADO') {
    return <Comprobante pago={pago} confirmadoQr />;
  }

  if (!qr) {
    return (
      <div className="rp-method">
        <p className="rp-method__hint">
          Genera un código QR para que el alumno pague. El estado se confirma automáticamente.
        </p>
        {error && (
          <div className="page-error" role="alert">
            {error}
          </div>
        )}
        <Button
          variant="primary"
          onClick={generarQr}
          disabled={generando || cuotaIds.length === 0}
        >
          {generando ? 'Generando…' : 'Generar QR'}
        </Button>
      </div>
    );
  }

  return (
    <div className="rp-qr">
      <img className="rp-qr__img" src={qr.qr_png_data_url} alt="Código QR de pago" />
      <p className="rp-qr__monto tabular">{formatMoney(qr.monto)}</p>
      <div className="rp-qr__estado">
        {estado === 'CONFIRMADO' ? (
          <Badge tone="paid">✓ Pago confirmado</Badge>
        ) : estado === 'FALLIDO' ? (
          <Badge tone="overdue">Pago fallido</Badge>
        ) : (
          <span className="rp-qr__waiting">
            <span className="rp-qr__spinner" aria-hidden="true" />
            Esperando pago…
          </span>
        )}
      </div>
      {error && (
        <div className="page-error" role="alert">
          {error}
        </div>
      )}
      {estado === 'PENDIENTE' && (
        <Button variant="secondary" onClick={simular} disabled={simulando}>
          {simulando ? 'Simulando…' : 'Simular pago'}
        </Button>
      )}
    </div>
  );
}

// --- Comprobante: PDF (descarga real) + WhatsApp (visual) ---
function Comprobante({ pago, confirmadoQr }: { pago: PagoOut; confirmadoQr?: boolean }) {
  const [whatsappEnviado, setWhatsappEnviado] = useState(false);
  return (
    <div className="rp-comprobante">
      <Card>
        <div className="rp-comprobante__head">
          <Badge tone="paid">✓ {confirmadoQr ? 'Pago confirmado' : 'Pago registrado'}</Badge>
          <span className="rp-comprobante__monto tabular">{formatMoney(pago.monto)}</span>
        </div>
        <p className="rp-comprobante__text">
          Comprobante generado. Descárgalo en PDF o envíalo por WhatsApp.
        </p>
        <div className="rp-comprobante__actions">
          <a
            className="btn btn--secondary btn--md"
            href={comprobantePdfUrl(pago.id)}
            target="_blank"
            rel="noopener noreferrer"
            download
          >
            Descargar PDF
          </a>
          <Button
            variant="ghost"
            onClick={() => setWhatsappEnviado(true)}
            disabled={whatsappEnviado}
          >
            {whatsappEnviado ? 'Enviado por WhatsApp' : 'Enviar por WhatsApp'}
          </Button>
        </div>
      </Card>
    </div>
  );
}
