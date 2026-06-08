import { useEffect, useState, type FormEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api, ApiError } from '@/api/client';
import type {
  DeportistaCreate,
  DeportistaDetail,
  DeportistaUpdate,
  DisciplinaRef,
  Categoria,
  Sucursal,
  TutorByCi,
  TutorCreate,
  TutorUpsert,
} from '@/api/types';
import { Button, Card, Field, SelectField } from '@/components/ui';
import { DocumentScanner, type CedulaFields } from '@/components/ocr/DocumentScanner';
import { nivelLabel } from '@/lib/format';
import './NuevoDeportista.css';

// Estado interno del formulario de tutor: campos SIEMPRE string para inputs
// controlados. El CI del tutor es opcional (se mapea a TutorCreate.ci al enviar;
// "" => omitido). Distinto del CI del deportista, que es obligatorio.
// `id`: solo en modo EDICIÓN, es el id del vínculo/tutor existente. La lista del
// PUT es RECONCILIABLE por id: con id => edita el existente; sin id => alta o
// recupera-por-CI; lo que NO se envía se desvincula (el backend valida el
// invariante de menores -> 422).
type TutorForm = Omit<TutorCreate, 'ci'> & { ci: string; id?: string };

const EMPTY_TUTOR: TutorForm = {
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
  // Distingue ALTA de EDICIÓN: si la ruta trae :id (/deportistas/:id/editar),
  // estamos editando un deportista existente; si no, es un alta nueva
  // (/deportistas/nuevo). isEdit gobierna título/botones, la precarga, el OCR y
  // el endpoint (PUT vs POST).
  const { id } = useParams<{ id: string }>();
  const isEdit = Boolean(id);

  // Carga del detalle en modo edición (precarga). loadError corta el render del
  // formulario (no tiene sentido editar lo que no se pudo cargar).
  const [loading, setLoading] = useState(isEdit);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Datos del deportista
  const [apPaterno, setApPaterno] = useState('');
  const [apMaterno, setApMaterno] = useState('');
  const [nombres, setNombres] = useState('');
  const [ci, setCi] = useState('');
  const [fechaNac, setFechaNac] = useState('');
  // Disciplina: select del catálogo global (S3). El contrato POST /deportistas
  // acepta el FK canónico `disciplina_id`; enviamos el id de la disciplina elegida.
  // "" => null (sin disciplina). El backend deriva el nombre legacy.
  const [disciplinaId, setDisciplinaId] = useState('');
  const [sucursalId, setSucursalId] = useState('');
  const [categoriaId, setCategoriaId] = useState('');
  const [contactoEmergencia, setContactoEmergencia] = useState('');
  // Campos OPCIONALES (string|null). "" => null al enviar; nunca bloquean el alta.
  const [domicilio, setDomicilio] = useState('');
  const [lugarNacimiento, setLugarNacimiento] = useState('');

  // Ficha médica (OPCIONAL). Grupo sanguíneo = ficha_medica.tipo_sangre.
  const [tipoSangre, setTipoSangre] = useState('');
  const [alergias, setAlergias] = useState('');
  const [condiciones, setCondiciones] = useState('');

  // Tutores (≥1) + consentimiento obligatorio
  const [tutores, setTutores] = useState<TutorForm[]>([{ ...EMPTY_TUTOR }]);
  const [consentimiento, setConsentimiento] = useState(false);
  // En EDICIÓN el consentimiento ya existe y NO se reenvía (DeportistaUpdate no
  // lo incluye); guardamos el flag solo para mostrarlo como ya otorgado.
  const [consentimientoExistente, setConsentimientoExistente] = useState(false);

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

  // Precarga en modo EDICIÓN: trae el detalle por id y rellena el formulario
  // (datos + tutores con su id + ficha médica). 404/403/red cortan el render con
  // un error claro. No dispara el recuperar-por-CI (ya tenemos el registro).
  useEffect(() => {
    if (!id) return;
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setLoadError(null);
    api
      .deportista(id, controller.signal)
      .then((d) => {
        if (!active) return;
        cargarDeportista(d);
        // El aviso "Se recuperó el registro anterior" es del flujo de alta; en
        // edición no aplica (siempre estamos editando un registro existente).
        setRecuperadoDeportista(false);
        setConsentimientoExistente(d.consentimiento != null);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        if (err instanceof ApiError) {
          setLoadError(
            err.isNotFound
              ? 'Deportista no encontrado.'
              : err.isForbidden
                ? 'No tienes acceso a este deportista.'
                : err.message,
          );
        } else {
          setLoadError('No se pudo cargar el deportista para editar.');
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
    // Solo re-ejecutar al cambiar el id de la ruta; cargarDeportista no se incluye
    // en deps a propósito (es estable para los fines de este efecto de precarga).
  }, [id]);

  // Carga los datos de un deportista recuperado en el formulario (modo recuperado).
  function cargarDeportista(d: DeportistaDetail) {
    setApPaterno(d.ap_paterno ?? '');
    setApMaterno(d.ap_materno ?? '');
    setNombres(d.nombres ?? '');
    setCi(d.ci ?? '');
    setFechaNac(d.fecha_nac ?? '');
    // Precarga el select con el FK canónico devuelto ("" si no tiene disciplina).
    setDisciplinaId(d.disciplina_id ?? '');
    setContactoEmergencia(d.contacto_emergencia ?? '');
    setDomicilio(d.domicilio ?? '');
    setLugarNacimiento(d.lugar_nacimiento ?? '');
    // Ficha médica: puede venir null si el rol no tiene acceso (RNF-02).
    if (d.ficha_medica) {
      setTipoSangre(d.ficha_medica.tipo_sangre ?? '');
      setAlergias(d.ficha_medica.alergias ?? '');
      setCondiciones(d.ficha_medica.condiciones ?? '');
    }
    if (d.sucursal?.id) setSucursalId(d.sucursal.id);
    if (d.categoria?.id) setCategoriaId(d.categoria.id);
    if (d.tutores && d.tutores.length > 0) {
      setTutores(
        d.tutores.map((t) => ({
          // Conservamos el id del tutor: en EDICIÓN el PUT reconcilia por id; en
          // alta-recuperada el POST lo ignora (usa TutorCreate sin id).
          id: t.id,
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
  // En EDICIÓN no aplica (ya estamos sobre un registro existente): no queremos que
  // tocar el CI dispare un lookup que sobrescriba el formulario.
  async function recuperarDeportistaPorCi(ciValor: string) {
    if (isEdit) return;
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
    // Campos opcionales del reverso (solo si el OCR los extrajo con confianza).
    if (fields.domicilio) setDomicilio(fields.domicilio);
    if (fields.lugarNacimiento) setLugarNacimiento(fields.lugarNacimiento);
    if (fields.grupoSanguineo) setTipoSangre(fields.grupoSanguineo);
    if (fields.numeroCi) {
      setCi(fields.numeroCi);
      void recuperarDeportistaPorCi(fields.numeroCi);
    }
  }

  function updateTutor(index: number, patch: Partial<TutorForm>) {
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
    // CI del deportista: OBLIGATORIO. Bloquea el submit si está vacío.
    if (!ci.trim()) errs.ci = 'El CI del deportista es obligatorio.';
    if (!fechaNac) errs.fecha_nac = 'Requerido';
    if (!disciplinaId) errs.disciplina_id = 'Requerido';
    if (!sucursalId) errs.sucursal_id = 'Selecciona una sucursal';

    const tutoresValidos = tutores.filter((t) => t.nombres.trim());
    if (tutoresValidos.length === 0) {
      errs.tutores = 'Se requiere al menos un tutor con nombre.';
    }
    // El consentimiento solo se captura en el ALTA. En EDICIÓN ya existe y no se
    // reenvía (DeportistaUpdate no lo incluye); el invariante de menores (>=1
    // tutor, no quitar al del consentimiento) lo valida el backend -> 422.
    if (!isEdit && !consentimiento) {
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

  // Ficha médica para el payload (alta/edición): solo si hay algún dato (toda
  // OPCIONAL). El backend acepta null/omitido. En edición, enviar "" en todos los
  // campos equivale a limpiarla; aquí solo la incluimos cuando hay contenido.
  function fichaMedicaPayload() {
    if (tipoSangre.trim() || alergias.trim() || condiciones.trim()) {
      return {
        tipo_sangre: tipoSangre.trim(),
        alergias: alergias.trim(),
        condiciones: condiciones.trim(),
      };
    }
    return null;
  }

  // Tutores a enviar (filtra los vacíos). En EDICIÓN conserva el `id` del vínculo
  // existente (reconciliación por id: con id => edita; sin id => alta/recupera-por-CI;
  // omitido => desvincula). En ALTA el id se descarta (TutorCreate no lo lleva).
  function tutoresPayload(): TutorUpsert[] {
    return tutores
      .filter((t) => t.nombres.trim())
      .map((t) => ({
        ...(isEdit && t.id ? { id: t.id } : {}),
        nombres: t.nombres.trim(),
        telefono: t.telefono.trim(),
        ci: t.ci.trim(),
        parentesco: t.parentesco.trim(),
        responsable_pago: t.responsable_pago,
      }));
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
      if (isEdit && id) {
        // EDICIÓN: PUT con todos los campos (los que no llegan no se tocan en el
        // backend; aquí los enviamos siempre para reflejar el estado del formulario).
        // El consentimiento NO va en el update (ya existe).
        const updatePayload: DeportistaUpdate = {
          ap_paterno: apPaterno.trim(),
          ap_materno: apMaterno.trim(),
          nombres: nombres.trim(),
          ci: ci.trim(),
          fecha_nac: fechaNac,
          disciplina_id: disciplinaId || null,
          sucursal_id: sucursalId,
          categoria_id: categoriaId || null,
          contacto_emergencia: contactoEmergencia.trim(),
          domicilio: domicilio.trim() || null,
          lugar_nacimiento: lugarNacimiento.trim() || null,
          tutores: tutoresPayload(),
          ficha_medica: fichaMedicaPayload(),
        };
        const updated = await api.actualizarDeportista(id, updatePayload);
        navigate(`/deportistas/${updated.id}`);
        return;
      }

      // ALTA: POST.
      const payload: DeportistaCreate = {
        ap_paterno: apPaterno.trim(),
        ap_materno: apMaterno.trim(),
        nombres: nombres.trim(),
        ci: ci.trim(),
        fecha_nac: fechaNac,
        // FK canónico (S3): "" => null. El backend valida y deriva el nombre legacy.
        disciplina_id: disciplinaId || null,
        sucursal_id: sucursalId,
        categoria_id: categoriaId || null,
        contacto_emergencia: contactoEmergencia.trim(),
        // Campos OPCIONALES: "" => null (no se envían como string vacío).
        domicilio: domicilio.trim() || null,
        lugar_nacimiento: lugarNacimiento.trim() || null,
        tutores: tutoresPayload(),
        consentimiento: { version_terminos: CONSENT_VERSION, canal: 'WEB' },
      };

      const ficha = fichaMedicaPayload();
      if (ficha) {
        payload.ficha_medica = ficha;
      }

      const created = await api.crearDeportista(payload);
      navigate(`/deportistas/${created.id}`, { replace: true });
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.isValidation) {
          applyApiErrors(err);
          setFormError(
            isEdit
              ? 'El servidor rechazó los cambios. Revisa los campos marcados y los tutores.'
              : 'El servidor rechazó los datos. Revisa los campos marcados.',
          );
        } else if (err.isConflict) {
          // CI duplicado: el deportista ya existe en la org (RNF-06, sin duplicar).
          setFieldErrors((prev) => ({
            ...prev,
            ci: 'Ya existe un deportista con ese CI en la organización.',
          }));
          setFormError(
            'Ya hay un deportista registrado con ese CI. Búscalo en la lista para editarlo en vez de crear un duplicado.',
          );
        } else if (err.isNotFound) {
          setFormError('El deportista ya no existe.');
        } else if (err.isForbidden) {
          setFormError(
            isEdit
              ? 'No tienes permiso para editar este deportista.'
              : 'No tienes permiso para crear deportistas en esa sucursal.',
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

  // Modo edición: mientras carga el detalle no pintamos el formulario (evita
  // mostrarlo vacío y luego rellenarlo); si la carga falla, cortamos con el error.
  if (isEdit && loading) {
    return <div className="perfil__state">Cargando deportista…</div>;
  }
  if (isEdit && loadError) {
    return (
      <div className="nuevo-deportista">
        <Link to="/deportistas" className="perfil__back">
          ← Volver a deportistas
        </Link>
        <div className="page-error" role="alert">
          {loadError}
        </div>
      </div>
    );
  }

  // Destino del enlace "Volver": al perfil en edición; a la lista en alta.
  const volverHref = isEdit && id ? `/deportistas/${id}` : '/deportistas';
  const volverLabel = isEdit ? '← Volver al perfil' : '← Volver a deportistas';

  return (
    <div className="nuevo-deportista">
      <Link to={volverHref} className="perfil__back">
        {volverLabel}
      </Link>

      <header className="page-head">
        <div>
          <h1 className="page-head__title">
            {isEdit ? 'Editar deportista' : 'Nuevo deportista'}
          </h1>
          <p className="page-head__subtitle">
            {isEdit
              ? 'Actualiza los datos, tutores y ficha médica. Debe quedar al menos un tutor.'
              : 'Se requiere al menos un tutor y su consentimiento.'}
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
          {/* OCR + recuperar-por-CI son del flujo de ALTA (pre-llenar una cédula
              nueva y evitar duplicados). En EDICIÓN ya tenemos el registro: el
              escáner no aplica y se oculta para no estorbar. */}
          {!isEdit && (
            <div className="nuevo-deportista__ocr">
              <p className="nuevo-deportista__ocr-hint">
                Escanea ambos lados de la cédula del deportista para pre-llenar los datos.
                Siempre puedes corregirlos a mano.
              </p>
              <DocumentScanner
                onExtract={handleOcr}
                label="Escanea anverso y reverso de la cédula del deportista."
              />
            </div>
          )}

          {!isEdit && recuperadoDeportista && (
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
              label="CI del deportista"
              value={ci}
              onChange={(e) => {
                setCi(e.target.value);
                // Editar el CI invalida el aviso de recuperación previo.
                setRecuperadoDeportista(false);
              }}
              onBlur={(e) => void recuperarDeportistaPorCi(e.target.value)}
              error={fieldErrors.ci}
              placeholder="9123456 LP"
              hint={
                isEdit
                  ? 'Obligatorio. No lo dejes vacío.'
                  : 'Obligatorio. El escaneo lo pre-llena; puedes corregirlo, no dejarlo vacío.'
              }
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
              value={disciplinaId}
              onChange={(e) => setDisciplinaId(e.target.value)}
              error={fieldErrors.disciplina_id}
              required
            >
              <option value="">— Sin disciplina —</option>
              {/* Si la disciplina recuperada no está en el catálogo (p.ej. inactiva),
                  conservamos el id cargado para no perder el valor. */}
              {disciplinaId && !disciplinas.some((d) => d.id === disciplinaId) && (
                <option value={disciplinaId}>Disciplina actual</option>
              )}
              {disciplinas.map((d) => (
                <option key={d.id} value={d.id}>
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
          <div className="form-grid">
            <Field
              label="Domicilio"
              value={domicilio}
              onChange={(e) => setDomicilio(e.target.value)}
              placeholder="Calle, número, zona"
              hint="Opcional"
            />
            <Field
              label="Lugar de nacimiento"
              value={lugarNacimiento}
              onChange={(e) => setLugarNacimiento(e.target.value)}
              placeholder="Ciudad / localidad"
              hint="Opcional"
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
        </Card>

        <Card title="Ficha médica">
          <p className="page-head__subtitle">Todos los campos son opcionales.</p>
          <div className="form-grid">
            <Field
              label="Grupo sanguíneo"
              value={tipoSangre}
              onChange={(e) => setTipoSangre(e.target.value)}
              placeholder="O+, A-, AB+…"
              hint="Opcional"
            />
            <Field
              label="Alergias"
              value={alergias}
              onChange={(e) => setAlergias(e.target.value)}
              placeholder="Penicilina, polen…"
              hint="Opcional"
            />
          </div>
          <div className="form-grid form-grid--single">
            <Field
              label="Condiciones médicas"
              value={condiciones}
              onChange={(e) => setCondiciones(e.target.value)}
              placeholder="Asma, diabetes…"
              hint="Opcional"
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
          {isEdit ? (
            // En EDICIÓN el consentimiento ya existe y no se reedita por aquí
            // (DeportistaUpdate no lo incluye). Solo se informa su estado.
            <div className="nuevo-deportista__notice" role="status">
              {consentimientoExistente
                ? 'El consentimiento del tutor ya fue otorgado y se conserva. El cambio de tutores respeta el invariante de menores (queda ≥1 tutor y no se quita al del consentimiento).'
                : 'Este deportista no tiene un consentimiento registrado. El editor de datos no lo modifica.'}
            </div>
          ) : (
            <>
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
                  El tutor acepta los términos y otorga su consentimiento para la inscripción
                  del deportista. <strong>(Obligatorio)</strong>
                </span>
              </label>
              {fieldErrors.consentimiento && (
                <p className="field__error" role="alert">
                  {fieldErrors.consentimiento}
                </p>
              )}
            </>
          )}
        </Card>

        <div className="nuevo-deportista__actions">
          <Button variant="secondary" onClick={() => navigate(volverHref)}>
            Cancelar
          </Button>
          <Button type="submit" variant="primary" disabled={submitting}>
            {submitting
              ? 'Guardando…'
              : isEdit
                ? 'Guardar cambios'
                : 'Crear deportista'}
          </Button>
        </div>
      </form>
    </div>
  );
}
