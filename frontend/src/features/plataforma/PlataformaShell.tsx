import { NavLink, Navigate, Outlet, useLocation } from 'react-router-dom';
import { Button } from '@/components/ui';
import { usePlatformAuth } from './PlataformaAuth';
import './Plataforma.css';

// Guard de la consola de plataforma: sin token de plataforma -> al login de
// plataforma (NO al login de escuela; son apps distintas). No reusa RoleRoute
// (que mira la sesión de escuela).
export function PlataformaGuard() {
  const { token } = usePlatformAuth();
  const location = useLocation();
  if (!token) {
    return <Navigate to="/plataforma/login" replace state={{ from: location }} />;
  }
  return <Outlet />;
}

// Layout mínimo de la consola: cabecera con marca + tabs Escuelas/Super Admins +
// botón salir. No usa el Sidebar de escuela (son aplicaciones separadas).
export function PlataformaShell() {
  const { admin, logout } = usePlatformAuth();

  return (
    <div className="plataforma">
      <header className="plataforma__topbar">
        <div className="plataforma__brand">
          <span className="plataforma__logo" aria-hidden="true">
            ⬡
          </span>
          <div>
            <span className="plataforma__brand-name">LATINOSPORT</span>
            <span className="plataforma__brand-tag">Consola de plataforma</span>
          </div>
        </div>
        <div className="plataforma__session">
          {admin && <span className="plataforma__admin">{admin.nombre}</span>}
          <Button variant="ghost" size="sm" onClick={logout}>
            Salir
          </Button>
        </div>
      </header>

      <nav className="plataforma__tabs" aria-label="Secciones de la consola">
        <NavLink
          to="/plataforma/escuelas"
          className={({ isActive }) =>
            `plataforma__tab${isActive ? ' plataforma__tab--active' : ''}`
          }
        >
          Escuelas
        </NavLink>
        <NavLink
          to="/plataforma/admins"
          className={({ isActive }) =>
            `plataforma__tab${isActive ? ' plataforma__tab--active' : ''}`
          }
        >
          Super Admins
        </NavLink>
      </nav>

      <main className="plataforma__main">
        <Outlet />
      </main>
    </div>
  );
}
