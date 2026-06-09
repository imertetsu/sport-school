import { useEffect, useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { useMediaQuery } from '@/hooks/useMediaQuery';
import { TopBar } from './TopBar';
import { Sidebar } from './Sidebar';
import { SucursalProvider } from './SucursalContext';
import { SearchProvider } from './SearchContext';
import './AppShell.css';

export function AppShell() {
  // Escritorio: el botón ☰ colapsa el sidebar a iconos.
  const [collapsed, setCollapsed] = useState(false);
  // Móvil: el sidebar es un drawer off-canvas; ☰ lo abre/cierra.
  const [mobileOpen, setMobileOpen] = useState(false);
  const isMobile = useMediaQuery('(max-width: 768px)');
  const location = useLocation();

  // Cerrar el drawer al navegar (en móvil), y al pasar a escritorio.
  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);
  useEffect(() => {
    if (isMobile) setCollapsed(false); // el drawer siempre muestra labels
    else setMobileOpen(false);
  }, [isMobile]);

  const handleToggleSidebar = () => {
    if (isMobile) setMobileOpen((o) => !o);
    else setCollapsed((c) => !c);
  };

  return (
    <SucursalProvider>
      <SearchProvider>
        <div className="appshell">
          <TopBar onToggleSidebar={handleToggleSidebar} />
          <div className="appshell__body">
            <Sidebar
              collapsed={collapsed}
              mobileOpen={mobileOpen}
              onNavigate={() => setMobileOpen(false)}
            />
            {mobileOpen && (
              <div
                className="appshell__overlay"
                onClick={() => setMobileOpen(false)}
                aria-hidden="true"
              />
            )}
            <main className="appshell__main">
              <Outlet />
            </main>
          </div>
        </div>
      </SearchProvider>
    </SucursalProvider>
  );
}
