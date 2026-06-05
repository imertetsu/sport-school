import { useEffect, useState, type FormEvent } from 'react';
import { api, ApiError } from '@/api/client';
import type {
  AlcanceAviso,
  AvisoCreate,
  AvisoCreated,
  AvisoOut,
  Categoria,
  Sucursal,
} from '@/api/types';
import { Button, Card, Field, SelectField } from '@/components/ui';

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
  const editar = Boolean(aviso);

  const [titulo, setTitulo] = useState(aviso?.titulo ?? '');
  const [cuerpo, setCuerpo] = useState(aviso?.cuerpo ?? '');
  const [alcance, setAlcance] = useState<AlcanceAviso>(aviso?.alcance ?? 'ORG');
  const [sucursalId, setSucursalId] = useState(aviso?.sucursal?.id ?? '');
  const [categoriaId, setCategoriaId] = useState(aviso?.categoria?.id ?? '');
  const [vigenteHasta, setVigenteHasta] = useState(aviso?.vigente_hasta ?? '');

  // Categorías para el selector de alcance=CATEGORIA (scoped por rol en backend).
  const [categorias, setCategorias] = useState<Categoria[]>([]);

  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

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
    const payload: AvisoCreate = {
      titulo: titulo.trim(),
      cuerpo: cuerpo.trim(),
      alcance,
      sucursal_id: alcance === 'SUCURSAL' ? sucursalId : null,
      categoria_id: alcance === 'CATEGORIA' ? categoriaId : null,
      vigente_hasta: vigenteHasta || null,
    };

    setSubmitting(true);
    try {
      const saved = aviso
        ? await api.actualizarAviso(aviso.id, payload)
        : await api.crearAviso(payload);
      onSaved(saved);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.isValidation) {
          applyApiErrors(err);
          setFormError('El servidor rechazó los datos. Revisa los campos marcados.');
        } else if (err.isForbidden) {
          setFormError('No tienes permiso para publicar avisos.');
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

            <div className="avisos__modal-actions">
              <Button variant="secondary" onClick={onClose} disabled={submitting}>
                Cancelar
              </Button>
              <Button type="submit" variant="primary" disabled={submitting}>
                {submitting ? 'Guardando…' : editar ? 'Guardar cambios' : 'Publicar aviso'}
              </Button>
            </div>
          </form>
        </Card>
      </div>
    </div>
  );
}
