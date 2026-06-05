// Definición de la navegación de la shell (design-system §Shell común).
// Los items aún no implementados quedan VISIBLES pero inertes ("Próximamente").

import type { Role } from '@/api/types';

export interface NavItem {
  id: string;
  label: string;
  icon: string; // glifo simple para no añadir dependencia de iconos
  to?: string; // ruta si está implementado
  enabled: boolean;
  // Roles que pueden VER el item. Si se omite, lo ven todos. Reportes es
  // gerencial: solo ADMIN (C2 — el item no aparece para ENTRENADOR).
  roles?: Role[];
}

export interface NavGroup {
  title: string;
  items: NavItem[];
}

export const NAV_GROUPS: NavGroup[] = [
  {
    title: 'Gestión',
    items: [
      { id: 'panel', label: 'Panel', icon: '◧', to: '/panel', enabled: true }, // Panel de cobranza
      { id: 'alumnos', label: 'Alumnos', icon: '◉', to: '/alumnos', enabled: true },
      { id: 'pagos', label: 'Pagos', icon: '＄', to: '/pagos', enabled: true },
      { id: 'asistencia', label: 'Asistencia', icon: '✓', to: '/asistencia', enabled: true },
      {
        id: 'reportes',
        label: 'Reportes',
        icon: '▤',
        to: '/reportes',
        enabled: true,
        roles: ['ADMIN'],
      },
    ],
  },
  {
    title: 'Acciones',
    items: [{ id: 'qr', label: 'Generar QR', icon: '▦', enabled: false }],
  },
];

// Filtra los grupos según el rol activo: oculta items con `roles` que no
// incluyan el rol y descarta grupos que queden vacíos.
export function navGroupsForRole(role: Role | null): NavGroup[] {
  return NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => !item.roles || (role !== null && item.roles.includes(role))),
  })).filter((group) => group.items.length > 0);
}
