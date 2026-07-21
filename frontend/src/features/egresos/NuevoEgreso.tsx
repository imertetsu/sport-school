import { useState, type FormEvent } from 'react';
import { api, ApiError } from '@/api/client';
import type { EgresoCreate, EgresoCreated, MetodoPago, Sucursal } from '@/api/types';
import { Button, Card, Field, SelectField, useToast } from '@/components/ui';

// Fecha de hoy en formato YYYY-MM-DD (local), valor por defecto del campo.
function hoyISO(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

export interface NuevoEgresoProps {
  sucursales: Sucursal[];
  onClose: () => void;
  // El padre refresca la lista con el egreso creado.
  onCreated: (egreso: EgresoCreated) => void;
}

// Formulario de alta de egreso (modal). Valida UX (categoría no vacía, monto > 0),
// pero el backend es la fuente de verdad: refleja sus 422 en los campos.
export function NuevoEgreso({ sucursales, onClose, onCreated }: NuevoEgresoProps) {
  const toast = useToast();
  const [sucursalId, setSucursalId] = useState('');
  const [categoria, setCategoria] = useState('');
  const [monto, setMonto] = useState('');
  // Con qué se pagó el gasto: alimenta el desglose Efectivo/QR del panel.
  const [metodo, setMetodo] = useState<MetodoPago>('EFECTIVO');
  const [fecha, setFecha] = useState(hoyISO);
  const [descripcion, setDescripcion] = useState('');

  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  // Validación de UX que refleja el 422 del backend (no lo reemplaza).
  function validate(): Record<string, string> {
    const errs: Record<string, string> = {};
    if (!categoria.trim()) errs.categoria_gasto = 'Requerido';
    if (!fecha) errs.fecha = 'Requerido';
    const montoNum = Number(monto);
    if (!monto.trim() || Number.isNaN(montoNum)) {
      errs.monto = 'Ingresa un monto válido';
    } else if (montoNum <= 0) {
      errs.monto = 'El monto debe ser mayor que 0';
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

    const payload: EgresoCreate = {
      sucursal_id: sucursalId || null,
      categoria_gasto: categoria.trim(),
      // El monto se manda como string (numeric serializado); el backend decide.
      monto: monto.trim(),
      metodo,
      fecha,
      descripcion: descripcion.trim() || null,
    };

    setSubmitting(true);
    try {
      const created = await api.createEgreso(payload);
      toast.success('Egreso registrado');
      onCreated(created);
    } catch (err) {
      let msg = 'No se pudo conectar con el servidor.';
      if (err instanceof ApiError) {
        if (err.isValidation) {
          applyApiErrors(err);
          msg = 'El servidor rechazó los datos. Revisa los campos marcados.';
        } else if (err.isForbidden) {
          msg = 'No tienes permiso para registrar egresos.';
        } else {
          msg = err.message;
        }
      }
      setFormError(msg);
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="egresos__modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label="Registrar egreso"
      onClick={(e) => {
        if (e.target === e.currentTarget && !submitting) onClose();
      }}
    >
      <div className="egresos__modal">
        <Card title="Registrar egreso">
          {formError && (
            <div className="page-error" role="alert">
              {formError}
            </div>
          )}
          <form onSubmit={handleSubmit} noValidate className="egresos__modal-form">
            <Field
              label="Categoría de gasto"
              value={categoria}
              onChange={(e) => setCategoria(e.target.value)}
              error={fieldErrors.categoria_gasto}
              placeholder="Alquiler de cancha"
              required
            />
            <Field
              label="Monto"
              type="number"
              inputMode="decimal"
              min="0"
              step="0.01"
              value={monto}
              onChange={(e) => setMonto(e.target.value)}
              error={fieldErrors.monto}
              placeholder="1500.00"
              required
            />
            <SelectField
              label="Método de pago"
              value={metodo}
              onChange={(e) => setMetodo(e.target.value as MetodoPago)}
              error={fieldErrors.metodo}
              hint="Con qué se pagó el gasto (desglosa Egresos y Utilidad en el panel)."
            >
              <option value="EFECTIVO">Efectivo</option>
              <option value="QR">QR / transferencia</option>
            </SelectField>
            <Field
              label="Fecha"
              type="date"
              value={fecha}
              onChange={(e) => setFecha(e.target.value)}
              error={fieldErrors.fecha}
              required
            />
            <SelectField
              label="Sucursal"
              value={sucursalId}
              onChange={(e) => setSucursalId(e.target.value)}
              error={fieldErrors.sucursal_id}
              hint="Opcional: déjalo vacío para un gasto a nivel organización."
            >
              <option value="">Toda la organización</option>
              {sucursales.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.nombre}
                </option>
              ))}
            </SelectField>
            <Field
              label="Descripción"
              value={descripcion}
              onChange={(e) => setDescripcion(e.target.value)}
              error={fieldErrors.descripcion}
              placeholder="Opcional"
            />
            <div className="egresos__modal-actions">
              <Button variant="secondary" onClick={onClose} disabled={submitting}>
                Cancelar
              </Button>
              <Button type="submit" variant="primary" disabled={submitting}>
                {submitting ? 'Guardando…' : 'Registrar egreso'}
              </Button>
            </div>
          </form>
        </Card>
      </div>
    </div>
  );
}
