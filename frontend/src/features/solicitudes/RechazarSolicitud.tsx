import { useState, type FormEvent } from 'react';
import { api, ApiError } from '@/api/client';
import type { SolicitudOut } from '@/api/types';
import { Button, Card } from '@/components/ui';

export interface RechazarSolicitudProps {
  solicitud: SolicitudOut;
  onClose: () => void;
  // El padre refresca la cola con la solicitud rechazada.
  onRejected: (solicitud: SolicitudOut) => void;
}

// Modal de rechazo (solo ADMIN): exige un motivo. 409 si la solicitud ya fue resuelta.
export function RechazarSolicitud({ solicitud, onClose, onRejected }: RechazarSolicitudProps) {
  const [motivo, setMotivo] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [motivoError, setMotivoError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    setMotivoError(null);
    if (!motivo.trim()) {
      setMotivoError('Indica el motivo del rechazo.');
      return;
    }

    setSubmitting(true);
    try {
      const rechazada = await api.rechazarSolicitud(solicitud.id, motivo.trim());
      onRejected(rechazada);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.isValidation) {
          setMotivoError(err.fieldErrors[0]?.msg ?? 'Motivo inválido.');
        } else if (err.isForbidden) {
          setFormError('No tienes permiso para rechazar solicitudes.');
        } else if (err.status === 409) {
          setFormError('Esta solicitud ya fue resuelta.');
        } else {
          setFormError(err.message);
        }
      } else {
        setFormError('No se pudo conectar con el servidor.');
      }
    } finally {
      setSubmitting(false);
    }
  }

  const nombreCompleto = `${solicitud.nombres} ${solicitud.ap_paterno}`.trim();

  return (
    <div
      className="solicitudes__modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label="Rechazar solicitud"
      onClick={(e) => {
        if (e.target === e.currentTarget && !submitting) onClose();
      }}
    >
      <div className="solicitudes__modal solicitudes__modal--sm">
        <Card title="Rechazar solicitud">
          <p className="solicitudes__modal-lead">
            La solicitud de <strong>{nombreCompleto}</strong> quedará rechazada. No se
            creará ningún alumno.
          </p>
          {formError && (
            <div className="page-error" role="alert">
              {formError}
            </div>
          )}
          <form onSubmit={handleSubmit} noValidate className="solicitudes__modal-form">
            <div className="field">
              <label className="field__label" htmlFor="rechazo-motivo">
                Motivo
                <span className="field__required" aria-hidden="true"> *</span>
              </label>
              <textarea
                id="rechazo-motivo"
                className="field__input solicitudes__textarea"
                value={motivo}
                onChange={(e) => setMotivo(e.target.value)}
                aria-invalid={motivoError ? true : undefined}
                rows={3}
                placeholder="Datos incompletos / duplicado / …"
                required
              />
              {motivoError && (
                <p className="field__error" role="alert">
                  {motivoError}
                </p>
              )}
            </div>

            <div className="solicitudes__modal-actions">
              <Button variant="secondary" onClick={onClose} disabled={submitting}>
                Cancelar
              </Button>
              <Button type="submit" variant="danger" disabled={submitting}>
                {submitting ? 'Rechazando…' : 'Rechazar solicitud'}
              </Button>
            </div>
          </form>
        </Card>
      </div>
    </div>
  );
}
