import { useEffect, useState, type FormEvent } from 'react';
import { api, ApiError } from '@/api/client';
import type {
  Categoria,
  DiaSemana,
  EntrenadorOut,
  HorarioCreate,
  HorarioCreated,
} from '@/api/types';
import { Button, Card, Field, SelectField } from '@/components/ui';

// Forma mínima del horario a editar (lo arma la rejilla a partir de la clase +
// el día). Si se omite, el formulario crea uno nuevo.
export interface HorarioEditable {
  id: string;
  categoria_id: string;
  dia_semana: DiaSemana;
  hora_inicio: string; // HH:MM
  hora_fin: string; // HH:MM
  entrenador_id: string | null;
}

export interface NuevoHorarioProps {
  // Horario a editar; si se omite, el formulario crea uno nuevo.
  horario?: HorarioEditable | null;
  // Sucursal activa del filtro (scope para cargar las categorías del selector).
  sucursalId?: string;
  onClose: () => void;
  // El padre refresca la rejilla con el horario creado/editado.
  onSaved: (horario: HorarioCreated) => void;
}

// Días de la semana: 0=Lunes … 6=Domingo (= date.weekday() del backend, C1).
const DIAS: { value: DiaSemana; label: string }[] = [
  { value: 0, label: 'Lunes' },
  { value: 1, label: 'Martes' },
  { value: 2, label: 'Miércoles' },
  { value: 3, label: 'Jueves' },
  { value: 4, label: 'Viernes' },
  { value: 5, label: 'Sábado' },
  { value: 6, label: 'Domingo' },
];

// Recorta "HH:MM:SS" -> "HH:MM" para el <input type="time"> (acepta HH:MM).
function toTimeInput(t: string): string {
  return t.slice(0, 5);
}

// Formulario de alta/edición de horario (modal, solo ADMIN). Valida UX
// (hora_fin > hora_inicio), pero el backend es la fuente de verdad: refleja sus
// 422 (validación) y 409 (unicidad categoria+día+hora_inicio).
export function NuevoHorario({ horario, sucursalId, onClose, onSaved }: NuevoHorarioProps) {
  const editar = Boolean(horario);

  const [categoriaId, setCategoriaId] = useState(horario?.categoria_id ?? '');
  const [diaSemana, setDiaSemana] = useState<DiaSemana>(horario?.dia_semana ?? 0);
  const [horaInicio, setHoraInicio] = useState(
    horario ? toTimeInput(horario.hora_inicio) : '',
  );
  const [horaFin, setHoraFin] = useState(horario ? toTimeInput(horario.hora_fin) : '');
  // Entrenador opcional. Se elige de la lista real de activos (Epic B); ''
  // representa la opción "Sin entrenador" (envía entrenador_id = null).
  const [entrenadorId, setEntrenadorId] = useState(horario?.entrenador_id ?? '');

  const [categorias, setCategorias] = useState<Categoria[]>([]);
  const [entrenadores, setEntrenadores] = useState<EntrenadorOut[]>([]);

  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  // Carga las categorías para el selector (scoped por rol/sucursal en backend).
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    api
      .categorias(sucursalId, controller.signal)
      .then((data) => {
        if (active) setCategorias(data);
      })
      .catch((err) => {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        // No bloquea el formulario; el backend valida categoria_id.
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [sucursalId]);

  // Carga los entrenadores activos para el selector (Epic B). Scoped por org (RLS).
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    api
      .listEntrenadores(true, controller.signal)
      .then((data) => {
        if (active) setEntrenadores(data);
      })
      .catch((err) => {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        // No bloquea el formulario; el campo quedará con "Sin entrenador".
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, []);

  // Validación de UX que refleja la del backend (no la reemplaza).
  function validate(): Record<string, string> {
    const errs: Record<string, string> = {};
    if (!categoriaId) errs.categoria_id = 'Elige una categoría';
    if (!horaInicio) errs.hora_inicio = 'Requerido';
    if (!horaFin) errs.hora_fin = 'Requerido';
    if (horaInicio && horaFin && horaFin <= horaInicio) {
      errs.hora_fin = 'La hora de fin debe ser posterior a la de inicio';
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

    const payload: HorarioCreate = {
      categoria_id: categoriaId,
      dia_semana: diaSemana,
      hora_inicio: horaInicio,
      hora_fin: horaFin,
      // '' = "Sin entrenador" -> null; cualquier otro valor es el id del select.
      entrenador_id: entrenadorId || null,
    };

    setSubmitting(true);
    try {
      const saved = horario
        ? await api.actualizarHorario(horario.id, payload)
        : await api.crearHorario(payload);
      onSaved(saved);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.isValidation) {
          applyApiErrors(err);
          setFormError('El servidor rechazó los datos. Revisa los campos marcados.');
        } else if (err.status === 409) {
          setFormError('Ya existe un horario para esa categoría, día y hora de inicio.');
        } else if (err.isForbidden) {
          setFormError('No tienes permiso para gestionar horarios.');
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
      className="horarios__modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label={editar ? 'Editar horario' : 'Nuevo horario'}
      onClick={(e) => {
        if (e.target === e.currentTarget && !submitting) onClose();
      }}
    >
      <div className="horarios__modal">
        <Card title={editar ? 'Editar horario' : 'Nuevo horario'}>
          {formError && (
            <div className="page-error" role="alert">
              {formError}
            </div>
          )}
          <form onSubmit={handleSubmit} noValidate className="horarios__modal-form">
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

            <SelectField
              label="Día de la semana"
              value={String(diaSemana)}
              onChange={(e) => setDiaSemana(Number(e.target.value) as DiaSemana)}
              error={fieldErrors.dia_semana}
              required
            >
              {DIAS.map((d) => (
                <option key={d.value} value={d.value}>
                  {d.label}
                </option>
              ))}
            </SelectField>

            <div className="horarios__modal-row">
              <Field
                label="Hora de inicio"
                type="time"
                value={horaInicio}
                onChange={(e) => setHoraInicio(e.target.value)}
                error={fieldErrors.hora_inicio}
                required
              />
              <Field
                label="Hora de fin"
                type="time"
                value={horaFin}
                onChange={(e) => setHoraFin(e.target.value)}
                error={fieldErrors.hora_fin}
                required
              />
            </div>

            <SelectField
              label="Entrenador"
              value={entrenadorId}
              onChange={(e) => setEntrenadorId(e.target.value)}
              error={fieldErrors.entrenador_id}
              hint="Opcional. Elige «Sin entrenador» si aún no hay uno asignado."
            >
              <option value="">Sin entrenador</option>
              {entrenadores.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.nombres}
                </option>
              ))}
            </SelectField>

            <div className="horarios__modal-actions">
              <Button variant="secondary" onClick={onClose} disabled={submitting}>
                Cancelar
              </Button>
              <Button type="submit" variant="primary" disabled={submitting}>
                {submitting
                  ? 'Guardando…'
                  : editar
                    ? 'Guardar cambios'
                    : 'Crear horario'}
              </Button>
            </div>
          </form>
        </Card>
      </div>
    </div>
  );
}
