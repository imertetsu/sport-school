import { useNavigate } from 'react-router-dom';
import { BrandName } from '@/components/BrandName';
import { useAuth } from '@/auth/useAuth';
import { useAccent } from '@/theme/useAccent';
import { Avatar } from '@/components/ui';
import { useSucursales } from './SucursalContext';
import { useSearch } from './SearchContext';
import type { Role } from '@/api/types';
import './TopBar.css';

const ROLE_LABEL: Record<Role, string> = {
  ADMIN: 'Administrador',
  ENTRENADOR: 'Entrenador',
};

export interface TopBarProps {
  onToggleSidebar: () => void;
}

export function TopBar({ onToggleSidebar }: TopBarProps) {
  const { user, viewRole, logout } = useAuth();
  const { accent, toggle: toggleAccent } = useAccent();
  const { sucursales, selected, setSelected } = useSucursales();
  const { query, setQuery } = useSearch();
  const navigate = useNavigate();

  // Rol real del usuario (no modificable desde la UI). Se retiró el toggle de
  // prototipo que permitía a un ENTRENADOR ponerse en vista ADMIN.
  const role: Role = viewRole ?? 'ADMIN';

  function handleSearchKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') navigate('/alumnos');
  }

  return (
    <header className="topbar">
      <div className="topbar__left">
        <button
          type="button"
          className="topbar__icon-btn topbar__menu"
          onClick={onToggleSidebar}
          aria-label="Mostrar u ocultar menú"
        >
          ☰
        </button>
        <div className="topbar__brand">
          <span className="topbar__logo" aria-hidden="true">
            ⬡
          </span>
          <BrandName className="topbar__brand-name" />
        </div>
      </div>

      <div className="topbar__center">
        <label className="topbar__sucursal">
          <span className="sr-only">Sucursal</span>
          <select
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            aria-label="Filtrar por sucursal"
          >
            <option value="">Todas las sucursales</option>
            {sucursales.map((s) => (
              <option key={s.id} value={s.id}>
                {s.nombre}
              </option>
            ))}
          </select>
        </label>

        <div className="topbar__search">
          <span className="topbar__search-icon" aria-hidden="true">
            ⌕
          </span>
          <input
            type="search"
            placeholder="Buscar alumno, CI o…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleSearchKey}
            aria-label="Buscar alumno"
          />
        </div>
      </div>

      <div className="topbar__right">
        <button
          type="button"
          className="topbar__icon-btn"
          onClick={toggleAccent}
          aria-label={`Cambiar acento (actual: ${accent})`}
          title={`Acento: ${accent === 'verde' ? 'verde' : 'azul'}`}
        >
          <span className={`topbar__accent-dot topbar__accent-dot--${accent}`} />
        </button>

        <button
          type="button"
          className="topbar__icon-btn"
          aria-label="Notificaciones"
          title="Notificaciones"
        >
          <span aria-hidden="true">🔔</span>
        </button>

        <div className="topbar__user" title={`${user?.nombre ?? 'Usuario'} · ${ROLE_LABEL[role]}`}>
          <Avatar name={user?.nombre ?? 'Usuario'} size="sm" />
          <span className="topbar__user-text">
            <span className="topbar__user-name">{user?.nombre ?? 'Usuario'}</span>
            <span className="topbar__user-role">{ROLE_LABEL[role]}</span>
          </span>
        </div>

        <button
          type="button"
          className="topbar__icon-btn topbar__logout"
          onClick={logout}
          aria-label="Cerrar sesión"
          title="Cerrar sesión"
        >
          ⎋
        </button>
      </div>
    </header>
  );
}
