import { useEffect, useState, type FormEvent } from 'react';
import { api, ApiError } from '@/api/client';
import type {
  AlcanceAviso,
  AvisoCreate,
  AvisoCreated,
  AvisoOut,
  Categoria,
  PreviewNotificacionOut,
  Sucursal,
} from '@/api/types';
import { Button, Card, Field, SelectField, useToast } from '@/components/ui';

export interface NuevoAvisoProps {
  sucursales: Sucursal[];
  // Aviso a editar; si se omite, el formulario crea uno nuevo.
  aviso?: AvisoOut | null;
  onClose: () => void;
  // El padre refresca el feed con el aviso creado/editado.
  onSaved: (aviso: AvisoCreated) => void;
}

const ALCANCE_OPCIONES: { value: AlcanceAviso; label: string }[] = [
  { value: 'ORG', label: 'Toda la escuela' },
  { value: 'SUCURSAL', label: 'Una sucursal' },
  { value: 'CATEGORIA', label: 'Una categoría' },
];

// Formulario de alta/edición de aviso (modal, solo ADMIN). Valida UX, pero el
// backend es la fuente de verdad: refleja sus 422 (incl. la invariante de alcance).
export function NuevoAviso({ sucursales, aviso, onClose, onSaved }: NuevoAvisoProps) {
  const toast = useToast();
  const editar = Boolean(aviso);

  const [titulo, setTitulo] = useState(aviso?.titulo ?? '');
  const [cuerpo, setCuerpo] = useState(aviso?.cuerpo ?? '');
  const [alcance, setAlcance] = useState<AlcanceAviso>(aviso?.alcance ?? 'ORG');
  const [sucursalId, setSucursalId] = useState(aviso?.sucursal?.id ?? '');
  const [categoriaId, setCategoriaId] = useState(aviso?.categoria?.id ?? '');
  const [vigenteHasta, setVigenteHasta] = useState(aviso?.vigente_hasta ?? '');

  // Categorías para el selector de alcance=CATEGORIA (scoped por rol en backend).
  const [categorias, setCategorias] = useState<Categoria[]>([]);

  // Notificación opt-in por WhatsApp (solo en ALTA). Desmarcados por defecto:
  // sin flag marcado, el alta se comporta exactamente como hoy (sin preview).
  const [notificarEntrenadores, setNotificarEntrenadores] = useState(false);
  const [notificarTutores, setNotificarTutores] = useState(false);

  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  // Paso de confirmación con conteo: cuando hay algún grupo marcado, antes de
  // crear se pide el preview y se muestra "se enviará a N personas…". Mientras
  // pending != null, el modal muestra ese paso y espera confirmar/cancelar.
  const [pending, setPending] = useState<AvisoCreate | null>(null);
  const [preview, setPreview] = useState<PreviewNotificacionOut | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  // Carga las categorías la primera vez que se elige el alcance CATEGORIA.
  useEffect(() => {
    if (alcance !== 'CATEGORIA' || categorias.length > 0) return;
    const controller = new AbortController();
    let active = true;
    api
      .categorias(undefined, controller.signal)
      .then((data) => {
        if (active) setCategorias(data);
      })
      .catch((err) => {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        // No bloquea el formulario; el campo quedará vacío y el backend valida.
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [alcance, categorias.length]);

  // Validación de UX que refleja la invariante del backend (no la reemplaza).
  function validate(): Record<string, string> {
    const errs: Record<string, string> = {};
    if (!titulo.trim()) errs.titulo = 'Requerido';
    if (!cuerpo.trim()) errs.cuerpo = 'Requerido';
    if (alcance === 'SUCURSAL' && !sucursalId) errs.sucursal_id = 'Elige una sucursal';
    if (alcance === 'CATEGORIA' && !categoriaId) errs.categoria_id = 'Elige una categoría';
    return errs;
  }

  // Mapea errores 422 (loc) del backend a los campos del formulario.
  function applyApiErrors(err: ApiError) {
    const mapped: Record<string, string> = {};
    for (const fe of err.fieldErrors) {
      const loc = fe.loc.filter((p) => p !== 'body');
      const key = typeof loc[0] === 'string' ? loc[0] : loc.join('.');
      if (key) mapped[key] = fe.msg;
    }
    setFieldErrors(mapped);
  }

  // Crea (o edita) el aviso y avisa al padre. Mapea 422/403 a la UI.
  async function persistir(payload: AvisoCreate) {
    setSubmitting(true);
    try {
      const saved = aviso
        ? await api.actualizarAviso(aviso.id, payload)
        : await api.crearAviso(payload);
      toast.success(aviso ? 'Aviso actualizado' : 'Aviso publicado');
      onSaved(saved);
    } catch (err) {
      // Si veníamos del paso de confirmación, vuelve al formulario para mostrar
      // el error (la invariante o el 403 se reflejan en los campos/banner).
      setPending(null);
      let msg: string;
      if (err instanceof ApiError) {
        if (err.isValidation) {
          applyApiErrors(err);
          msg = 'El servidor rechazó los datos. Revisa los campos marcados.';
        } else if (err.isForbidden) {
          msg = 'No tienes permiso para publicar avisos.';
        } else {
          msg = err.message;
        }
      } else {
        msg = 'No se pudo conectar con el servidor.';
      }
      setFormError(msg);
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    const errs = validate();
    setFieldErrors(errs);
    if (Object.keys(errs).length > 0) {
      setFormError('Revisa los campos marcados.');
      return;
    }

    // Respeta la invariante C1: solo se envía el id que corresponde al alcance.
    // Las flags de notificación SOLO aplican al alta (nunca al editar).
    const notificar = !editar && (notificarEntrenadores || notificarTutores);
    const payload: AvisoCreate = {
      titulo: titulo.trim(),
      cuerpo: cuerpo.trim(),
      alcance,
      sucursal_id: alcance === 'SUCURSAL' ? sucursalId : null,
      categoria_id: alcance === 'CATEGORIA' ? categoriaId : null,
      vigente_hasta: vigenteHasta || null,
      ...(editar
        ? {}
        : {
            notificar_entrenadores: notificarEntrenadores,
            notificar_tutores: notificarTutores,
          }),
    };

    // Sin notificación: alta normal, sin preview ni confirmación (como hoy).
    if (!notificar) {
      await persistir(payload);
      return;
    }

    // Con algún grupo marcado: primero el conteo (preview), luego confirmación.
    setPreview(null);
    setPreviewError(null);
    setPreviewLoading(true);
    setPending(payload);
    try {
      const counts = await api.previewNotificacionAviso({
        alcance,
        sucursal_id: payload.sucursal_id ?? null,
        categoria_id: payload.categoria_id ?? null,
        notificar_entrenadores: notificarEntrenadores,
        notificar_tutores: notificarTutores,
      });
      setPreview(counts);
    } catch (err) {
      // El conteo es informativo: si falla, NO bloqueamos el alta. Mostramos un
      // aviso y dejamos confirmar igual (o reintentar el preview).
      if (err instanceof ApiError && err.isForbidden) {
        setPreviewError('No tienes permiso para enviar notificaciones.');
      } else if (err instanceof ApiError) {
        setPreviewError(err.message);
      } else {
        setPreviewError('No se pudo calcular el número de destinatarios.');
      }
    } finally {
      setPreviewLoading(false);
    }
  }

  // Reintenta el preview desde el paso de confirmación (cuando falló el conteo).
  async function reintentarPreview() {
    setPreviewError(null);
    setPreviewLoading(true);
    try {
      const counts = await api.previewNotificacionAviso({
        alcance,
        sucursal_id: alcance === 'SUCURSAL' ? sucursalId : null,
        categoria_id: alcance === 'CATEGORIA' ? categoriaId : null,
        notificar_entrenadores: notificarEntrenadores,
        notificar_tutores: notificarTutores,
      });
      setPreview(counts);
    } catch (err) {
      if (err instanceof ApiError && err.isForbidden) {
        setPreviewError('No tienes permiso para enviar notificaciones.');
      } else if (err instanceof ApiError) {
        setPreviewError(err.message);
      } else {
        setPreviewError('No se pudo calcular el número de destinatarios.');
      }
    } finally {
      setPreviewLoading(false);
    }
  }

  return (
    <div
      className="avisos__modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label={editar ? 'Editar aviso' : 'Nuevo aviso'}
      onClick={(e) => {
        if (e.target === e.currentTarget && !submitting) onClose();
      }}
    >
      <div className="avisos__modal">
        <Card title={editar ? 'Editar aviso' : 'Nuevo aviso'}>
          {formError && (
            <div className="page-error" role="alert">
              {formError}
            </div>
          )}

          {/* Paso de confirmación con conteo (solo alta con algún grupo marcado). */}
          {pending ? (
            <div
              className="avisos__confirm-envio"
              role="alertdialog"
              aria-label="Confirmar envío de notificación"
            >
              {previewLoading && (
                <p className="avisos__confirm-texto">Calculando destinatarios…</p>
              )}

              {!previewLoading && previewError && (
                <>
                  <p className="page-error" role="alert">
                    {previewError}
                  </p>
                  <p className="avisos__confirm-texto">
                    No pudimos calcular cuántas personas recibirán el WhatsApp.
                    Puedes reintentar el conteo o publicar de todos modos (se
                    enviará a los destinatarios del alcance elegido).
                  </p>
                </>
              )}

              {!previewLoading && !previewError && preview && (
                <p className="avisos__confirm-texto">
                  {preview.total === 0 ? (
                    <>No hay destinatarios con teléfono para este aviso. </>
                  ) : (
                    <>
                      Se enviará un WhatsApp a <strong>{preview.total}</strong>{' '}
                      {preview.total === 1 ? 'persona' : 'personas'} (
                      {preview.entrenadores}{' '}
                      {preview.entrenadores === 1 ? 'entrenador' : 'entrenadores'},{' '}
                      {preview.tutores}{' '}
                      {preview.tutores === 1 ? 'tutor' : 'tutores'}).{' '}
                    </>
                  )}
                  {preview.sin_telefono > 0 && (
                    <>
                      {preview.sin_telefono}{' '}
                      {preview.sin_telefono === 1
                        ? 'persona sin teléfono se omitirá'
                        : 'personas sin teléfono se omitirán'}
                      .{' '}
                    </>
                  )}
                  ¿Confirmar?
                </p>
              )}

              <div className="avisos__modal-actions">
                <Button
                  variant="secondary"
                  onClick={() => {
                    setPending(null);
                    setPreview(null);
                    setPreviewError(null);
                  }}
                  disabled={submitting}
                >
                  Cancelar
                </Button>
                {!previewLoading && previewError && (
                  <Button
                    variant="ghost"
                    onClick={reintentarPreview}
                    disabled={submitting}
                  >
                    Reintentar conteo
                  </Button>
                )}
                <Button
                  variant="primary"
                  onClick={() => persistir(pending)}
                  disabled={submitting || previewLoading}
                >
                  {submitting ? 'Publicando…' : 'Confirmar y publicar'}
                </Button>
              </div>
            </div>
          ) : (
          <form onSubmit={handleSubmit} noValidate className="avisos__modal-form">
            <Field
              label="Título"
              value={titulo}
              onChange={(e) => setTitulo(e.target.value)}
              error={fieldErrors.titulo}
              placeholder="Suspensión de entrenamientos"
              required
            />
            <div className="field">
              <label className="field__label" htmlFor="aviso-cuerpo">
                Cuerpo
                <span className="field__required" aria-hidden="true"> *</span>
              </label>
              <textarea
                id="aviso-cuerpo"
                className="field__input avisos__textarea"
                value={cuerpo}
                onChange={(e) => setCuerpo(e.target.value)}
                aria-invalid={fieldErrors.cuerpo ? true : undefined}
                rows={4}
                placeholder="Por mal clima, los entrenamientos de hoy se cancelan."
                required
              />
              {fieldErrors.cuerpo && (
                <p className="field__error" role="alert">
                  {fieldErrors.cuerpo}
                </p>
              )}
            </div>

            <SelectField
              label="Alcance"
              value={alcance}
              onChange={(e) => setAlcance(e.target.value as AlcanceAviso)}
              error={fieldErrors.alcance}
              hint="Define quién verá el aviso."
            >
              {ALCANCE_OPCIONES.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </SelectField>

            {alcance === 'SUCURSAL' && (
              <SelectField
                label="Sucursal"
                value={sucursalId}
                onChange={(e) => setSucursalId(e.target.value)}
                error={fieldErrors.sucursal_id}
                required
              >
                <option value="">Selecciona…</option>
                {sucursales.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.nombre}
                  </option>
                ))}
              </SelectField>
            )}

            {alcance === 'CATEGORIA' && (
              <SelectField
                label="Categoría"
                value={categoriaId}
                onChange={(e) => setCategoriaId(e.target.value)}
                error={fieldErrors.categoria_id}
                required
              >
                <option value="">Selecciona…</option>
                {categorias.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.nombre}
                  </option>
                ))}
              </SelectField>
            )}

            <Field
              label="Vence el"
              type="date"
              value={vigenteHasta}
              onChange={(e) => setVigenteHasta(e.target.value)}
              error={fieldErrors.vigente_hasta}
              hint="Opcional: déjalo vacío para un aviso sin caducidad."
            />

            {/* Notificación opt-in por WhatsApp: SOLO en el alta (editar no
                notifica). Desmarcados por defecto (RNF-07: el envío tiene
                costo). El conteo y la confirmación van al pulsar "Publicar". */}
            {!editar && (
              <fieldset className="avisos__notificar">
                <legend className="avisos__notificar-legend">
                  Notificar por WhatsApp
                </legend>
                <p className="avisos__notificar-hint">
                  Opcional: avisa a quienes alcance este aviso. El envío tiene
                  costo; verás el número de destinatarios antes de confirmar.
                </p>
                <label className="avisos__notificar-opcion">
                  <input
                    type="checkbox"
                    checked={notificarEntrenadores}
                    onChange={(e) => setNotificarEntrenadores(e.target.checked)}
                  />
                  Entrenadores
                </label>
                <label className="avisos__notificar-opcion">
                  <input
                    type="checkbox"
                    checked={notificarTutores}
                    onChange={(e) => setNotificarTutores(e.target.checked)}
                  />
                  Tutores
                </label>
              </fieldset>
            )}

            <div className="avisos__modal-actions">
              <Button variant="secondary" onClick={onClose} disabled={submitting}>
                Cancelar
              </Button>
              <Button type="submit" variant="primary" disabled={submitting}>
                {submitting ? 'Guardando…' : editar ? 'Guardar cambios' : 'Publicar aviso'}
              </Button>
            </div>
          </form>
          )}
        </Card>
      </div>
    </div>
  );
}
