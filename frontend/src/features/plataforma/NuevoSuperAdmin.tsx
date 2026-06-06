import { useState, type FormEvent } from 'react';
import { platformApi, ApiError } from '@/api/client';
import type { CrearSuperAdminIn, SuperAdminCreado } from '@/api/types';
import { Button, Card, Field } from '@/components/ui';

export interface NuevoSuperAdminProps {
  onClose: () => void;
  onCreated: (admin: SuperAdminCreado) => void;
}

// Alta de super admin de plataforma. 409 = email duplicado (se muestra en el campo).
export function NuevoSuperAdmin({ onClose, onCreated }: NuevoSuperAdminProps) {
  const [nombre, setNombre] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  function validate(): Record<string, string> {
    const errs: Record<string, string> = {};
    if (!nombre.trim()) errs.nombre = 'Requerido';
    if (!email.trim()) errs.email = 'Requerido';
    if (!password) errs.password = 'Requerido';
    else if (password.length < 8) errs.password = 'Mínimo 8 caracteres';
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

    const payload: CrearSuperAdminIn = {
      nombre: nombre.trim(),
      email: email.trim(),
      password,
    };

    setSubmitting(true);
    try {
      const created = await platformApi.crearAdmin(payload);
      onCreated(created);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409) {
          setFieldErrors((prev) => ({
            ...prev,
            email: 'Ya existe un super admin con este correo.',
          }));
          setFormError('El correo ya está en uso.');
        } else if (err.isValidation) {
          applyApiErrors(err);
          setFormError('El servidor rechazó los datos. Revisa los campos marcados.');
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
      className="plataforma__modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label="Crear super admin"
      onClick={(e) => {
        if (e.target === e.currentTarget && !submitting) onClose();
      }}
    >
      <div className="plataforma__modal">
        <Card title="Crear super admin">
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
              placeholder="Operador de plataforma"
              required
            />
            <Field
              label="Correo electrónico"
              type="email"
              autoComplete="off"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              error={fieldErrors.email}
              placeholder="operador@latinosport.com"
              required
            />
            <Field
              label="Contraseña"
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              error={fieldErrors.password}
              placeholder="••••••••"
              required
            />
            <div className="plataforma__modal-actions">
              <Button variant="secondary" onClick={onClose} disabled={submitting}>
                Cancelar
              </Button>
              <Button type="submit" variant="primary" disabled={submitting}>
                {submitting ? 'Creando…' : 'Crear super admin'}
              </Button>
            </div>
          </form>
        </Card>
      </div>
    </div>
  );
}
