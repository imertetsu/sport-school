// Definición de la navegación de la shell (design-system §Shell común).
// Los items aún no implementados quedan VISIBLES pero inertes ("Próximamente").

export interface NavItem {
  id: string;
  label: string;
  icon: string; // glifo simple para no añadir dependencia de iconos
  to?: string; // ruta si está implementado
  enabled: boolean;
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
      { id: 'asistencia', label: 'Asistencia', icon: '✓', enabled: false },
    ],
  },
  {
    title: 'Acciones',
    items: [{ id: 'qr', label: 'Generar QR', icon: '▦', enabled: false }],
  },
];
