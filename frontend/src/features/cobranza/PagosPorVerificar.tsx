import { useEffect, useState } from 'react';
import { api, ApiError, resolveSignedUrl } from '@/api/client';
import type {
  ComprobanteCuotaElegible,
  ComprobantePendienteItem,
} from '@/api/types';
import { Button, Card, EstadoBadge, SelectField, useToast } from '@/components/ui';
import { formatDate, formatMoney } from '@/lib/format';
import './PagosPorVerificar.css';

const PAGE_SIZE = 20;

// "Pagos por verificar" (epic pagos-qr-comprobante, C6) — SOLO ADMIN. La ruta
// /pagos-por-verificar ya está gateada con RoleRoute allow={['ADMIN']}; el backend
// además impone require_role("ADMIN") y scopea SIEMPRE al org del token. Cola
// pre-llena por el OCR + match por teléfono: el admin confirma en 1 clic (reusa
// registrar_pago_efectivo, idempotente) o rechaza. NUNCA auto-confirma (v1).
export function PagosPorVerificar() {
  const toast = useToast();
  const [items, setItems] = useState<ComprobantePendienteItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  // Comprobante en proceso de confirmación (abre el modal de confirmar).
  const [confirmando, setConfirmando] = useState<ComprobantePendienteItem | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    api
      .comprobantesPendientes(
        { estado: 'PENDIENTE', page, page_size: PAGE_SIZE },
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
        if (err instanceof ApiError && err.isForbidden) {
          setError('No tienes permiso para ver los pagos por verificar.');
        } else {
          setError(
            err instanceof ApiError ? err.message : 'No se pudieron cargar los comprobantes.',
          );
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [page, reloadKey]);

  function recargar() {
    setReloadKey((k) => k + 1);
  }

  async function rechazar(item: ComprobantePendienteItem) {
    const ok = window.confirm(
      '¿Rechazar este comprobante? No se registrará ningún pago. Esta acción se puede revisar luego en el filtro de rechazados.',
    );
    if (!ok) return;
    try {
      await api.rechazarComprobante(item.id);
      toast.success('Comprobante rechazado');
      recargar();
    } catch (err) {
      const msg =
        err instanceof ApiError ? err.message : 'No se pudo rechazar el comprobante.';
      setError(msg);
      toast.error(msg);
    }
  }

  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="por-verificar">
      <header className="page-head">
        <div>
          <h1 className="page-head__title">Pagos por verificar</h1>
          <p className="page-head__subtitle">
            {loading
              ? 'Cargando…'
              : `${total} comprobante${total === 1 ? '' : 's'} pendiente${
                  total === 1 ? '' : 's'
                } de revisión`}
          </p>
        </div>
      </header>

      {error && (
        <div className="page-error" role="alert">
          {error}
        </div>
      )}

      {!loading && items.length === 0 && !error && (
        <Card>
          <p className="por-verificar__empty">
            No hay comprobantes por verificar. Cuando un tutor responda con la captura
            de su pago por WhatsApp, aparecerá aquí.
          </p>
        </Card>
      )}

      <div className="por-verificar__list">
        {items.map((item) => (
          <ComprobanteCard
            key={item.id}
            item={item}
            onConfirmar={() => setConfirmando(item)}
            onRechazar={() => rechazar(item)}
          />
        ))}
      </div>

      {total > PAGE_SIZE && (
        <div className="por-verificar__pager">
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

      {confirmando && (
        <ConfirmarComprobante
          item={confirmando}
          onClose={() => setConfirmando(null)}
          onConfirmado={() => {
            setConfirmando(null);
            recargar();
          }}
        />
      )}
    </div>
  );
}

// Tarjeta de un comprobante: imagen + tutor + cuota sugerida + datos del OCR.
// Todos los campos del OCR pueden ser null (best-effort) -> fallback explícito.
function ComprobanteCard({
  item,
  onConfirmar,
  onRechazar,
}: {
  item: ComprobantePendienteItem;
  onConfirmar: () => void;
  onRechazar: () => void;
}) {
  const sinIdentificar = item.tutor == null;

  return (
    <Card padded={false} className="por-verificar__card">
      <div className="pv-card">
        <div className="pv-card__media">
          {/* Binario servido por URL FIRMADA (item.imagen_url); el <img> la carga
              directo. resolveSignedUrl la hace absoluta si llega relativa. El token
              se renueva al recargar la cola tras confirmar/rechazar. */}
          <img
            src={resolveSignedUrl(item.imagen_url)}
            alt="Comprobante de pago enviado por el tutor"
            className="pv-card__img"
            loading="lazy"
          />
        </div>

        <div className="pv-card__info">
          <div className="pv-card__row">
            <span className="pv-card__label">Tutor</span>
            <span className="pv-card__value">
              {item.tutor ? (
                item.tutor.nombres
              ) : (
                <span className="pv-card__warn">Sin identificar</span>
              )}
            </span>
          </div>
          <div className="pv-card__row">
            <span className="pv-card__label">Teléfono</span>
            <span className="pv-card__value tabular">{item.from_telefono || '—'}</span>
          </div>

          {item.cuota_sugerida ? (
            <div className="pv-card__cuota">
              <span className="pv-card__label">Cuota sugerida</span>
              <div className="pv-card__cuota-body">
                <span className="pv-card__value">
                  {item.cuota_sugerida.deportista_nombre}
                </span>
                <span className="pv-card__sub">
                  Vence {formatDate(item.cuota_sugerida.vence_el)} · Saldo{' '}
                  <span className="tabular">{formatMoney(item.cuota_sugerida.saldo)}</span>
                </span>
                <EstadoBadge estado={item.cuota_sugerida.estado} />
              </div>
            </div>
          ) : (
            <div className="pv-card__cuota">
              <span className="pv-card__label">Cuota sugerida</span>
              <span className="pv-card__sub">
                {sinIdentificar
                  ? 'Sin identificar — asigna la cuota manualmente al confirmar.'
                  : 'Sin cuota sugerida — elige una al confirmar.'}
              </span>
            </div>
          )}

          <div className="pv-card__ocr">
            <span className="pv-card__label">Lectura del comprobante (OCR)</span>
            <div className="pv-card__ocr-grid">
              <div>
                <span className="pv-card__sub">Monto</span>
                <span className="pv-card__value tabular">
                  {item.monto_ocr != null ? formatMoney(item.monto_ocr) : '—'}
                </span>
              </div>
              <div>
                <span className="pv-card__sub">N° transacción</span>
                <span className="pv-card__value tabular">
                  {item.transaccion_id_ocr ?? '—'}
                </span>
              </div>
              <div>
                <span className="pv-card__sub">Fecha</span>
                <span className="pv-card__value">
                  {item.fecha_ocr ? formatDate(item.fecha_ocr) : '—'}
                </span>
              </div>
            </div>
          </div>

          <div className="pv-card__foot">
            <span className="pv-card__sub">Recibido {formatDate(item.created_at)}</span>
            <div className="pv-card__actions">
              <Button variant="ghost" size="sm" onClick={onRechazar}>
                Rechazar
              </Button>
              <Button variant="primary" size="sm" onClick={onConfirmar}>
                Confirmar
              </Button>
            </div>
          </div>
        </div>
      </div>
    </Card>
  );
}

// Modal de confirmación: si hay cuota sugerida + monto_ocr, vienen prellenados; el
// admin puede cambiar la cuota (dropdown poblado con GET /comprobantes/{id}/cuotas)
// y/o el monto. El backend reusa registrar_pago_efectivo (idempotente). Un
// comprobante "sin identificar" requiere elegir una cuota antes de confirmar; si el
// backend no resuelve cuotas sin tutor, la lista llega vacía y se ofrece rechazar.
function ConfirmarComprobante({
  item,
  onClose,
  onConfirmado,
}: {
  item: ComprobantePendienteItem;
  onClose: () => void;
  onConfirmado: () => void;
}) {
  const toast = useToast();
  // Cuotas elegibles para el dropdown (incluye la sugerida si existe). Se cargan
  // siempre para permitir reasignar; "sin identificar" depende de que el backend
  // las resuelva sin tutor.
  const [cuotas, setCuotas] = useState<ComprobanteCuotaElegible[]>([]);
  const [cargandoCuotas, setCargandoCuotas] = useState(true);
  const [cuotasError, setCuotasError] = useState<string | null>(null);

  const [cuotaId, setCuotaId] = useState<string>(item.cuota_sugerida?.cuota_id ?? '');
  const [monto, setMonto] = useState<string>(item.monto_ocr ?? '');

  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [cuotaError, setCuotaError] = useState<string | null>(null);
  const [montoError, setMontoError] = useState<string | null>(null);

  // Carga las cuotas elegibles de la escuela para el dropdown.
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setCargandoCuotas(true);
    setCuotasError(null);
    api
      .comprobanteCuotas(item.id, controller.signal)
      .then((res) => {
        if (!active) return;
        setCuotas(res);
        // Si la sugerida no vino en la lista pero existe, la añadimos al frente
        // para que el dropdown la muestre seleccionada.
        if (
          item.cuota_sugerida &&
          !res.some((c) => c.cuota_id === item.cuota_sugerida!.cuota_id)
        ) {
          setCuotas([item.cuota_sugerida, ...res]);
        }
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setCuotasError(
          err instanceof ApiError
            ? err.message
            : 'No se pudieron cargar las cuotas para asignar.',
        );
      })
      .finally(() => {
        if (active) setCargandoCuotas(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [item.id, item.cuota_sugerida]);

  // Al cambiar la cuota elegida, si el monto está vacío lo prellenamos con el saldo.
  function elegirCuota(id: string) {
    setCuotaId(id);
    setCuotaError(null);
    if (!monto.trim()) {
      const c = cuotas.find((x) => x.cuota_id === id);
      if (c) setMonto(c.saldo);
    }
  }

  async function confirmar() {
    setFormError(null);
    setCuotaError(null);
    setMontoError(null);

    if (!cuotaId) {
      setCuotaError('Elige la cuota a la que se aplica el pago.');
      return;
    }
    const montoNum = Number(monto);
    if (!monto.trim() || Number.isNaN(montoNum) || montoNum <= 0) {
      setMontoError('Ingresa un monto mayor a 0.');
      return;
    }

    setSubmitting(true);
    try {
      await api.confirmarComprobante(item.id, { cuota_id: cuotaId, monto: monto.trim() });
      toast.success('Pago confirmado');
      onConfirmado();
    } catch (err) {
      let msg = 'No se pudo confirmar el pago. Inténtalo de nuevo.';
      if (err instanceof ApiError) {
        if (err.isForbidden) {
          msg = 'No tienes permiso para confirmar comprobantes.';
        } else if (err.isConflict) {
          msg = 'Este comprobante ya fue resuelto.';
        } else if (err.isValidation) {
          msg = err.fieldErrors[0]?.msg ?? err.message;
        } else {
          msg = err.message;
        }
      }
      setFormError(msg);
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  }

  const sinIdentificar = item.tutor == null;
  const sinCuotas = !cargandoCuotas && cuotas.length === 0;

  return (
    <div
      className="pv-modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label="Confirmar pago del comprobante"
      onClick={(e) => {
        if (e.target === e.currentTarget && !submitting) onClose();
      }}
    >
      <div className="pv-modal">
        <Card title="Confirmar pago">
          <p className="pv-modal__lead">
            Se registrará un pago en efectivo aplicado a la cuota elegida. Esta acción
            queda asociada al comprobante recibido.
          </p>

          {sinIdentificar && (
            <div className="pv-modal__notice" role="status">
              Comprobante sin identificar: el teléfono no coincide con ningún tutor.
              Asigna manualmente la cuota a la que corresponde.
            </div>
          )}

          {formError && (
            <div className="page-error" role="alert">
              {formError}
            </div>
          )}

          {cargandoCuotas ? (
            <p className="pv-modal__loading">Cargando cuotas…</p>
          ) : cuotasError ? (
            <div className="page-error" role="alert">
              {cuotasError}
            </div>
          ) : sinCuotas ? (
            <div className="pv-modal__notice" role="status">
              No hay cuotas con saldo disponibles para asignar este comprobante. Puedes
              rechazarlo o dejarlo pendiente para asignarlo más adelante.
            </div>
          ) : (
            <div className="pv-modal__form">
              <SelectField
                label="Cuota"
                value={cuotaId}
                onChange={(e) => elegirCuota(e.target.value)}
                error={cuotaError ?? undefined}
                required
              >
                <option value="">Elige una cuota…</option>
                {cuotas.map((c) => (
                  <option key={c.cuota_id} value={c.cuota_id}>
                    {c.deportista_nombre} · vence {formatDate(c.vence_el)} · saldo{' '}
                    {formatMoney(c.saldo)}
                  </option>
                ))}
              </SelectField>

              <div className="field">
                <label className="field__label" htmlFor="pv-monto">
                  Monto
                  <span className="field__required" aria-hidden="true"> *</span>
                </label>
                <input
                  id="pv-monto"
                  className="field__input"
                  type="number"
                  inputMode="decimal"
                  min="0"
                  step="0.01"
                  value={monto}
                  onChange={(e) => {
                    setMonto(e.target.value);
                    setMontoError(null);
                  }}
                  aria-invalid={montoError ? true : undefined}
                  placeholder="0.00"
                  required
                />
                {montoError ? (
                  <p className="field__error" role="alert">
                    {montoError}
                  </p>
                ) : (
                  <p className="field__hint">
                    {item.monto_ocr != null
                      ? 'Prellenado con el monto leído del comprobante; ajústalo si no coincide.'
                      : 'No se pudo leer el monto del comprobante; ingrésalo manualmente.'}
                  </p>
                )}
              </div>
            </div>
          )}

          <div className="pv-modal__actions">
            <Button variant="secondary" onClick={onClose} disabled={submitting}>
              Cancelar
            </Button>
            <Button
              variant="primary"
              onClick={confirmar}
              disabled={submitting || cargandoCuotas || sinCuotas}
            >
              {submitting ? 'Confirmando…' : 'Confirmar pago'}
            </Button>
          </div>
        </Card>
      </div>
    </div>
  );
}
