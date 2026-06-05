import type { ReactNode } from 'react';
import './Card.css';

export interface CardProps {
  children: ReactNode;
  title?: ReactNode;
  actions?: ReactNode;
  className?: string;
  padded?: boolean;
}

export function Card({ children, title, actions, className, padded = true }: CardProps) {
  return (
    <section className={`card${className ? ` ${className}` : ''}`}>
      {(title || actions) && (
        <header className="card__header">
          {title ? <h3 className="card__title">{title}</h3> : <span />}
          {actions ? <div className="card__actions">{actions}</div> : null}
        </header>
      )}
      <div className={padded ? 'card__body' : 'card__body card__body--flush'}>
        {children}
      </div>
    </section>
  );
}
