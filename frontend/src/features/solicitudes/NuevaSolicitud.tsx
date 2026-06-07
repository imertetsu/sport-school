import { useEffect, useState, type FormEvent } from 'react';
import { api, ApiError } from '@/api/client';
import type {
  Categoria,
  SolicitudCreate,
  SolicitudOut,
  Sucursal,
} from '@/api/types';
import { Button, Card, Field, SelectField } from '@/components/ui';
import { nivelLabel } from '@/lib/format';

export interface NuevaSolicitudProps {
  // Sucursales del alcance del usuario (entrenador: solo las suyas, de useSucursales).
  sucursales: Sucursal[];
  onClose: () => void;
  // El padre refresca la cola con la solicitud creada.
  onSaved: (solicitud: SolicitudOut) => void;
}

// Versión de términos del consentimiento que la UI envía (el texto del backend manda).
const CONSENT_VERSION = 'v1';

// Formulario de captura de solicitud (modal, ADMIN o ENTRENADOR). Reusa la
// estructura del alta de deportista (datos deportista + ficha médica + tutor +
// consentimiento). El backend es la fuente de verdad: refleja sus 422/403.
export function NuevaSolicitud({ sucursales, onClose, onSaved }: NuevaSolicitudProps) {
  // Datos del deportista
  const [apPaterno, setApPaterno] = useState('');
  const [apMaterno, setApMaterno] = useState('');
  const [nombres, setNombres] = useState('');
  const [ci, setCi] = useState('');
  const [fechaNac, setFechaNac] = useState('');
  const [disciplina, setDisciplina] = useState('');
  const [contactoEmergencia, setContactoEmergencia] = useState('');

  // Ficha médica (opcional)
  const [tipoSangre, setTipoSangre] = useState('');
  const [alergias, setAlergias] = useState('');
  const [condiciones, setCondiciones] = useState('');

  // Tutor (uno; el admin completa responsable_pago al aprobar)
  const [tutorNombres, setTutorNombres] = useState('');
  const [tutorTelefono, setTutorTelefono] = useState('');
  const [tutorCi, setTutorCi] = useState('');
  const [parentesco, setParentesco] = useState('');

  // Consentimiento obligatorio
  const [consentimiento, setConsentimiento] = useState(false);

  // Sugerencias (opcionales): sucursal del alcance + categoría de esa sucursal
  const [sucursalId, setSucursalId] = useState('');
  const [categoriaId, setCategoriaId] = useState('');
  const [categorias, setCategorias] = useState<Categoria[]>([]);

  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  // Carga las categorías de la sucursal sugerida (scoped por rol en el backend).
  useEffect(() => {
    if (!sucursalId) {
      setCategorias([]);
      setCategoriaId('');
      return;
    }
    const controller = new AbortController();
    let active = true;
    api
      .categorias(sucursalId, controller.signal)
      .then((data) => {
        if (active) setCategorias(data);
      })
      .catch((err) => {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        if (active) setCategorias([]);
      });
    setCategoriaId('');
    return () => {
      active = false;
      controller.abort();
    };
  }, [sucursalId]);

  // Validación de UX que refleja el 422 del backend (no reemplaza la regla dura).
  function validate(): Record<string, string> {
    const errs: Record<string, string> = {};
    if (!apPaterno.trim()) errs.ap_paterno = 'Requerido';
    if (!nombres.trim()) errs.nombres = 'Requerido';
    // CI del deportista: OBLIGATORIO. Bloquea el submit si está vacío.
    if (!ci.trim()) errs.ci = 'El CI del deportista es obligatorio.';
    if (!fechaNac) errs.fecha_nac = 'Requerido';
    if (!disciplina.trim()) errs.disciplina = 'Requerido';
    if (!tutorNombres.trim()) errs.tutor_nombres = 'Requerido';
    if (!tutorTelefono.trim()) errs.tutor_telefono = 'Requerido';
    if (!parentesco.trim()) errs.parentesco = 'Requerido';
    if (!consentimiento) {
      errs.consentimiento = 'El consentimiento del tutor es obligatorio.';
    }
    return errs;
  }

  // Mapea errores 422 (loc) del backend a los campos del formulario.
  function applyApiErrors(err: ApiError) {
    const mapped: Record<string, string> = {};
    for (const fe of err.fieldErrors) {
      const loc = fe.loc.filter((p) => p !== 'body');
      if (loc.includes('consentimiento')) {
        mapped.consentimiento = fe.msg;
      } else if (loc.includes('tutor')) {
        // tutor.<campo> -> tutor_<campo> para casar con los inputs.
        const sub = loc[loc.indexOf('tutor') + 1];
        mapped[typeof sub === 'string' ? `tutor_${sub}` : 'tutor_nombres'] = fe.msg;
      } else if (typeof loc[0] === 'string') {
        mapped[loc[0]] = fe.msg;
      } else {
        mapped[loc.join('.')] = fe.msg;
      }
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

    // Solo enviamos ficha_medica si el capturador llenó algún campo.
    const fichaLlena =
      tipoSangre.trim() || alergias.trim() || condiciones.trim();

    const payload: SolicitudCreate = {
      ap_paterno: apPaterno.trim(),
      ap_materno: apMaterno.trim(),
      nombres: nombres.trim(),
      ci: ci.trim(),
      fecha_nac: fechaNac,
      disciplina: disciplina.trim(),
      contacto_emergencia: contactoEmergencia.trim() || null,
      ficha_medica: fichaLlena
        ? {
            tipo_sangre: tipoSangre.trim(),
            alergias: alergias.trim(),
            condiciones: condiciones.trim(),
          }
        : null,
      tutor: {
        nombres: tutorNombres.trim(),
        telefono: tutorTelefono.trim(),
        ci: tutorCi.trim() || null,
        parentesco: parentesco.trim(),
      },
      consentimiento: { aceptado: true, version_terminos: CONSENT_VERSION },
      sucursal_sugerida_id: sucursalId || null,
      categoria_sugerida_id: categoriaId || null,
    };

    setSubmitting(true);
    try {
      const saved = await api.crearSolicitud(payload);
      onSaved(saved);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.isValidation) {
          applyApiErrors(err);
          setFormError('El servidor rechazó los datos. Revisa los campos marcados.');
        } else if (err.isForbidden) {
          setFormError(
            'No puedes sugerir esa sucursal: está fuera de tu alcance.',
          );
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
      className="solicitudes__modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label="Nueva solicitud"
      onClick={(e) => {
        if (e.target === e.currentTarget && !submitting) onClose();
      }}
    >
      <div className="solicitudes__modal">
        <Card title="Nueva solicitud">
          {formError && (
            <div className="page-error" role="alert">
              {formError}
            </div>
          )}
          <form onSubmit={handleSubmit} noValidate className="solicitudes__modal-form">
            <fieldset className="solicitudes__fieldset">
              <legend className="solicitudes__legend">Datos del deportista</legend>
              <div className="form-grid">
                <Field
                  label="Apellido paterno"
                  value={apPaterno}
                  onChange={(e) => setApPaterno(e.target.value)}
                  error={fieldErrors.ap_paterno}
                  required
                />
                <Field
                  label="Apellido materno"
                  value={apMaterno}
                  onChange={(e) => setApMaterno(e.target.value)}
                  error={fieldErrors.ap_materno}
                />
                <Field
                  label="Nombres"
                  value={nombres}
                  onChange={(e) => setNombres(e.target.value)}
                  error={fieldErrors.nombres}
                  required
                />
                <Field
                  label="CI del deportista"
                  value={ci}
                  onChange={(e) => setCi(e.target.value)}
                  error={fieldErrors.ci}
                  placeholder="9123456 LP"
                  hint="Obligatorio."
                  required
                />
                <Field
                  label="Fecha de nacimiento"
                  type="date"
                  value={fechaNac}
                  onChange={(e) => setFechaNac(e.target.value)}
                  error={fieldErrors.fecha_nac}
                  required
                />
                <Field
                  label="Disciplina"
                  value={disciplina}
                  onChange={(e) => setDisciplina(e.target.value)}
                  error={fieldErrors.disciplina}
                  placeholder="Fútbol"
                  required
                />
              </div>
              <div className="form-grid form-grid--single">
                <Field
                  label="Contacto de emergencia"
                  value={contactoEmergencia}
                  onChange={(e) => setContactoEmergencia(e.target.value)}
                  placeholder="Nombre y teléfono"
                />
              </div>
            </fieldset>

            <fieldset className="solicitudes__fieldset">
              <legend className="solicitudes__legend">Ficha médica (opcional)</legend>
              <div className="form-grid">
                <Field
                  label="Tipo de sangre"
                  value={tipoSangre}
                  onChange={(e) => setTipoSangre(e.target.value)}
                  placeholder="O+"
                />
                <Field
                  label="Alergias"
                  value={alergias}
                  onChange={(e) => setAlergias(e.target.value)}
                  placeholder="Ninguna"
                />
              </div>
              <div className="form-grid form-grid--single">
                <Field
                  label="Condiciones"
                  value={condiciones}
                  onChange={(e) => setCondiciones(e.target.value)}
                  placeholder="Asma, etc."
                />
              </div>
            </fieldset>

            <fieldset className="solicitudes__fieldset">
              <legend className="solicitudes__legend">Datos del tutor</legend>
              <div className="form-grid">
                <Field
                  label="Nombres"
                  value={tutorNombres}
                  onChange={(e) => setTutorNombres(e.target.value)}
                  error={fieldErrors.tutor_nombres}
                  required
                />
                <Field
                  label="Teléfono"
                  value={tutorTelefono}
                  onChange={(e) => setTutorTelefono(e.target.value)}
                  error={fieldErrors.tutor_telefono}
                  required
                />
                <Field
                  label="CI"
                  value={tutorCi}
                  onChange={(e) => setTutorCi(e.target.value)}
                  hint="Opcional"
                />
                <Field
                  label="Parentesco"
                  value={parentesco}
                  onChange={(e) => setParentesco(e.target.value)}
                  error={fieldErrors.parentesco}
                  placeholder="Madre / Padre / …"
                  required
                />
              </div>
            </fieldset>

            <fieldset className="solicitudes__fieldset">
              <legend className="solicitudes__legend">Sugerencias (opcional)</legend>
              <div className="form-grid">
                <SelectField
                  label="Sucursal sugerida"
                  value={sucursalId}
                  onChange={(e) => setSucursalId(e.target.value)}
                  error={fieldErrors.sucursal_sugerida_id}
                  hint="El admin confirma la sucursal al aprobar."
                >
                  <option value="">Sin sugerencia</option>
                  {sucursales.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.nombre}
                    </option>
                  ))}
                </SelectField>
                <SelectField
                  label="Categoría sugerida"
                  value={categoriaId}
                  onChange={(e) => setCategoriaId(e.target.value)}
                  hint={!sucursalId ? 'Elige primero una sucursal' : undefined}
                  disabled={!sucursalId}
                >
                  <option value="">Sin sugerencia</option>
                  {categorias.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.nombre} {nivelLabel(c.nivel)}
                    </option>
                  ))}
                </SelectField>
              </div>
            </fieldset>

            <label
              className={`checkbox-row checkbox-row--lg${
                fieldErrors.consentimiento ? ' checkbox-row--error' : ''
              }`}
            >
              <input
                type="checkbox"
                checked={consentimiento}
                onChange={(e) => setConsentimiento(e.target.checked)}
                required
              />
              <span>
                El tutor acepta los términos y otorga su consentimiento para la
                inscripción del deportista. <strong>(Obligatorio)</strong>
              </span>
            </label>
            {fieldErrors.consentimiento && (
              <p className="field__error" role="alert">
                {fieldErrors.consentimiento}
              </p>
            )}

            <div className="solicitudes__modal-actions">
              <Button variant="secondary" onClick={onClose} disabled={submitting}>
                Cancelar
              </Button>
              <Button type="submit" variant="primary" disabled={submitting}>
                {submitting ? 'Enviando…' : 'Enviar solicitud'}
              </Button>
            </div>
          </form>
        </Card>
      </div>
    </div>
  );
}
