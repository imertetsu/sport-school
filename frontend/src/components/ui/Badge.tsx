import type { ReactNode } from 'react';
import './Badge.css';

// Estados de cuota (fijos y consistentes en toda la app — design-system):
// verde = Pagado, ámbar = Pendiente, rojo = Vencido. + neutro/acento para otros usos.
export type BadgeTone =
  | 'paid' // verde — Pagado
  | 'pending' // ámbar — Pendiente
  | 'overdue' // rojo — Vencido
  | 'neutral'
  | 'accent';

export type EstadoCuota = 'PAGADO' | 'PENDIENTE' | 'VENCIDO';

const ESTADO_TONE: Record<EstadoCuota, BadgeTone> = {
  PAGADO: 'paid',
  PENDIENTE: 'pending',
  VENCIDO: 'overdue',
};

const ESTADO_LABEL: Record<EstadoCuota, string> = {
  PAGADO: 'Pagado',
  PENDIENTE: 'Pendiente',
  VENCIDO: 'Vencido',
};

export interface BadgeProps {
  tone?: BadgeTone;
  children: ReactNode;
  className?: string;
}

export function Badge({ tone = 'neutral', children, className }: BadgeProps) {
  return (
    <span className={`badge badge--${tone}${className ? ` ${className}` : ''}`}>
      {children}
    </span>
  );
}

// Atajo para el estado de cuota (cuando exista cobranza). Mapea a tono+etiqueta canónicos.
export function EstadoBadge({ estado }: { estado: EstadoCuota }) {
  return <Badge tone={ESTADO_TONE[estado]}>{ESTADO_LABEL[estado]}</Badge>;
}
