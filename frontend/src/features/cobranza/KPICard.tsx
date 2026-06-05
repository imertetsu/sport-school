import './KPICard.css';

export interface KPICardProps {
  label: string;
  value: string;
  hint?: string;
  // "overdue" resalta la card en rojo (Cuotas vencidas — design-system §1).
  tone?: 'default' | 'overdue';
  loading?: boolean;
}

export function KPICard({ label, value, hint, tone = 'default', loading = false }: KPICardProps) {
  return (
    <div className={`kpi-card${tone === 'overdue' ? ' kpi-card--overdue' : ''}`}>
      <span className="kpi-card__label">{label}</span>
      <span className="kpi-card__value tabular">{loading ? '…' : value}</span>
      {hint && !loading && <span className="kpi-card__hint">{hint}</span>}
    </div>
  );
}
