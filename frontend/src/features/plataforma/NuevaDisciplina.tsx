import { useState, type FormEvent } from 'react';
import { platformApi, ApiError } from '@/api/client';
import type { Disciplina, DisciplinaCreate } from '@/api/types';
import { Button, Card, Field, useToast } from '@/components/ui';

export interface NuevaDisciplinaProps {
  onClose: () => void;
  onCreated: (disciplina: Disciplina) => void;
}

// Alta de disciplina del catálogo GLOBAL (consola de plataforma, SUPERADMIN).
// 409 = nombre duplicado case-insensitive (lower(nombre) ya existe) -> se muestra
// en el campo. Espejo de NuevoSuperAdmin.
export function NuevaDisciplina({ onClose, onCreated }: NuevaDisciplinaProps) {
  const toast = useToast();
  const [nombre, setNombre] = useState('');

  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  function validate(): Record<string, string> {
    const errs: Record<string, string> = {};
    if (!nombre.trim()) errs.nombre = 'Requerido';
    return errs;
  }

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

    const payload: DisciplinaCreate = { nombre: nombre.trim() };

    setSubmitting(true);
    try {
      const created = await platformApi.crearDisciplina(payload);
      toast.success('Disciplina creada');
      onCreated(created);
    } catch (err) {
      let msg: string;
      if (err instanceof ApiError) {
        if (err.status === 409) {
          setFieldErrors((prev) => ({
            ...prev,
            nombre: 'Ya existe una disciplina con este nombre.',
          }));
          msg = 'El nombre ya está en uso.';
        } else if (err.isValidation) {
          applyApiErrors(err);
          msg = 'El servidor rechazó los datos. Revisa los campos marcados.';
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
      className="plataforma__modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label="Crear disciplina"
      onClick={(e) => {
        if (e.target === e.currentTarget && !submitting) onClose();
      }}
    >
      <div className="plataforma__modal">
        <Card title="Crear disciplina">
          {formError && (
            <div className="page-error" role="alert">
              {formError}
            </div>
          )}
          <form onSubmit={handleSubmit} noValidate className="plataforma__modal-form">
            <Field
              label="Nombre"
              value={nombre}
              onChange={(e) => setNombre(e.target.value)}
              error={fieldErrors.nombre}
              placeholder="Vóleibol"
              required
            />
            <div className="plataforma__modal-actions">
              <Button variant="secondary" onClick={onClose} disabled={submitting}>
                Cancelar
              </Button>
              <Button type="submit" variant="primary" disabled={submitting}>
                {submitting ? 'Creando…' : 'Crear disciplina'}
              </Button>
            </div>
          </form>
        </Card>
      </div>
    </div>
  );
}
