// Definición de la navegación de la shell (design-system §Shell común).
// Los items aún no implementados quedan VISIBLES pero inertes ("Próximamente").

import type { Role } from '@/api/types';

export interface NavItem {
  id: string;
  label: string;
  icon: string; // glifo simple para no añadir dependencia de iconos
  to?: string; // ruta si está implementado
  enabled: boolean;
  // Roles que pueden VER el item. Si se omite, lo ven todos. Egresos y Reportes
  // son gerenciales: solo ADMIN (el item no aparece para ENTRENADOR).
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
      { id: 'deportistas', label: 'Deportistas', icon: '◉', to: '/deportistas', enabled: true },
      // Solicitudes (auto-registro EN SISTEMA): visible a ADMIN y ENTRENADOR
      // (sin `roles`). El backend filtra la cola por rol; aprobar/rechazar es solo ADMIN.
      { id: 'solicitudes', label: 'Solicitudes', icon: '✎', to: '/solicitudes', enabled: true },
      { id: 'pagos', label: 'Pagos', icon: '＄', to: '/pagos', enabled: true },
      // Lista de pagos + anular pago efectivo (epic anular-pago): punto de acceso
      // al botón "Anular". SOLO ADMIN (el item no aparece para ENTRENADOR).
      {
        id: 'pagos-lista',
        label: 'Anular pagos',
        icon: '↺',
        to: '/pagos-lista',
        enabled: true,
        roles: ['ADMIN'],
      },
      // Pagos por verificar (epic pagos-qr-comprobante): cola de comprobantes
      // entrantes por WhatsApp. SOLO ADMIN (el item no aparece para ENTRENADOR).
      {
        id: 'pagos-por-verificar',
        label: 'Por verificar',
        icon: '❏',
        to: '/pagos-por-verificar',
        enabled: true,
        roles: ['ADMIN'],
      },
      // Egresos (financiero): SOLO ADMIN (RF-FIN-07).
      { id: 'egresos', label: 'Egresos', icon: '▽', to: '/egresos', enabled: true, roles: ['ADMIN'] },
      // Entrenadores (Epic B): gestión SOLO ADMIN (el item no aparece para ENTRENADOR).
      { id: 'entrenadores', label: 'Entrenadores', icon: '♟', to: '/entrenadores', enabled: true, roles: ['ADMIN'] },
      { id: 'asistencia', label: 'Asistencia', icon: '✓', to: '/asistencia', enabled: true },
      // Horarios / programación de clases: visible a ADMIN y ENTRENADOR (sin `roles`).
      // El backend filtra la vista por rol; la escritura es solo ADMIN.
      { id: 'horarios', label: 'Horarios', icon: '◷', to: '/horarios', enabled: true },
      // Muro de avisos (RF-COM-01): visible a ADMIN y ENTRENADOR (sin `roles`).
      // El feed ya viene filtrado por el backend; la escritura es solo ADMIN.
      { id: 'avisos', label: 'Avisos', icon: '✸', to: '/avisos', enabled: true },
      {
        id: 'reportes',
        label: 'Reportes',
        icon: '▤',
        to: '/reportes',
        enabled: true,
        roles: ['ADMIN'],
      },
      // Sucursales/Categorías (catálogo): SOLO ADMIN (CRUD del catálogo).
      {
        id: 'sucursales',
        label: 'Sucursales',
        icon: '⌂',
        to: '/sucursales',
        enabled: true,
        roles: ['ADMIN'],
      },
      // Ajustes de la escuela (nombre + color del monograma): SOLO ADMIN.
      {
        id: 'ajustes',
        label: 'Ajustes',
        icon: '⚙',
        to: '/ajustes',
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
