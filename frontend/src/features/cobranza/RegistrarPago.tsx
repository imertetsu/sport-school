import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, ApiError, comprobantePdfUrl } from '@/api/client';
import type {
  CuotaListItem,
  EstadoPago,
  PagoOut,
  QrResponse,
} from '@/api/types';
import { Badge, Button, Card, EstadoBadge, Field, Tabs, type TabItem } from '@/components/ui';
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

  const catalogoById = useMemo(
    () => new Map(catalogo.map((c) => [c.id, c])),
    [catalogo],
  );

  // RF-ABO-11: un pago aplica a cuotas de UNA sola inscripción/alumno (el crédito
  // es por inscripción). El alumno de la selección actual ancla qué se puede sumar.
  const alumnoSeleccionadoId = useMemo(() => {
    for (const id of seleccion) {
      const c = catalogoById.get(id);
      if (c) return c.alumno.id;
    }
    return null;
  }, [seleccion, catalogoById]);

  const toggleCuota = useCallback(
    (cuota: CuotaListItem) => {
      setSeleccion((prev) => {
        if (prev.includes(cuota.id)) {
          return prev.filter((x) => x !== cuota.id);
        }
        // Si ya hay selección de otro alumno, la reemplazamos (no se mezclan alumnos).
        const ancla = prev
          .map((id) => catalogoById.get(id))
          .find((c): c is CuotaListItem => c != null);
        if (ancla && ancla.alumno.id !== cuota.alumno.id) {
          return [cuota.id];
        }
        return [...prev, cuota.id];
      });
    },
    [catalogoById],
  );

  // Total a cobrar = Σ SALDO de lo seleccionado (Abonos: el saldo es lo que falta).
  const saldoTotal = useMemo(() => {
    return seleccion.reduce((sum, id) => {
      const c = catalogoById.get(id);
      return sum + (c ? Number(c.saldo) : 0);
    }, 0);
  }, [seleccion, catalogoById]);

  const listaCuotas = cuotasAlumno;

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
          {listaCuotas.map((c) => {
            // RF-ABO-11: solo cuotas del alumno ya anclado son combinables.
            const bloqueada =
              alumnoSeleccionadoId != null && c.alumno.id !== alumnoSeleccionadoId;
            return (
              <li key={c.id}>
                <label
                  className={`rp-cuota${bloqueada ? ' rp-cuota--disabled' : ''}`}
                  title={
                    bloqueada
                      ? 'Solo puedes cobrar cuotas de un mismo alumno por pago.'
                      : undefined
                  }
                >
                  <input
                    type="checkbox"
                    checked={seleccion.includes(c.id)}
                    onChange={() => toggleCuota(c)}
                    disabled={bloqueada}
                  />
                  <span className="rp-cuota__body">
                    <span className="rp-cuota__top">
                      {!cuotaInicial && (
                        <span className="rp-cuota__alumno">{c.alumno.nombre_completo}</span>
                      )}
                      <EstadoBadge estado={c.estado} />
                    </span>
                    <span className="rp-cuota__meta">Vence {formatDate(c.vence_el)}</span>
                  </span>
                  <span className="rp-cuota__monto tabular">{formatMoney(c.saldo)}</span>
                </label>
              </li>
            );
          })}
        </ul>
      )}

      <div className="rp-total">
        <span>Total a cobrar</span>
        <span className="rp-total__monto tabular">{formatMoney(saldoTotal)}</span>
      </div>
    </div>
  );

  const tabs: TabItem[] = [
    {
      id: 'efectivo',
      label: 'Efectivo',
      content: (
        <PagoEfectivo
          cuotaIds={seleccion}
          saldoTotal={saldoTotal}
          onConfirmado={onConfirmado}
        />
      ),
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
  saldoTotal,
  onConfirmado,
}: {
  cuotaIds: string[];
  // Σ saldo de lo seleccionado: default del "Monto recibido" (Abonos).
  saldoTotal: number;
  onConfirmado?: () => void;
}) {
  const [pago, setPago] = useState<PagoOut | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // "Monto recibido" en caja. Vacío => paga el total (Σ saldo). El backend
  // distribuye FIFO y guarda el sobrepago como crédito de la inscripción.
  const [montoRecibido, setMontoRecibido] = useState('');

  const recibidoNum = montoRecibido.trim() === '' ? null : Number(montoRecibido);
  const recibidoInvalido =
    recibidoNum !== null && (Number.isNaN(recibidoNum) || recibidoNum <= 0);
  // Sobrepago que iría a crédito (preview; el backend tiene la última palabra).
  const excedente =
    recibidoNum !== null && !recibidoInvalido && recibidoNum > saldoTotal
      ? recibidoNum - saldoTotal
      : 0;
  const parcial =
    recibidoNum !== null && !recibidoInvalido && recibidoNum < saldoTotal;

  async function confirmar() {
    if (cuotaIds.length === 0 || recibidoInvalido) return;
    setSubmitting(true);
    setError(null);
    try {
      // Vacío o igual al total => omitimos monto_recibido (camino "paga todo"
      // intacto). Solo lo mandamos cuando el operador escribió un valor distinto.
      const body =
        recibidoNum === null || recibidoNum === saldoTotal
          ? { cuota_ids: cuotaIds }
          : { cuota_ids: cuotaIds, monto_recibido: montoRecibido.trim() };
      const res = await api.pagoEfectivo(body);
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
      <Field
        type="number"
        inputMode="decimal"
        min="0"
        step="0.01"
        label="Monto recibido"
        value={montoRecibido}
        onChange={(e) => setMontoRecibido(e.target.value)}
        placeholder={saldoTotal > 0 ? String(saldoTotal) : '0'}
        error={recibidoInvalido ? 'Ingresa un monto mayor a 0.' : undefined}
        hint={
          recibidoInvalido
            ? undefined
            : excedente > 0
              ? `Sobrepago: ${formatMoney(excedente)} quedará como crédito a favor.`
              : parcial
                ? 'Pago parcial: el saldo restante queda pendiente.'
                : 'Vacío = cobrar el total seleccionado.'
        }
      />
      {error && (
        <div className="page-error" role="alert">
          {error}
        </div>
      )}
      <Button
        variant="primary"
        onClick={confirmar}
        disabled={submitting || cuotaIds.length === 0 || recibidoInvalido}
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
  const cuotas = pago.cuotas_aplicadas ?? [];
  const creditoAplicado = Number(pago.credito_aplicado ?? 0);
  const creditoGenerado = Number(pago.credito_generado ?? 0);
  // ¿Quedó algo a medias? (saldo restante > 0 en alguna cuota → estado PARCIAL).
  const hayParcial = cuotas.some(
    (c) => c.estado === 'PARCIAL' || Number(c.saldo_restante) > 0,
  );
  return (
    <div className="rp-comprobante">
      <Card>
        <div className="rp-comprobante__head">
          <Badge tone={hayParcial ? 'pending' : 'paid'}>
            {hayParcial
              ? 'Pago parcial registrado'
              : `✓ ${confirmadoQr ? 'Pago confirmado' : 'Pago registrado'}`}
          </Badge>
          <span className="rp-comprobante__monto tabular">{formatMoney(pago.monto)}</span>
        </div>
        {pago.numero_recibo && (
          <p className="rp-comprobante__recibo">Recibo {pago.numero_recibo}</p>
        )}
        <p className="rp-comprobante__text">
          Comprobante generado. Descárgalo en PDF o envíalo por WhatsApp.
        </p>

        {cuotas.length > 0 && (
          <ul className="rp-aplicaciones">
            {cuotas.map((c) => (
              <li key={c.cuota_id} className="rp-aplicacion">
                <span className="rp-aplicacion__top">
                  <EstadoBadge estado={c.estado} />
                  <span className="rp-aplicacion__aplicado tabular">
                    {formatMoney(c.monto_aplicado)}
                  </span>
                </span>
                {Number(c.saldo_restante) > 0 && (
                  <span className="rp-aplicacion__saldo tabular">
                    Saldo restante: {formatMoney(c.saldo_restante)}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}

        {(creditoAplicado > 0 || creditoGenerado > 0) && (
          <div className="rp-credito">
            {creditoAplicado > 0 && (
              <p className="rp-credito__line">
                <span>Crédito aplicado</span>
                <span className="tabular">−{formatMoney(creditoAplicado)}</span>
              </p>
            )}
            {creditoGenerado > 0 && (
              <p className="rp-credito__line rp-credito__line--favor">
                <span>Saldo a favor generado</span>
                <span className="tabular">{formatMoney(creditoGenerado)}</span>
              </p>
            )}
          </div>
        )}

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
