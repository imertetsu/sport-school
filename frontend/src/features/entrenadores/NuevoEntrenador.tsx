import { useEffect, useState, type FormEvent, type KeyboardEvent } from 'react';
import { api, ApiError } from '@/api/client';
import type {
  EntrenadorCreate,
  EntrenadorOut,
  EntrenadorUpdate,
  Sucursal,
} from '@/api/types';
import { Button, Card, Field } from '@/components/ui';

export interface NuevoEntrenadorProps {
  // Entrenador a editar; si se omite, el formulario crea uno nuevo.
  entrenador?: EntrenadorOut | null;
  onClose: () => void;
  // El padre refresca la lista con el entrenador creado/editado.
  onSaved: (entrenador: EntrenadorOut) => void;
}

// Formulario de alta/edición de entrenador (modal, solo ADMIN). Valida UX, pero
// el backend es la fuente de verdad: refleja sus 422 (validación) y 409 (email
// ya en uso, en esta org o en otra). En edición el email NO es editable.
export function NuevoEntrenador({ entrenador, onClose, onSaved }: NuevoEntrenadorProps) {
  const editar = Boolean(entrenador);

  const [nombres, setNombres] = useState(entrenador?.nombres ?? '');
  const [email, setEmail] = useState(entrenador?.email ?? '');
  const [password, setPassword] = useState('');
  const [especialidad, setEspecialidad] = useState(entrenador?.especialidad ?? '');
  const [telefono, setTelefono] = useState(entrenador?.telefono ?? '');
  const [disciplinas, setDisciplinas] = useState<string[]>(entrenador?.disciplinas ?? []);
  const [disciplinaInput, setDisciplinaInput] = useState('');
  // Sucursales asignadas (M:N). Al editar precarga las actuales del entrenador.
  const [sucursalIds, setSucursalIds] = useState<string[]>(entrenador?.sucursal_ids ?? []);
  // Solo relevante en edición: toggle de baja/reactivación.
  const [activo, setActivo] = useState(entrenador?.activo ?? true);

  // Catálogo de sucursales para el multiselect (reusa GET /sucursales).
  const [sucursales, setSucursales] = useState<Sucursal[]>([]);
  const [sucursalesError, setSucursalesError] = useState<string | null>(null);

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

  function toggleSucursal(id: string) {
    setSucursalIds((prev) =>
      prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id],
    );
  }

  // Añade el texto actual como una disciplina (sin duplicados, recortado).
  function addDisciplina() {
    const value = disciplinaInput.trim();
    if (!value) return;
    setDisciplinas((prev) => (prev.includes(value) ? prev : [...prev, value]));
    setDisciplinaInput('');
  }

  function removeDisciplina(value: string) {
    setDisciplinas((prev) => prev.filter((d) => d !== value));
  }

  // Enter (o coma) añade la disciplina sin enviar el formulario.
  function onDisciplinaKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      addDisciplina();
    }
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
    // Si quedó texto sin añadir en el input, lo incorporamos antes de validar.
    const pendiente = disciplinaInput.trim();
    const discFinal =
      pendiente && !disciplinas.includes(pendiente)
        ? [...disciplinas, pendiente]
        : disciplinas;

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
          especialidad: especialidad.trim() || null,
          disciplinas: discFinal,
          activo,
          telefono: telefono.trim() || null,
          // Lista = REEMPLAZA el set actual (el backend resuelve el delta).
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
          especialidad: especialidad.trim() || null,
          disciplinas: discFinal,
          telefono: telefono.trim() || null,
          sucursal_ids: sucursalIds,
        };
        saved = await api.createEntrenador(payload);
      }
      onSaved(saved);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409) {
          setFieldErrors((prev) => ({ ...prev, email: 'Ese email ya está en uso.' }));
          setFormError('El email ya está en uso por otra cuenta.');
        } else if (err.isValidation) {
          applyApiErrors(err);
          setFormError('El servidor rechazó los datos. Revisa los campos marcados.');
        } else if (err.isForbidden) {
          setFormError('No tienes permiso para gestionar entrenadores.');
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

            <div className="field">
              <label className="field__label" htmlFor="entrenador-disciplina">
                Disciplinas
              </label>
              <div className="tag-input">
                <input
                  id="entrenador-disciplina"
                  className="field__input"
                  value={disciplinaInput}
                  onChange={(e) => setDisciplinaInput(e.target.value)}
                  onKeyDown={onDisciplinaKeyDown}
                  placeholder="Fútbol, Natación…"
                />
                <Button
                  variant="secondary"
                  className="tag-input__add"
                  onClick={addDisciplina}
                  disabled={!disciplinaInput.trim()}
                >
                  Añadir
                </Button>
              </div>
              <p className="field__hint">Escribe una disciplina y pulsa Enter o «Añadir».</p>
              {disciplinas.length > 0 && (
                <ul className="tag-list" aria-label="Disciplinas añadidas">
                  {disciplinas.map((d) => (
                    <li key={d} className="tag-chip">
                      {d}
                      <button
                        type="button"
                        className="tag-chip__remove"
                        aria-label={`Quitar ${d}`}
                        onClick={() => removeDisciplina(d)}
                      >
                        ×
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>

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

            {editar && (
              <label className="entrenadores__toggle">
                <input
                  type="checkbox"
                  checked={activo}
                  onChange={(e) => setActivo(e.target.checked)}
                />
                {activo ? 'Activo (puede iniciar sesión)' : 'Inactivo (dado de baja)'}
              </label>
            )}

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
