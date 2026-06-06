import { APP_NAME } from '@/config';

/**
 * Nombre de marca con el sufijo "SPORT" en color de acento (`var(--accent)`),
 * p. ej. LATINO + SPORT (azul). Si el nombre no termina en "sport", se renderiza
 * tal cual. El color sigue el acento del tema (cambia con el tweak verde/azul).
 */
export function BrandName({ className }: { className?: string }) {
  const match = /^(.*?)(sport)$/i.exec(APP_NAME);
  if (!match) {
    return <span className={className}>{APP_NAME}</span>;
  }
  const [, prefix, sport] = match;
  return (
    <span className={className}>
      {prefix}
      <span style={{ color: 'var(--accent)' }}>{sport}</span>
    </span>
  );
}
