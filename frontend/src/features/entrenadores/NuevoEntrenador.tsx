import { useEffect, useState, type FormEvent } from 'react';
import { api, ApiError } from '@/api/client';
import type {
  DisciplinaRef,
  EntrenadorCreate,
  EntrenadorOut,
  EntrenadorUpdate,
  Sucursal,
} from '@/api/types';
import { DocumentScanner, type CedulaFields } from '@/components/ocr/DocumentScanner';
import { Button, Card, Field, useToast } from '@/components/ui';

export interface NuevoEntrenadorProps {
  // Entrenador a editar; si se omite, el formulario crea uno nuevo.
  entrenador?: EntrenadorOut | null;
  onClose: () => void;
  // El padre refresca la lista con el entrenador creado/editado.
  onSaved: (entrenador: EntrenadorOut) => void;
}

// Formulario de alta/edición de entrenador (modal, solo ADMIN). Valida UX, pero
// el backend es la fuente de verdad: refleja sus 422 (validación) y 409 (email o
// CI ya en uso). En edición el email NO es editable. El CI (opcional) se puede
// prellenar con el escáner OCR de cédula; la imagen NO se sube ni se guarda.
export function NuevoEntrenador({ entrenador, onClose, onSaved }: NuevoEntrenadorProps) {
  const toast = useToast();
  const editar = Boolean(entrenador);

  const [nombres, setNombres] = useState(entrenador?.nombres ?? '');
  const [email, setEmail] = useState(entrenador?.email ?? '');
  const [ci, setCi] = useState(entrenador?.ci ?? '');
  const [password, setPassword] = useState('');
  const [especialidad, setEspecialidad] = useState(entrenador?.especialidad ?? '');
  const [telefono, setTelefono] = useState(entrenador?.telefono ?? '');
  // Disciplinas (M:N al catálogo global S2). Guardamos solo ids; al editar
  // precarga las refs del entrenador. El catálogo puebla los checkboxes.
  const [disciplinaIds, setDisciplinaIds] = useState<string[]>(
    () => entrenador?.disciplinas.map((d) => d.id) ?? [],
  );
  // Sucursales asignadas (M:N). Al editar precarga las actuales del entrenador.
  const [sucursalIds, setSucursalIds] = useState<string[]>(entrenador?.sucursal_ids ?? []);
  // La baja/reactivación se hace con un botón DIRECTO en la fila (Entrenadores.tsx),
  // no desde este modal (epic escuela-y-bajas, Fase 2). Por eso el update NO envía
  // `activo` (campo opcional => "no tocar"): editar datos no cambia el estado activo.

  // Catálogo de sucursales para el multiselect (reusa GET /sucursales).
  const [sucursales, setSucursales] = useState<Sucursal[]>([]);
  const [sucursalesError, setSucursalesError] = useState<string | null>(null);

  // Catálogo global de disciplinas (S2) para el multiselect.
  const [disciplinasCatalogo, setDisciplinasCatalogo] = useState<DisciplinaRef[]>([]);
  const [disciplinasError, setDisciplinasError] = useState<string | null>(null);

  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    api
      .sucursales(controller.signal)
      .then((data) => {
        if (active) setSucursales(data);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setSucursalesError('No se pudieron cargar las sucursales.');
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    api
      .disciplinasCatalogo(controller.signal)
      .then((data) => {
        if (active) setDisciplinasCatalogo(data);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setDisciplinasError('No se pudieron cargar las disciplinas.');
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, []);

  function toggleSucursal(id: string) {
    setSucursalIds((prev) =>
      prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id],
    );
  }

  function toggleDisciplina(id: string) {
    setDisciplinaIds((prev) =>
      prev.includes(id) ? prev.filter((d) => d !== id) : [...prev, id],
    );
  }

  // El OCR prellena CI y nombres (best-effort). Los campos siguen editables a mano;
  // la imagen no se guarda (lo garantiza DocumentScanner).
  function onScan(fields: CedulaFields) {
    if (fields.numeroCi) setCi(fields.numeroCi);
    if (fields.nombres) setNombres(fields.nombres);
  }

  // Validación de UX que refleja el 422 del backend (no lo reemplaza).
  function validate(): Record<string, string> {
    const errs: Record<string, string> = {};
    if (!nombres.trim()) errs.nombres = 'Requerido';
    if (!editar) {
      if (!email.trim()) errs.email = 'Requerido';
      if (!password) {
        errs.password = 'Requerido';
      } else if (password.length < 8) {
        errs.password = 'Mínimo 8 caracteres';
      }
    } else if (password && password.length < 8) {
      // En edición la contraseña es opcional; si viene, debe cumplir el mínimo.
      errs.password = 'Mínimo 8 caracteres';
    }
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

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);

    const errs = validate();
    setFieldErrors(errs);
    if (Object.keys(errs).length > 0) {
      setFormError('Revisa los campos marcados.');
      return;
    }

    setSubmitting(true);
    try {
      let saved: EntrenadorOut;
      if (entrenador) {
        const payload: EntrenadorUpdate = {
          nombres: nombres.trim(),
          ci: ci.trim() || null,
          especialidad: especialidad.trim() || null,
          // Lista = REEMPLAZA el set actual (el backend resuelve el delta).
          disciplina_ids: disciplinaIds,
          // `activo` NO se envía: la baja/reactivación vive en el botón de la fila.
          telefono: telefono.trim() || null,
          sucursal_ids: sucursalIds,
        };
        // Solo enviamos la contraseña si el admin escribió una nueva.
        if (password) payload.password = password;
        saved = await api.updateEntrenador(entrenador.id, payload);
      } else {
        const payload: EntrenadorCreate = {
          nombres: nombres.trim(),
          email: email.trim(),
          password,
          ci: ci.trim() || null,
          especialidad: especialidad.trim() || null,
          disciplina_ids: disciplinaIds,
          telefono: telefono.trim() || null,
          sucursal_ids: sucursalIds,
        };
        saved = await api.createEntrenador(payload);
      }
      toast.success(entrenador ? 'Cambios guardados' : 'Entrenador registrado');
      onSaved(saved);
    } catch (err) {
      let msg: string;
      if (err instanceof ApiError) {
        if (err.status === 409) {
          // El backend usa 409 para email duplicado y para CI duplicado (D2:
          // rechaza, no recupera). Distinguimos por el detail del backend.
          const detalle = (err.message ?? '').toLowerCase();
          const esCi = detalle.includes('ci');
          if (esCi) {
            setFieldErrors((prev) => ({
              ...prev,
              ci: 'Ya existe un entrenador con ese CI',
            }));
            msg =
              'Ya existe un entrenador con ese CI en tu organización. Edita el entrenador existente en lugar de crear otro.';
          } else {
            setFieldErrors((prev) => ({ ...prev, email: 'Ese email ya está en uso.' }));
            msg = 'El email ya está en uso por otra cuenta.';
          }
        } else if (err.isValidation) {
          applyApiErrors(err);
          msg = 'El servidor rechazó los datos. Revisa los campos marcados.';
        } else if (err.isForbidden) {
          msg = 'No tienes permiso para gestionar entrenadores.';
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

  return (
    <div
      className="entrenadores__modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label={editar ? 'Editar entrenador' : 'Nuevo entrenador'}
      onClick={(e) => {
        if (e.target === e.currentTarget && !submitting) onClose();
      }}
    >
      <div className="entrenadores__modal">
        <Card title={editar ? 'Editar entrenador' : 'Nuevo entrenador'}>
          {formError && (
            <div className="page-error" role="alert">
              {formError}
            </div>
          )}
          <form onSubmit={handleSubmit} noValidate className="entrenadores__modal-form">
            <Field
              label="Nombres"
              value={nombres}
              onChange={(e) => setNombres(e.target.value)}
              error={fieldErrors.nombres}
              placeholder="Carlos Pérez"
              required
            />

            <Field
              label="Email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              error={fieldErrors.email}
              placeholder="entrenador@escuela.com"
              required={!editar}
              disabled={editar}
              hint={editar ? 'El email no se puede cambiar.' : undefined}
            />

            <Field
              label="CI (cédula de identidad)"
              inputMode="numeric"
              value={ci}
              onChange={(e) => setCi(e.target.value)}
              error={fieldErrors.ci}
              placeholder="Opcional"
              hint="Único por organización. Opcional. Puedes escanear la cédula para prellenarlo."
            />

            <div className="entrenadores__scan">
              <DocumentScanner
                label="Escanea anverso y reverso para prellenar CI y nombres."
                onExtract={onScan}
              />
            </div>

            <Field
              label={editar ? 'Nueva contraseña' : 'Contraseña'}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              error={fieldErrors.password}
              placeholder={editar ? 'Dejar vacío para no cambiar' : 'Mínimo 8 caracteres'}
              autoComplete="new-password"
              required={!editar}
              hint={editar ? 'Déjalo vacío para no cambiar la contraseña.' : undefined}
            />

            <Field
              label="Especialidad"
              value={especialidad}
              onChange={(e) => setEspecialidad(e.target.value)}
              error={fieldErrors.especialidad}
              placeholder="Opcional"
            />

            <Field
              label="Teléfono (WhatsApp)"
              type="tel"
              inputMode="numeric"
              value={telefono}
              onChange={(e) => setTelefono(e.target.value)}
              error={fieldErrors.telefono}
              placeholder="59170000000"
              hint="Formato internacional sin «+» (código de país + número). Opcional."
            />

            <fieldset className="entrenadores__sucursales">
              <legend className="field__label">Disciplinas</legend>
              <p className="field__hint">
                Marca las disciplinas que entrena. Vienen del catálogo de la
                plataforma.
              </p>
              {disciplinasError && (
                <p className="field__error" role="alert">
                  {disciplinasError}
                </p>
              )}
              {disciplinasCatalogo.length === 0 && !disciplinasError ? (
                <p className="entrenador-cell__muted">
                  No hay disciplinas en el catálogo todavía.
                </p>
              ) : (
                <ul className="entrenadores__sucursales-list">
                  {disciplinasCatalogo.map((d) => (
                    <li key={d.id}>
                      <label className="entrenadores__toggle">
                        <input
                          type="checkbox"
                          checked={disciplinaIds.includes(d.id)}
                          onChange={() => toggleDisciplina(d.id)}
                        />
                        {d.nombre}
                      </label>
                    </li>
                  ))}
                </ul>
              )}
            </fieldset>

            <fieldset className="entrenadores__sucursales">
              <legend className="field__label">Sucursales asignadas</legend>
              <p className="field__hint">
                Marca las sucursales donde trabaja. Alimentan el resumen de
                deudores que se le envía por WhatsApp.
              </p>
              {sucursalesError && (
                <p className="field__error" role="alert">
                  {sucursalesError}
                </p>
              )}
              {sucursales.length === 0 && !sucursalesError ? (
                <p className="entrenador-cell__muted">
                  No hay sucursales registradas todavía.
                </p>
              ) : (
                <ul className="entrenadores__sucursales-list">
                  {sucursales.map((s) => (
                    <li key={s.id}>
                      <label className="entrenadores__toggle">
                        <input
                          type="checkbox"
                          checked={sucursalIds.includes(s.id)}
                          onChange={() => toggleSucursal(s.id)}
                        />
                        {s.nombre}
                      </label>
                    </li>
                  ))}
                </ul>
              )}
            </fieldset>

            <div className="entrenadores__modal-actions">
              <Button variant="secondary" onClick={onClose} disabled={submitting}>
                Cancelar
              </Button>
              <Button type="submit" variant="primary" disabled={submitting}>
                {submitting
                  ? 'Guardando…'
                  : editar
                    ? 'Guardar cambios'
                    : 'Crear entrenador'}
              </Button>
            </div>
          </form>
        </Card>
      </div>
    </div>
  );
}
