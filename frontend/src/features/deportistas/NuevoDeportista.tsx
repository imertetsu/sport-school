import { useEffect, useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api, ApiError } from '@/api/client';
import type {
  DeportistaCreate,
  DeportistaDetail,
  DisciplinaRef,
  Categoria,
  Sucursal,
  TutorByCi,
  TutorCreate,
} from '@/api/types';
import { Button, Card, Field, SelectField } from '@/components/ui';
import { DocumentScanner, type CedulaFields } from '@/components/ocr/DocumentScanner';
import { nivelLabel } from '@/lib/format';
import './NuevoDeportista.css';

const EMPTY_TUTOR: TutorCreate = {
  nombres: '',
  telefono: '',
  ci: '',
  parentesco: '',
  responsable_pago: true,
};

// Versión de términos del consentimiento que la UI envía (texto del backend manda).
const CONSENT_VERSION = 'v1';

export function NuevoDeportista() {
  const navigate = useNavigate();

  // Datos del deportista
  const [apPaterno, setApPaterno] = useState('');
  const [apMaterno, setApMaterno] = useState('');
  const [nombres, setNombres] = useState('');
  const [ci, setCi] = useState('');
  const [fechaNac, setFechaNac] = useState('');
  // Disciplina: select del catálogo global (S2). El contrato POST /deportistas usa
  // el campo string `disciplina` (no `disciplina_id`); enviamos el NOMBRE de la
  // disciplina elegida. "" => "" (sin disciplina). Ver handoff en el reporte.
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
  const [disciplinas, setDisciplinas] = useState<DisciplinaRef[]>([]);

  // Recuperar-por-CI (S3): avisos no bloqueantes cuando se reutiliza un registro.
  const [recuperadoDeportista, setRecuperadoDeportista] = useState(false);
  // tutoresRecuperados[i] = true si el tutor i fue recuperado por su CI.
  const [tutoresRecuperados, setTutoresRecuperados] = useState<Record<number, boolean>>({});
  // CI ya consultado para el deportista (evita lookups repetidos en onBlur).
  const [ciConsultado, setCiConsultado] = useState<string | null>(null);

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

  // Catálogo global de disciplinas (solo activas) para el select. Si falla, el
  // select queda solo con "— Sin disciplina —" (la disciplina no bloquea el render).
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    api
      .disciplinasCatalogo(controller.signal)
      .then((data) => {
        if (active) setDisciplinas(data);
      })
      .catch((err) => {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        /* la disciplina es opcional para el render; no bloquea el formulario */
      });
    return () => {
      active = false;
      controller.abort();
    };
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

  // Carga los datos de un deportista recuperado en el formulario (modo recuperado).
  function cargarDeportista(d: DeportistaDetail) {
    setApPaterno(d.ap_paterno ?? '');
    setApMaterno(d.ap_materno ?? '');
    setNombres(d.nombres ?? '');
    setCi(d.ci ?? '');
    setFechaNac(d.fecha_nac ?? '');
    setDisciplina(d.disciplina ?? '');
    setContactoEmergencia(d.contacto_emergencia ?? '');
    if (d.sucursal?.id) setSucursalId(d.sucursal.id);
    if (d.categoria?.id) setCategoriaId(d.categoria.id);
    if (d.tutores && d.tutores.length > 0) {
      setTutores(
        d.tutores.map((t) => ({
          nombres: t.nombres ?? '',
          telefono: t.telefono ?? '',
          ci: t.ci ?? '',
          parentesco: t.parentesco ?? '',
          responsable_pago: t.responsable_pago,
        })),
      );
    }
    setRecuperadoDeportista(true);
  }

  // Recuperar-por-CI del deportista: si existe un registro con ese CI en la org, lo
  // carga (evita duplicado; el backend además da 409 al crear). 404 => alta nueva.
  async function recuperarDeportistaPorCi(ciValor: string) {
    const valor = ciValor.trim();
    if (!valor || valor === ciConsultado) return;
    setCiConsultado(valor);
    try {
      const d = await api.deportistaPorCi(valor);
      cargarDeportista(d);
    } catch (err) {
      if (err instanceof ApiError && err.isNotFound) {
        // No existe: alta nueva, sin aviso de recuperación.
        setRecuperadoDeportista(false);
        return;
      }
      /* otros errores (red/permiso) no bloquean el alta manual */
    }
  }

  // Recuperar-por-CI del tutor i: si existe en la org, reutiliza sus datos y permite
  // actualizar el teléfono (el backend reaplica el cambio al crear, contrato #4).
  async function recuperarTutorPorCi(index: number, ciValor: string) {
    const valor = ciValor.trim();
    if (!valor) return;
    try {
      const t: TutorByCi = await api.tutorPorCi(valor);
      setTutores((prev) =>
        prev.map((tut, i) =>
          i === index
            ? {
                ...tut,
                nombres: t.nombres ?? tut.nombres,
                telefono: t.telefono ?? tut.telefono,
                ci: t.ci ?? tut.ci,
              }
            : tut,
        ),
      );
      setTutoresRecuperados((prev) => ({ ...prev, [index]: true }));
    } catch (err) {
      if (err instanceof ApiError && err.isNotFound) {
        // No existe: alta normal del tutor.
        setTutoresRecuperados((prev) => ({ ...prev, [index]: false }));
        return;
      }
      /* otros errores no bloquean el alta manual del tutor */
    }
  }

  // OCR: pre-rellena los campos del deportista. El usuario SIEMPRE puede corregir.
  // Tras extraer, dispara el recuperar-por-CI del deportista con el CI detectado.
  function handleOcr(fields: CedulaFields) {
    if (fields.apellidoPaterno) setApPaterno(fields.apellidoPaterno);
    if (fields.apellidoMaterno) setApMaterno(fields.apellidoMaterno);
    if (fields.nombres) setNombres(fields.nombres);
    if (fields.fechaNacimiento) setFechaNac(fields.fechaNacimiento);
    if (fields.numeroCi) {
      setCi(fields.numeroCi);
      void recuperarDeportistaPorCi(fields.numeroCi);
    }
  }

  function updateTutor(index: number, patch: Partial<TutorCreate>) {
    setTutores((prev) => prev.map((t, i) => (i === index ? { ...t, ...patch } : t)));
  }

  function addTutor() {
    setTutores((prev) => [...prev, { ...EMPTY_TUTOR, responsable_pago: false }]);
  }

  function removeTutor(index: number) {
    setTutores((prev) => (prev.length > 1 ? prev.filter((_, i) => i !== index) : prev));
    setTutoresRecuperados((prev) => {
      const next: Record<number, boolean> = {};
      // Re-indexa los avisos de recuperación tras quitar el tutor `index`.
      for (const [k, v] of Object.entries(prev)) {
        const i = Number(k);
        if (i < index) next[i] = v;
        else if (i > index) next[i - 1] = v;
      }
      return next;
    });
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

    const payload: DeportistaCreate = {
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
      const created = await api.crearDeportista(payload);
      navigate(`/deportistas/${created.id}`, { replace: true });
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.isValidation) {
          applyApiErrors(err);
          setFormError('El servidor rechazó los datos. Revisa los campos marcados.');
        } else if (err.isConflict) {
          // CI duplicado: el deportista ya existe en la org (RNF-06, sin duplicar).
          setFieldErrors((prev) => ({
            ...prev,
            ci: 'Ya existe un deportista con ese CI en la organización.',
          }));
          setFormError(
            'Ya hay un deportista registrado con ese CI. Búscalo en la lista para editarlo en vez de crear un duplicado.',
          );
        } else if (err.isForbidden) {
          setFormError('No tienes permiso para crear deportistas en esa sucursal.');
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
    <div className="nuevo-deportista">
      <Link to="/deportistas" className="perfil__back">
        ← Volver a deportistas
      </Link>

      <header className="page-head">
        <div>
          <h1 className="page-head__title">Nuevo deportista</h1>
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

      <form onSubmit={handleSubmit} noValidate className="nuevo-deportista__form">
        <Card title="Datos del deportista">
          <div className="nuevo-deportista__ocr">
            <p className="nuevo-deportista__ocr-hint">
              Escanea la cédula para pre-llenar los datos. Siempre puedes corregirlos a mano.
            </p>
            <DocumentScanner onExtract={handleOcr} label="Escanear cédula del deportista" />
          </div>

          {recuperadoDeportista && (
            <div className="nuevo-deportista__notice" role="status">
              Se recuperó el registro anterior del deportista. Revisa los datos antes de
              guardar.
            </div>
          )}

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
              onChange={(e) => {
                setCi(e.target.value);
                // Editar el CI invalida el aviso de recuperación previo.
                setRecuperadoDeportista(false);
              }}
              onBlur={(e) => void recuperarDeportistaPorCi(e.target.value)}
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
            <SelectField
              label="Disciplina"
              value={disciplina}
              onChange={(e) => setDisciplina(e.target.value)}
              error={fieldErrors.disciplina}
              required
            >
              <option value="">— Sin disciplina —</option>
              {/* Si la disciplina recuperada no está en el catálogo, la mostramos
                  para no perder el valor cargado. */}
              {disciplina && !disciplinas.some((d) => d.nombre === disciplina) && (
                <option value={disciplina}>{disciplina}</option>
              )}
              {disciplinas.map((d) => (
                <option key={d.id} value={d.nombre}>
                  {d.nombre}
                </option>
              ))}
            </SelectField>
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
                {tutoresRecuperados[i] && (
                  <div className="nuevo-deportista__notice" role="status">
                    Se recuperó el tutor. Puedes actualizar su teléfono.
                  </div>
                )}
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
                    onBlur={(e) => void recuperarTutorPorCi(i, e.target.value)}
                    hint="Opcional. Si existe, se recupera el tutor."
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
              deportista. <strong>(Obligatorio)</strong>
            </span>
          </label>
          {fieldErrors.consentimiento && (
            <p className="field__error" role="alert">
              {fieldErrors.consentimiento}
            </p>
          )}
        </Card>

        <div className="nuevo-deportista__actions">
          <Button variant="secondary" onClick={() => navigate('/deportistas')}>
            Cancelar
          </Button>
          <Button type="submit" variant="primary" disabled={submitting}>
            {submitting ? 'Guardando…' : 'Crear deportista'}
          </Button>
        </div>
      </form>
    </div>
  );
}
