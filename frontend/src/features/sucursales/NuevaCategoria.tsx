import { useEffect, useState, type FormEvent } from 'react';
import { api, ApiError } from '@/api/client';
import type {
  Categoria,
  CategoriaCreate,
  CategoriaUpdate,
  DisciplinaRef,
  Nivel,
} from '@/api/types';
import { Button, Card, Field, SelectField } from '@/components/ui';

// Niveles válidos (= CHECK de BD: PRINCIPIANTE|INTERMEDIO|AVANZADO). Si el
// backend rechaza un nivel (422), se refleja en el campo.
const NIVELES: { value: Nivel; label: string }[] = [
  { value: 'PRINCIPIANTE', label: 'Principiante' },
  { value: 'INTERMEDIO', label: 'Intermedio' },
  { value: 'AVANZADO', label: 'Avanzado' },
];

// Forma mínima de la categoría a editar. Si se omite, crea una nueva.
export interface CategoriaEditable {
  id: string;
  nombre: string;
  nivel: Nivel;
  rango_edad: string; // "" si no hay (la forma de lectura lo sirve como string)
  // Disciplinas (S2): FK opcional al catálogo global; null/undefined = sin
  // disciplina. Se precarga al editar.
  disciplina_id?: string | null;
}

export interface NuevaCategoriaProps {
  // Sucursal a la que pertenece la categoría (sucursal_id fijo, no editable).
  sucursalId: string;
  // Categoría a editar; si se omite, crea una nueva.
  categoria?: CategoriaEditable | null;
  onClose: () => void;
  // El padre refresca la lista con la categoría creada/editada.
  onSaved: (categoria: Categoria) => void;
}

// Formulario de alta/edición de categoría (modal, solo ADMIN). nivel es un select
// (PRINCIPIANTE/INTERMEDIO/AVANZADO) y rango_edad es opcional. En edición NO se
// envía sucursal_id (no editable por contrato). El backend valida (422).
export function NuevaCategoria({
  sucursalId,
  categoria,
  onClose,
  onSaved,
}: NuevaCategoriaProps) {
  const editar = Boolean(categoria);

  const [nombre, setNombre] = useState(categoria?.nombre ?? '');
  const [nivel, setNivel] = useState<Nivel>(categoria?.nivel ?? 'PRINCIPIANTE');
  const [rangoEdad, setRangoEdad] = useState(categoria?.rango_edad ?? '');
  // Disciplina (S2): "" = sin disciplina (opción "— Sin disciplina —"). Precarga
  // el disciplina_id de la categoría al editar.
  const [disciplinaId, setDisciplinaId] = useState(categoria?.disciplina_id ?? '');
  // Catálogo global de disciplinas activas (poblar el select).
  const [disciplinas, setDisciplinas] = useState<DisciplinaRef[]>([]);

  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  // Carga el catálogo de disciplinas (solo activas) para el select. Si falla, el
  // select queda solo con "— Sin disciplina —" (la disciplina es opcional).
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
        // No bloquea el formulario: la disciplina es opcional.
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, []);

  // Validación de UX que refleja la del backend (no la reemplaza).
  function validate(): Record<string, string> {
    const errs: Record<string, string> = {};
    if (!nombre.trim()) errs.nombre = 'Requerido';
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

    // "" (sin disciplina) => null para el backend (limpia / no asigna).
    const disciplina_id = disciplinaId || null;

    setSubmitting(true);
    try {
      const saved = categoria
        ? await api.actualizarCategoria(categoria.id, {
            nombre: nombre.trim(),
            nivel,
            rango_edad: rangoEdad.trim() || null,
            disciplina_id,
          } satisfies CategoriaUpdate)
        : await api.crearCategoria({
            nombre: nombre.trim(),
            nivel,
            rango_edad: rangoEdad.trim() || null,
            sucursal_id: sucursalId,
            disciplina_id,
          } satisfies CategoriaCreate);
      onSaved(saved);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.isValidation) {
          applyApiErrors(err);
          setFormError('El servidor rechazó los datos. Revisa los campos marcados.');
        } else if (err.isForbidden) {
          setFormError('No tienes permiso para gestionar categorías.');
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
      className="sucursales__modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label={editar ? 'Editar categoría' : 'Nueva categoría'}
      onClick={(e) => {
        if (e.target === e.currentTarget && !submitting) onClose();
      }}
    >
      <div className="sucursales__modal">
        <Card title={editar ? 'Editar categoría' : 'Nueva categoría'}>
          {formError && (
            <div className="page-error" role="alert">
              {formError}
            </div>
          )}
          <form onSubmit={handleSubmit} noValidate className="sucursales__modal-form">
            <Field
              label="Nombre"
              value={nombre}
              onChange={(e) => setNombre(e.target.value)}
              error={fieldErrors.nombre}
              placeholder="Sub-12"
              required
            />
            <SelectField
              label="Nivel"
              value={nivel}
              onChange={(e) => setNivel(e.target.value as Nivel)}
              error={fieldErrors.nivel}
              required
            >
              {NIVELES.map((n) => (
                <option key={n.value} value={n.value}>
                  {n.label}
                </option>
              ))}
            </SelectField>
            <SelectField
              label="Disciplina"
              value={disciplinaId}
              onChange={(e) => setDisciplinaId(e.target.value)}
              error={fieldErrors.disciplina_id}
            >
              <option value="">— Sin disciplina —</option>
              {disciplinas.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.nombre}
                </option>
              ))}
            </SelectField>
            <Field
              label="Rango de edad"
              value={rangoEdad}
              onChange={(e) => setRangoEdad(e.target.value)}
              error={fieldErrors.rango_edad}
              placeholder="Opcional. Ej.: 10-12 años"
            />
            <div className="sucursales__modal-actions">
              <Button variant="secondary" onClick={onClose} disabled={submitting}>
                Cancelar
              </Button>
              <Button type="submit" variant="primary" disabled={submitting}>
                {submitting
                  ? 'Guardando…'
                  : editar
                    ? 'Guardar cambios'
                    : 'Crear categoría'}
              </Button>
            </div>
          </form>
        </Card>
      </div>
    </div>
  );
}
