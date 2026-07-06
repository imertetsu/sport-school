import { useCallback, useEffect, useMemo, useState } from 'react';
import { api, ApiError, comprobantePdfUrl } from '@/api/client';
import type { CuotaListItem, PagoOut, RegistrarPagoEfectivoBody } from '@/api/types';
import { Badge, Button, Card, EstadoBadge, Field } from '@/components/ui';
import { formatDate, formatMoney, mesLargo } from '@/lib/format';
import './RegistrarPago.css';

// Fecha de HOY en formato YYYY-MM-DD (local): default del campo "Fecha de pago".
function hoyISO(): string {
  const d = new Date();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${mm}-${dd}`;
}

export interface RegistrarPagoProps {
  // Cuota preseleccionada al abrir desde una fila; null = elegir deportista + cuota(s).
  cuotaInicial?: CuotaListItem | null;
  onClose: () => void;
  // Se invoca cuando un pago queda CONFIRMADO (refresca panel/tabla).
  onConfirmado?: () => void;
}

export function RegistrarPago({ cuotaInicial, onClose, onConfirmado }: RegistrarPagoProps) {
  // --- Selección de deportista + cuotas ---
  const [busqueda, setBusqueda] = useState('');
  const [cuotasDeportista, setCuotasDeportista] = useState<CuotaListItem[]>([]);
  const [cargandoCuotas, setCargandoCuotas] = useState(false);
  // Cuota(s) elegida(s) para cobrar (ids).
  const [seleccion, setSeleccion] = useState<string[]>(
    cuotaInicial ? [cuotaInicial.id] : [],
  );
  // Catálogo de cuotas conocidas (para resolver monto/etiqueta por id).
  const [catalogo, setCatalogo] = useState<CuotaListItem[]>(
    cuotaInicial ? [cuotaInicial] : [],
  );

  // Cargar cuotas pendientes del deportista de la cuota inicial (para multi-cuota).
  useEffect(() => {
    if (!cuotaInicial) return;
    const controller = new AbortController();
    let active = true;
    setCargandoCuotas(true);
    api
      .cuotas(
        { deportista_id: cuotaInicial.deportista.id, page: 1, page_size: 50 },
        controller.signal,
      )
      .then((res) => {
        if (!active) return;
        // Solo cobrables (no PAGADO). Mantén la inicial aunque venga filtrada.
        const cobrables = res.items.filter((c) => c.estado !== 'PAGADO');
        const merged = cobrables.some((c) => c.id === cuotaInicial.id)
          ? cobrables
          : [cuotaInicial, ...cobrables];
        setCuotasDeportista(merged);
        setCatalogo(merged);
      })
      .catch(() => {
        if (active) setCuotasDeportista([cuotaInicial]);
      })
      .finally(() => {
        if (active) setCargandoCuotas(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [cuotaInicial]);

  // Búsqueda de cuotas por nombre de deportista cuando se abre sin cuota inicial.
  useEffect(() => {
    if (cuotaInicial) return;
    const q = busqueda.trim();
    if (!q) {
      setCuotasDeportista([]);
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
              c.deportista.nombre_completo.toLowerCase().includes(q.toLowerCase()),
          );
          setCuotasDeportista(cobrables);
          setCatalogo((prev) => {
            const byId = new Map(prev.map((c) => [c.id, c]));
            for (const c of cobrables) byId.set(c.id, c);
            return [...byId.values()];
          });
        })
        .catch(() => {
          if (active) setCuotasDeportista([]);
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

  // RF-ABO-11: un pago aplica a cuotas de UNA sola inscripción/deportista (el crédito
  // es por inscripción). El deportista de la selección actual ancla qué se puede sumar.
  const deportistaSeleccionadoId = useMemo(() => {
    for (const id of seleccion) {
      const c = catalogoById.get(id);
      if (c) return c.deportista.id;
    }
    return null;
  }, [seleccion, catalogoById]);

  const toggleCuota = useCallback(
    (cuota: CuotaListItem) => {
      setSeleccion((prev) => {
        if (prev.includes(cuota.id)) {
          return prev.filter((x) => x !== cuota.id);
        }
        // Si ya hay selección de otro deportista, la reemplazamos (no se mezclan deportistas).
        const ancla = prev
          .map((id) => catalogoById.get(id))
          .find((c): c is CuotaListItem => c != null);
        if (ancla && ancla.deportista.id !== cuota.deportista.id) {
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

  const listaCuotas = cuotasDeportista;

  const selector = (
    <div className="rp-selector">
      {!cuotaInicial && (
        <label className="rp-search">
          <span className="rp-search__label">Deportista</span>
          <input
            className="field__input"
            type="search"
            value={busqueda}
            onChange={(e) => setBusqueda(e.target.value)}
            placeholder="Buscar deportista…"
            autoFocus
          />
        </label>
      )}
      {cuotaInicial && (
        <p className="rp-deportista">
          <strong>{cuotaInicial.deportista.nombre_completo}</strong>
          <span className="rp-deportista__meta">
            {cuotaInicial.categoria?.nombre ?? 'Sin categoría'} · {cuotaInicial.sucursal?.nombre ?? '—'}
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
            : 'Escribe el nombre de un deportista.'}
        </p>
      ) : (
        <ul className="rp-cuotas">
          {listaCuotas.map((c) => {
            // RF-ABO-11: solo cuotas del deportista ya anclado son combinables.
            const bloqueada =
              deportistaSeleccionadoId != null && c.deportista.id !== deportistaSeleccionadoId;
            return (
              <li key={c.id}>
                <label
                  className={`rp-cuota${bloqueada ? ' rp-cuota--disabled' : ''}`}
                  title={
                    bloqueada
                      ? 'Solo puedes cobrar cuotas de un mismo deportista por pago.'
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
                        <span className="rp-cuota__deportista">{c.deportista.nombre_completo}</span>
                      )}
                      <EstadoBadge estado={c.estado} />
                    </span>
                    {/* La cuota se etiqueta por el MES en que vence (DICIEMBRE 2025),
                        junto a la fecha exacta de vencimiento. */}
                    <span className="rp-cuota__meta">
                      Cuota {mesLargo(c.vence_el)} {c.vence_el.slice(0, 4)} | Vence{' '}
                      {formatDate(c.vence_el)}
                    </span>
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
          <PagoManual cuotaIds={seleccion} saldoTotal={saldoTotal} onConfirmado={onConfirmado} />
        </div>
      </div>
    </div>
  );
}

// --- Pago manual: método (efectivo/QR) + fecha + monto; confirma y muestra comprobante ---
function PagoManual({
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
  // Método del pago manual: efectivo o QR/transferencia (solo etiqueta; mismo flujo).
  const [metodo, setMetodo] = useState<'EFECTIVO' | 'QR'>('EFECTIVO');
  // Fecha real del pago: por defecto hoy, editable (permite cargar meses viejos).
  const [fechaPago, setFechaPago] = useState<string>(hoyISO());
  // "Monto recibido" en caja. Vacío => paga el total (Σ saldo). El backend
  // distribuye FIFO y guarda el sobrepago como crédito de la inscripción.
  const [montoRecibido, setMontoRecibido] = useState('');
  // Confirmación explícita del sobrepago: al pagar de más, pedir un OK antes de
  // generar saldo a favor (evita el error de tipear de más sin querer).
  const [confirmarSobrepago, setConfirmarSobrepago] = useState(false);

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
    if (cuotaIds.length === 0 || recibidoInvalido || !fechaPago) return;
    // Sobrepago: exigir confirmación explícita antes de generar saldo a favor.
    if (excedente > 0 && !confirmarSobrepago) {
      setConfirmarSobrepago(true);
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const body: RegistrarPagoEfectivoBody = {
        cuota_ids: cuotaIds,
        metodo,
        fecha_pago: fechaPago,
      };
      // Vacío o igual al total => omitimos monto_recibido (camino "paga todo"
      // intacto). Solo lo mandamos cuando el operador escribió un valor distinto.
      if (recibidoNum !== null && recibidoNum !== saldoTotal) {
        body.monto_recibido = montoRecibido.trim();
      }
      const res = await api.pagoEfectivo(body);
      setPago(res);
      onConfirmado?.();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'No se pudo registrar el pago.');
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
        Registra el cobro. Se aplicará a la(s) cuota(s) seleccionada(s) y se generará el
        comprobante.
      </p>

      <div className="rp-metodo">
        <span className="rp-section-label">Método de pago</span>
        <div className="rp-metodo__opts" role="radiogroup" aria-label="Método de pago">
          {(['EFECTIVO', 'QR'] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={metodo === m}
              className={`rp-metodo__opt${metodo === m ? ' is-active' : ''}`}
              onClick={() => setMetodo(m)}
            >
              {m === 'EFECTIVO' ? 'Efectivo' : 'QR'}
            </button>
          ))}
        </div>
      </div>

      <Field
        type="date"
        label="Fecha de pago"
        value={fechaPago}
        max={hoyISO()}
        onChange={(e) => setFechaPago(e.target.value)}
        hint="Por defecto hoy. Cámbiala si el pago fue en otra fecha."
      />

      <Field
        type="number"
        inputMode="decimal"
        min="0"
        step="0.01"
        label="Monto recibido"
        value={montoRecibido}
        onChange={(e) => {
          setMontoRecibido(e.target.value);
          setConfirmarSobrepago(false);
        }}
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
      {confirmarSobrepago ? (
        <div className="rp-sobrepago" role="alert">
          <p className="rp-sobrepago__msg">
            ⚠️ Estás registrando <strong>{formatMoney(excedente)} de más</strong> sobre el
            total a cobrar. Ese excedente quedará como <strong>saldo a favor</strong> del
            deportista. Si fue un error, revisá el monto.
          </p>
          <div className="rp-sobrepago__actions">
            <Button
              variant="secondary"
              onClick={() => setConfirmarSobrepago(false)}
              disabled={submitting}
            >
              Revisar monto
            </Button>
            <Button variant="primary" onClick={confirmar} disabled={submitting}>
              {submitting ? 'Registrando…' : 'Registrar de todas formas'}
            </Button>
          </div>
        </div>
      ) : (
        <Button
          variant="primary"
          onClick={confirmar}
          disabled={submitting || cuotaIds.length === 0 || recibidoInvalido || !fechaPago}
        >
          {submitting ? 'Registrando…' : 'Confirmar pago'}
        </Button>
      )}
    </div>
  );
}

// --- Comprobante: PDF (descarga real) + WhatsApp (visual) ---
function Comprobante({ pago }: { pago: PagoOut }) {
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
            {hayParcial ? 'Pago parcial registrado' : '✓ Pago registrado'}
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
