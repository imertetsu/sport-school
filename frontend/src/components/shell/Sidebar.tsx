import { NavLink } from 'react-router-dom';
import { navGroupsForRole } from './nav';
import { useAuth } from '@/auth/useAuth';
import './Sidebar.css';

const ROLE_LABEL: Record<string, string> = {
  ADMIN: 'Administrador',
  ENTRENADOR: 'Entrenador',
};

export interface SidebarProps {
  collapsed: boolean;
}

export function Sidebar({ collapsed }: SidebarProps) {
  const { user, viewRole } = useAuth();
  const roleLabel = viewRole ? ROLE_LABEL[viewRole] ?? viewRole : '';
  // Items gerenciales (Reportes) solo para ADMIN; el resto sigue igual.
  const groups = navGroupsForRole(viewRole);

  return (
    <aside className={`sidebar${collapsed ? ' sidebar--collapsed' : ''}`}>
      <nav className="sidebar__nav" aria-label="Navegación principal">
        {groups.map((group) => (
          <div className="sidebar__group" key={group.title}>
            <p className="sidebar__group-title">{group.title}</p>
            <ul className="sidebar__list">
              {group.items.map((item) =>
                item.enabled && item.to ? (
                  <li key={item.id}>
                    <NavLink
                      to={item.to}
                      className={({ isActive }) =>
                        `sidebar__item${isActive ? ' sidebar__item--active' : ''}`
                      }
                      title={collapsed ? item.label : undefined}
                    >
                      <span className="sidebar__icon" aria-hidden="true">
                        {item.icon}
                      </span>
                      <span className="sidebar__label">{item.label}</span>
                    </NavLink>
                  </li>
                ) : (
                  <li key={item.id}>
                    <span
                      className="sidebar__item sidebar__item--disabled"
                      aria-disabled="true"
                      title={collapsed ? `${item.label} · Próximamente` : 'Próximamente'}
                    >
                      <span className="sidebar__icon" aria-hidden="true">
                        {item.icon}
                      </span>
                      <span className="sidebar__label">{item.label}</span>
                      <span className="sidebar__soon">Próximamente</span>
                    </span>
                  </li>
                ),
              )}
            </ul>
          </div>
        ))}
      </nav>

      <div className="sidebar__footer" title={collapsed ? user?.nombre : undefined}>
        <span className="sidebar__status-dot" aria-hidden="true" />
        <span className="sidebar__footer-text">
          <span className="sidebar__footer-name">{user?.nombre ?? 'Usuario'}</span>
          <span className="sidebar__footer-role">{roleLabel}</span>
        </span>
      </div>
    </aside>
  );
}
