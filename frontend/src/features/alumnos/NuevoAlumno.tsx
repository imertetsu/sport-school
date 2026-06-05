import { useEffect, useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api, ApiError } from '@/api/client';
import type {
  AlumnoCreate,
  Categoria,
  Sucursal,
  TutorCreate,
} from '@/api/types';
import { Button, Card, Field, SelectField } from '@/components/ui';
import { nivelLabel } from '@/lib/format';
import './NuevoAlumno.css';

const EMPTY_TUTOR: TutorCreate = {
  nombres: '',
  telefono: '',
  ci: '',
  parentesco: '',
  responsable_pago: true,
};

// Versión de términos del consentimiento que la UI envía (texto del backend manda).
const CONSENT_VERSION = 'v1';

export function NuevoAlumno() {
  const navigate = useNavigate();

  // Datos del alumno
  const [apPaterno, setApPaterno] = useState('');
  const [apMaterno, setApMaterno] = useState('');
  const [nombres, setNombres] = useState('');
  const [ci, setCi] = useState('');
  const [fechaNac, setFechaNac] = useState('');
  const [disciplina, setDisciplina] = useState('');
  const [sucursalId, setSucursalId] = useState('');
  const [categoriaId, setCategoriaId] = useState('');
  const [contactoEmergencia, setContactoEmergencia] = useState('');

  // Tutores (≥1) + consentimiento obligatorio
  const [tutores, setTutores] = useState<TutorCreate[]>([{ ...EMPTY_TUTOR }]);
  const [consentimiento, setConsentimiento] = useState(false);

  // Catálogos
  const [sucursales, setSucursales] = useState<Sucursal[]>([]);
  const [categorias, setCategorias] = useState<Categoria[]>([]);

  // Estado de envío / errores
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    const controller = new AbortController();
    api
      .sucursales(controller.signal)
      .then(setSucursales)
      .catch(() => {
        /* el error de carga no bloquea el render del formulario */
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!sucursalId) {
      setCategorias([]);
      setCategoriaId('');
      return;
    }
    const controller = new AbortController();
    api
      .categorias(sucursalId, controller.signal)
      .then(setCategorias)
      .catch(() => setCategorias([]));
    setCategoriaId('');
    return () => controller.abort();
  }, [sucursalId]);

  function updateTutor(index: number, patch: Partial<TutorCreate>) {
    setTutores((prev) => prev.map((t, i) => (i === index ? { ...t, ...patch } : t)));
  }

  function addTutor() {
    setTutores((prev) => [...prev, { ...EMPTY_TUTOR, responsable_pago: false }]);
  }

  function removeTutor(index: number) {
    setTutores((prev) => (prev.length > 1 ? prev.filter((_, i) => i !== index) : prev));
  }

  // Validación de UX que refleja el 422 del backend (no duplica la regla dura).
  function validate(): Record<string, string> {
    const errs: Record<string, string> = {};
    if (!apPaterno.trim()) errs.ap_paterno = 'Requerido';
    if (!nombres.trim()) errs.nombres = 'Requerido';
    if (!ci.trim()) errs.ci = 'Requerido';
    if (!fechaNac) errs.fecha_nac = 'Requerido';
    if (!disciplina.trim()) errs.disciplina = 'Requerido';
    if (!sucursalId) errs.sucursal_id = 'Selecciona una sucursal';

    const tutoresValidos = tutores.filter((t) => t.nombres.trim());
    if (tutoresValidos.length === 0) {
      errs.tutores = 'Se requiere al menos un tutor con nombre.';
    }
    if (!consentimiento) {
      errs.consentimiento = 'El consentimiento del tutor es obligatorio.';
    }
    return errs;
  }

  // Mapea errores 422 del backend (loc) a campos del formulario.
  function applyApiErrors(err: ApiError) {
    const mapped: Record<string, string> = {};
    for (const fe of err.fieldErrors) {
      const loc = fe.loc.filter((p) => p !== 'body');
      const key = loc.join('.');
      if (loc.includes('tutores')) {
        mapped.tutores = fe.msg;
      } else if (loc.includes('consentimiento')) {
        mapped.consentimiento = fe.msg;
      } else if (typeof loc[0] === 'string') {
        mapped[loc[0]] = fe.msg;
      } else {
        mapped[key] = fe.msg;
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

    const payload: AlumnoCreate = {
      ap_paterno: apPaterno.trim(),
      ap_materno: apMaterno.trim(),
      nombres: nombres.trim(),
      ci: ci.trim(),
      fecha_nac: fechaNac,
      disciplina: disciplina.trim(),
      sucursal_id: sucursalId,
      categoria_id: categoriaId || null,
      contacto_emergencia: contactoEmergencia.trim(),
      tutores: tutores
        .filter((t) => t.nombres.trim())
        .map((t) => ({
          nombres: t.nombres.trim(),
          telefono: t.telefono.trim(),
          ci: t.ci.trim(),
          parentesco: t.parentesco.trim(),
          responsable_pago: t.responsable_pago,
        })),
      consentimiento: { version_terminos: CONSENT_VERSION, canal: 'WEB' },
    };

    setSubmitting(true);
    try {
      const created = await api.crearAlumno(payload);
      navigate(`/alumnos/${created.id}`, { replace: true });
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.isValidation) {
          applyApiErrors(err);
          setFormError('El servidor rechazó los datos. Revisa los campos marcados.');
        } else if (err.isForbidden) {
          setFormError('No tienes permiso para crear alumnos en esa sucursal.');
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
    <div className="nuevo-alumno">
      <Link to="/alumnos" className="perfil__back">
        ← Volver a alumnos
      </Link>

      <header className="page-head">
        <div>
          <h1 className="page-head__title">Nuevo alumno</h1>
          <p className="page-head__subtitle">
            Se requiere al menos un tutor y su consentimiento.
          </p>
        </div>
      </header>

      {formError && (
        <div className="page-error" role="alert">
          {formError}
        </div>
      )}

      <form onSubmit={handleSubmit} noValidate className="nuevo-alumno__form">
        <Card title="Datos del alumno">
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
              label="CI"
              value={ci}
              onChange={(e) => setCi(e.target.value)}
              error={fieldErrors.ci}
              placeholder="9123456 LP"
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
            <SelectField
              label="Categoría"
              value={categoriaId}
              onChange={(e) => setCategoriaId(e.target.value)}
              hint={!sucursalId ? 'Selecciona primero una sucursal' : undefined}
              disabled={!sucursalId}
            >
              <option value="">Sin categoría</option>
              {categorias.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.nombre} {nivelLabel(c.nivel)}
                </option>
              ))}
            </SelectField>
          </div>
          <div className="form-grid form-grid--single">
            <Field
              label="Contacto de emergencia"
              value={contactoEmergencia}
              onChange={(e) => setContactoEmergencia(e.target.value)}
              placeholder="Nombre y teléfono"
            />
          </div>
        </Card>

        <Card
          title="Tutores"
          actions={
            <Button variant="ghost" size="sm" onClick={addTutor}>
              + Añadir tutor
            </Button>
          }
        >
          {fieldErrors.tutores && (
            <p className="field__error" role="alert">
              {fieldErrors.tutores}
            </p>
          )}
          <div className="tutor-forms">
            {tutores.map((t, i) => (
              <fieldset className="tutor-form" key={i}>
                <legend className="tutor-form__legend">
                  Tutor {i + 1}
                  {tutores.length > 1 && (
                    <button
                      type="button"
                      className="tutor-form__remove"
                      onClick={() => removeTutor(i)}
                      aria-label={`Quitar tutor ${i + 1}`}
                    >
                      Quitar
                    </button>
                  )}
                </legend>
                <div className="form-grid">
                  <Field
                    label="Nombres"
                    value={t.nombres}
                    onChange={(e) => updateTutor(i, { nombres: e.target.value })}
                    required={i === 0}
                  />
                  <Field
                    label="Teléfono"
                    value={t.telefono}
                    onChange={(e) => updateTutor(i, { telefono: e.target.value })}
                  />
                  <Field
                    label="CI"
                    value={t.ci}
                    onChange={(e) => updateTutor(i, { ci: e.target.value })}
                  />
                  <Field
                    label="Parentesco"
                    value={t.parentesco}
                    onChange={(e) => updateTutor(i, { parentesco: e.target.value })}
                    placeholder="Madre / Padre / …"
                  />
                </div>
                <label className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={t.responsable_pago}
                    onChange={(e) => updateTutor(i, { responsable_pago: e.target.checked })}
                  />
                  Responsable de pago
                </label>
              </fieldset>
            ))}
          </div>
        </Card>

        <Card title="Consentimiento">
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
              El tutor acepta los términos y otorga su consentimiento para la inscripción del
              alumno. <strong>(Obligatorio)</strong>
            </span>
          </label>
          {fieldErrors.consentimiento && (
            <p className="field__error" role="alert">
              {fieldErrors.consentimiento}
            </p>
          )}
        </Card>

        <div className="nuevo-alumno__actions">
          <Button variant="secondary" onClick={() => navigate('/alumnos')}>
            Cancelar
          </Button>
          <Button type="submit" variant="primary" disabled={submitting}>
            {submitting ? 'Guardando…' : 'Crear alumno'}
          </Button>
        </div>
      </form>
    </div>
  );
}
