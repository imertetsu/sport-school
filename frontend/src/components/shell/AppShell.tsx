import { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { TopBar } from './TopBar';
import { Sidebar } from './Sidebar';
import { SucursalProvider } from './SucursalContext';
import { SearchProvider } from './SearchContext';
import './AppShell.css';

export function AppShell() {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <SucursalProvider>
      <SearchProvider>
        <div className="appshell">
          <TopBar onToggleSidebar={() => setCollapsed((c) => !c)} />
          <div className="appshell__body">
            <Sidebar collapsed={collapsed} />
            <main className="appshell__main">
              <Outlet />
            </main>
          </div>
        </div>
      </SearchProvider>
    </SucursalProvider>
  );
}
