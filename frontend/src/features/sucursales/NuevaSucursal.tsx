import { useState, type FormEvent } from 'react';
import { api, ApiError } from '@/api/client';
import type { Sucursal, SucursalCreate } from '@/api/types';
import { Button, Card, Field, useToast } from '@/components/ui';

// Forma mínima de la sucursal a editar. Si se omite, el formulario crea una nueva.
export interface SucursalEditable {
  id: string;
  nombre: string;
  direccion: string; // "" si no hay (la forma de lectura lo sirve como string)
}

export interface NuevaSucursalProps {
  // Sucursal a editar; si se omite, el formulario crea una nueva.
  sucursal?: SucursalEditable | null;
  onClose: () => void;
  // El padre refresca la lista con la sucursal creada/editada.
  onSaved: (sucursal: Sucursal) => void;
}

// Formulario de alta/edición de sucursal (modal, solo ADMIN). Valida UX (nombre
// no vacío), pero el backend es la fuente de verdad: refleja sus 422.
export function NuevaSucursal({ sucursal, onClose, onSaved }: NuevaSucursalProps) {
  const toast = useToast();
  const editar = Boolean(sucursal);

  const [nombre, setNombre] = useState(sucursal?.nombre ?? '');
  const [direccion, setDireccion] = useState(sucursal?.direccion ?? '');

  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

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

    const payload: SucursalCreate = {
      nombre: nombre.trim(),
      direccion: direccion.trim() || null,
    };

    setSubmitting(true);
    try {
      const saved = sucursal
        ? await api.actualizarSucursal(sucursal.id, payload)
        : await api.crearSucursal(payload);
      toast.success(sucursal ? 'Sucursal actualizada' : 'Sucursal creada');
      onSaved(saved);
    } catch (err) {
      let msg: string;
      if (err instanceof ApiError) {
        if (err.isValidation) {
          applyApiErrors(err);
          msg = 'El servidor rechazó los datos. Revisa los campos marcados.';
        } else if (err.isForbidden) {
          msg = 'No tienes permiso para gestionar sucursales.';
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
      className="sucursales__modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label={editar ? 'Editar sucursal' : 'Nueva sucursal'}
      onClick={(e) => {
        if (e.target === e.currentTarget && !submitting) onClose();
      }}
    >
      <div className="sucursales__modal">
        <Card title={editar ? 'Editar sucursal' : 'Nueva sucursal'}>
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
              placeholder="Sucursal Centro"
              required
            />
            <Field
              label="Dirección"
              value={direccion}
              onChange={(e) => setDireccion(e.target.value)}
              error={fieldErrors.direccion}
              placeholder="Opcional"
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
                    : 'Crear sucursal'}
              </Button>
            </div>
          </form>
        </Card>
      </div>
    </div>
  );
}
