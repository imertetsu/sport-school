import { useState } from 'react';
import { api, ApiError } from '@/api/client';
import type { PagoListItem } from '@/api/types';
import { Button, Card } from '@/components/ui';
import { formatDate, formatMoney } from '@/lib/format';
import './Pagos.css';

// Modal de anulación de un pago en efectivo (epic anular-pago, C6). Motivo
// OBLIGATORIO (no se envía vacío) + confirmación. Al confirmar llama anularPago;
// el backend revierte cuotas + crédito (reversa CON rastro). Maneja 404/409/422 con
// mensaje claro (sin crash). Tras éxito, el padre refresca la lista.
export function AnularPagoModal({
  pago,
  onClose,
  onAnulado,
}: {
  pago: PagoListItem;
  onClose: () => void;
  onAnulado: () => void;
}) {
  const [motivo, setMotivo] = useState('');
  const [motivoError, setMotivoError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function confirmar() {
    setFormError(null);
    setMotivoError(null);

    const motivoLimpio = motivo.trim();
    if (!motivoLimpio) {
      setMotivoError('Indica el motivo de la anulación.');
      return;
    }

    setSubmitting(true);
    try {
      await api.anularPago(pago.id, motivoLimpio);
      onAnulado();
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.isNotFound) {
          setFormError('Este pago ya no existe o no es visible para tu escuela.');
        } else if (err.isConflict) {
          setFormError(
            'No se puede anular: el saldo a favor que generó este pago ya fue usado en un pago posterior. Anula primero ese pago.',
          );
        } else if (err.isValidation) {
          setFormError(err.fieldErrors[0]?.msg ?? err.message);
        } else if (err.isForbidden) {
          setFormError('No tienes permiso para anular pagos.');
        } else {
          setFormError(err.message);
        }
      } else {
        setFormError('No se pudo anular el pago. Inténtalo de nuevo.');
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="pagos-modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label="Anular pago"
      onClick={(e) => {
        if (e.target === e.currentTarget && !submitting) onClose();
      }}
    >
      <div className="pagos-modal">
        <Card title="Anular pago">
          <p className="pagos-modal__lead">
            La cuota volverá a estar pendiente de cobro y se deshará cualquier saldo a favor
            que este pago haya generado. Queda registrado con el motivo (no se borra).
          </p>

          <dl className="pagos-modal__resumen">
            <div>
              <dt>Deportista</dt>
              <dd>{pago.deportista_nombre ?? '—'}</dd>
            </div>
            <div>
              <dt>Monto</dt>
              <dd className="tabular">{formatMoney(pago.monto)}</dd>
            </div>
            <div>
              <dt>Fecha</dt>
              <dd>{formatDate(pago.fecha)}</dd>
            </div>
            {pago.numero_recibo && (
              <div>
                <dt>N° recibo</dt>
                <dd className="tabular">{pago.numero_recibo}</dd>
              </div>
            )}
          </dl>

          {formError && (
            <div className="page-error" role="alert">
              {formError}
            </div>
          )}

          <div className="field">
            <label className="field__label" htmlFor="anular-motivo">
              Motivo de la anulación
              <span className="field__required" aria-hidden="true"> *</span>
            </label>
            <textarea
              id="anular-motivo"
              className="field__input pagos-modal__textarea"
              rows={3}
              value={motivo}
              onChange={(e) => {
                setMotivo(e.target.value);
                setMotivoError(null);
              }}
              aria-invalid={motivoError ? true : undefined}
              placeholder="Ej.: monto equivocado, deportista equivocado, doble registro…"
              autoFocus
            />
            {motivoError ? (
              <p className="field__error" role="alert">
                {motivoError}
              </p>
            ) : (
              <p className="field__hint">
                Este motivo queda guardado como rastro de la anulación.
              </p>
            )}
          </div>

          <div className="pagos-modal__actions">
            <Button variant="secondary" onClick={onClose} disabled={submitting}>
              Cancelar
            </Button>
            <Button variant="danger" onClick={confirmar} disabled={submitting}>
              {submitting ? 'Anulando…' : 'Anular pago'}
            </Button>
          </div>
        </Card>
      </div>
    </div>
  );
}
