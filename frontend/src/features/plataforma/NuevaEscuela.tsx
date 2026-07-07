import { useState, type FormEvent } from 'react';
import { platformApi, ApiError } from '@/api/client';
import type { CrearEscuelaIn, EscuelaCreada } from '@/api/types';
import { Button, Card, Field, useToast } from '@/components/ui';

export interface NuevaEscuelaProps {
  onClose: () => void;
  onCreated: (escuela: EscuelaCreada) => void;
}

// Alta de escuela (organización + su primer usuario ADMIN) en una sola operación.
// Valida UX; el backend es la fuente de verdad (refleja 422/409). 409 =
// admin_email duplicado -> se muestra en el campo del correo del admin.
export function NuevaEscuela({ onClose, onCreated }: NuevaEscuelaProps) {
  const toast = useToast();
  const [nombre, setNombre] = useState('');
  const [pais, setPais] = useState('');
  const [moneda, setMoneda] = useState('');
  const [adminNombre, setAdminNombre] = useState('');
  const [adminEmail, setAdminEmail] = useState('');
  const [adminPassword, setAdminPassword] = useState('');

  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  function validate(): Record<string, string> {
    const errs: Record<string, string> = {};
    if (!nombre.trim()) errs.nombre = 'Requerido';
    if (!adminNombre.trim()) errs.admin_nombre = 'Requerido';
    if (!adminEmail.trim()) errs.admin_email = 'Requerido';
    if (!adminPassword) errs.admin_password = 'Requerido';
    else if (adminPassword.length < 8)
      errs.admin_password = 'Mínimo 8 caracteres';
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

    const payload: CrearEscuelaIn = {
      nombre: nombre.trim(),
      pais: pais.trim() || null,
      moneda: moneda.trim() || null,
      admin_nombre: adminNombre.trim(),
      admin_email: adminEmail.trim(),
      admin_password: adminPassword,
    };

    setSubmitting(true);
    try {
      const created = await platformApi.crearEscuela(payload);
      toast.success('Escuela creada');
      onCreated(created);
    } catch (err) {
      let msg: string;
      if (err instanceof ApiError) {
        if (err.status === 409) {
          setFieldErrors((prev) => ({
            ...prev,
            admin_email: 'Ya existe una cuenta con este correo.',
          }));
          msg = 'El correo del administrador ya está en uso.';
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
      aria-label="Crear escuela"
      onClick={(e) => {
        if (e.target === e.currentTarget && !submitting) onClose();
      }}
    >
      <div className="plataforma__modal">
        <Card title="Crear escuela">
          {formError && (
            <div className="page-error" role="alert">
              {formError}
            </div>
          )}
          <form onSubmit={handleSubmit} noValidate className="plataforma__modal-form">
            <Field
              label="Nombre de la escuela"
              value={nombre}
              onChange={(e) => setNombre(e.target.value)}
              error={fieldErrors.nombre}
              placeholder="Club Deportivo Aurora"
              required
            />
            <div className="plataforma__form-row">
              <Field
                label="País"
                value={pais}
                onChange={(e) => setPais(e.target.value)}
                error={fieldErrors.pais}
                placeholder="Bolivia"
                hint="Opcional"
              />
              <Field
                label="Moneda"
                value={moneda}
                onChange={(e) => setMoneda(e.target.value)}
                error={fieldErrors.moneda}
                placeholder="BOB"
                hint="Opcional (ISO 4217)"
              />
            </div>

            <p className="plataforma__form-section">Primer administrador</p>
            <Field
              label="Nombre del administrador"
              value={adminNombre}
              onChange={(e) => setAdminNombre(e.target.value)}
              error={fieldErrors.admin_nombre}
              placeholder="María Pérez"
              required
            />
            <Field
              label="Correo del administrador"
              type="email"
              autoComplete="off"
              value={adminEmail}
              onChange={(e) => setAdminEmail(e.target.value)}
              error={fieldErrors.admin_email}
              placeholder="admin@escuela.bo"
              required
            />
            <Field
              label="Contraseña inicial"
              type="password"
              autoComplete="new-password"
              value={adminPassword}
              onChange={(e) => setAdminPassword(e.target.value)}
              error={fieldErrors.admin_password}
              placeholder="••••••••"
              hint="El administrador podrá cambiarla luego."
              required
            />

            <div className="plataforma__modal-actions">
              <Button variant="secondary" onClick={onClose} disabled={submitting}>
                Cancelar
              </Button>
              <Button type="submit" variant="primary" disabled={submitting}>
                {submitting ? 'Creando…' : 'Crear escuela'}
              </Button>
            </div>
          </form>
        </Card>
      </div>
    </div>
  );
}
