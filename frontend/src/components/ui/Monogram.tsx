import { initialsFrom } from './Avatar';
import './Avatar.css';

// Monograma de la ESCUELA: iniciales del nombre en un círculo, con color elegido
// por el admin (org.color). Distinto del Avatar (que deriva su color del nombre):
// aquí el color lo decide la escuela; si es null/"" usamos un default DETERMINISTA
// derivado del nombre, para no romper la UI mientras no exista color.
const PALETTE = [
  '#16a34a',
  '#2563eb',
  '#7c3aed',
  '#db2777',
  '#ea580c',
  '#0891b2',
  '#ca8a04',
  '#dc2626',
];

function hashString(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) {
    h = (h << 5) - h + s.charCodeAt(i);
    h |= 0;
  }
  return Math.abs(h);
}

// Color válido sólo si es un hex #RGB/#RRGGBB (el backend valida #RRGGBB; el
// front es defensivo). Cualquier otra cosa -> default determinista por nombre.
function isHexColor(c: string | null | undefined): c is string {
  return !!c && /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(c.trim());
}

export interface MonogramProps {
  name: string;
  // Color elegido por la escuela (org.color). null/""/invalid => default por nombre.
  color?: string | null;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

export function Monogram({ name, color, size = 'md', className }: MonogramProps) {
  const resolved = isHexColor(color)
    ? color.trim()
    : PALETTE[hashString(name) % PALETTE.length];
  return (
    <span
      className={`avatar avatar--${size}${className ? ` ${className}` : ''}`}
      style={{ backgroundColor: resolved }}
      aria-hidden="true"
      title={name}
    >
      {initialsFrom(name)}
    </span>
  );
}
