import { useEffect, useState, type FormEvent } from 'react';
import { api, ApiError } from '@/api/client';
import type {
  AprobarBody,
  Categoria,
  ModoCobro,
  SolicitudAlumnoCreado,
  SolicitudOut,
  Sucursal,
} from '@/api/types';
import { Button, Card, Field, SelectField } from '@/components/ui';
import { nivelLabel } from '@/lib/format';

export interface AprobarSolicitudProps {
  solicitud: SolicitudOut;
  // Sucursales del alcance del admin (de useSucursales).
  sucursales: Sucursal[];
  onClose: () => void;
  // El padre refresca la cola con el alumno creado.
  onApproved: (alumno: SolicitudAlumnoCreado) => void;
}

const MODO_COBRO_OPCIONES: { value: ModoCobro; label: string }[] = [
  { value: 'FIJO', label: 'Día fijo del mes' },
  { value: 'ANIVERSARIO', label: 'Aniversario de inscripción' },
];

// Modal de aprobación (solo ADMIN): confirma sucursal (req), categoría (opc) y,
// si se indica monto_mensual, crea también la inscripción. Al aprobar, el backend
// crea el alumno real reutilizando la lógica del epic Alumnos. 409 si ya resuelta.
export function AprobarSolicitud({
  solicitud,
  sucursales,
  onClose,
  onApproved,
}: AprobarSolicitudProps) {
  // Pre-rellena con las sugerencias de la solicitud (el admin las puede cambiar).
  const [sucursalId, setSucursalId] = useState(solicitud.sucursal_sugerida?.id ?? '');
  const [categoriaId, setCategoriaId] = useState(solicitud.categoria_sugerida?.id ?? '');
  const [montoMensual, setMontoMensual] = useState('');
  const [modoCobro, setModoCobro] = useState<ModoCobro | ''>('');

  const [categorias, setCategorias] = useState<Categoria[]>([]);

  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  // Carga las categorías de la sucursal elegida (scoped por rol en el backend).
  useEffect(() => {
    if (!sucursalId) {
      setCategorias([]);
      return;
    }
    const controller = new AbortController();
    let active = true;
    api
      .categorias(sucursalId, controller.signal)
      .then((data) => {
        if (active) setCategorias(data);
      })
      .catch((err) => {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        if (active) setCategorias([]);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [sucursalId]);

  // Si cambia la sucursal, la categoría sugerida puede no pertenecer: límpiala
  // cuando ya no esté entre las categorías cargadas.
  useEffect(() => {
    if (categoriaId && categorias.length > 0 && !categorias.some((c) => c.id === categoriaId)) {
      setCategoriaId('');
    }
  }, [categorias, categoriaId]);

  function validate(): Record<string, string> {
    const errs: Record<string, string> = {};
    if (!sucursalId) errs.sucursal_id = 'Selecciona una sucursal';
    if (montoMensual.trim() && Number(montoMensual) <= 0) {
      errs.monto_mensual = 'El monto debe ser mayor a 0';
    }
    return errs;
  }

  function applyApiErrors(err: ApiError) {
    const mapped: Record<string, string> = {};
    for (const fe of err.fieldErrors) {
      const loc = fe.loc.filter((p) => p !== 'body');
      if (typeof loc[0] === 'string') mapped[loc[0]] = fe.msg;
      else mapped[loc.join('.')] = fe.msg;
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

    const body: AprobarBody = {
      sucursal_id: sucursalId,
      categoria_id: categoriaId || null,
      monto_mensual: montoMensual.trim() || null,
      modo_cobro: montoMensual.trim() && modoCobro ? modoCobro : null,
    };

    setSubmitting(true);
    try {
      const alumno = await api.aprobarSolicitud(solicitud.id, body);
      onApproved(alumno);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.isValidation) {
          applyApiErrors(err);
          setFormError('El servidor rechazó los datos. Revisa los campos marcados.');
        } else if (err.isForbidden) {
          setFormError('No tienes permiso para aprobar solicitudes.');
        } else if (err.status === 409) {
          setFormError('Esta solicitud ya fue resuelta.');
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

  const nombreCompleto = `${solicitud.nombres} ${solicitud.ap_paterno} ${solicitud.ap_materno}`.trim();

  return (
    <div
      className="solicitudes__modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label="Aprobar solicitud"
      onClick={(e) => {
        if (e.target === e.currentTarget && !submitting) onClose();
      }}
    >
      <div className="solicitudes__modal">
        <Card title="Aprobar solicitud">
          <p className="solicitudes__modal-lead">
            Se creará el alumno <strong>{nombreCompleto}</strong> con su tutor y
            consentimiento.
          </p>
          {formError && (
            <div className="page-error" role="alert">
              {formError}
            </div>
          )}
          <form onSubmit={handleSubmit} noValidate className="solicitudes__modal-form">
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
              hint={!sucursalId ? 'Elige primero una sucursal' : undefined}
              disabled={!sucursalId}
            >
              <option value="">Sin categoría</option>
              {categorias.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.nombre} {nivelLabel(c.nivel)}
                </option>
              ))}
            </SelectField>

            <Field
              label="Monto mensual"
              type="number"
              min="0"
              step="0.01"
              value={montoMensual}
              onChange={(e) => setMontoMensual(e.target.value)}
              error={fieldErrors.monto_mensual}
              hint="Opcional: si lo indicas, se crea la inscripción."
              placeholder="0.00"
            />

            {montoMensual.trim() && (
              <SelectField
                label="Modo de cobro"
                value={modoCobro}
                onChange={(e) => setModoCobro(e.target.value as ModoCobro | '')}
                hint="Opcional."
              >
                <option value="">Por defecto</option>
                {MODO_COBRO_OPCIONES.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </SelectField>
            )}

            <div className="solicitudes__modal-actions">
              <Button variant="secondary" onClick={onClose} disabled={submitting}>
                Cancelar
              </Button>
              <Button type="submit" variant="primary" disabled={submitting}>
                {submitting ? 'Aprobando…' : 'Aprobar y crear alumno'}
              </Button>
            </div>
          </form>
        </Card>
      </div>
    </div>
  );
}
