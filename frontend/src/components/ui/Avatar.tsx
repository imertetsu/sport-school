import './Avatar.css';

// Avatar con inicial + color derivado del nombre (determinista).
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

export function initialsFrom(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  if (parts.length === 1) return parts[0].slice(0, 1).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export interface AvatarProps {
  name: string;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

export function Avatar({ name, size = 'md', className }: AvatarProps) {
  const color = PALETTE[hashString(name) % PALETTE.length];
  return (
    <span
      className={`avatar avatar--${size}${className ? ` ${className}` : ''}`}
      style={{ backgroundColor: color }}
      aria-hidden="true"
      title={name}
    >
      {initialsFrom(name)}
    </span>
  );
}
