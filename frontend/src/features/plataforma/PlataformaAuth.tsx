import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import {
  platformApi,
  getPlatformToken,
  setPlatformToken,
  clearPlatformToken,
  getPlatformAdmin,
  setPlatformAdmin,
  clearPlatformAdmin,
  setPlatformUnauthorizedHandler,
} from '@/api/client';
import type { PlatformAdmin } from '@/api/types';

// Sesión de la consola de PLATAFORMA (rol SUPERADMIN, token SIN org_id). SEPARADA
// de la sesión de escuela (AuthContext): otro storage, otro provider, otro guard.
// La verdad de permisos la impone el backend; aquí solo gateamos la UI.
interface PlatformClaims {
  sub?: string;
  role?: string;
  exp?: number;
}

function decodeJwt(token: string): PlatformClaims | null {
  try {
    const payload = token.split('.')[1];
    if (!payload) return null;
    const normalized = payload.replace(/-/g, '+').replace(/_/g, '/');
    const json = decodeURIComponent(
      atob(normalized)
        .split('')
        .map((c) => '%' + c.charCodeAt(0).toString(16).padStart(2, '0'))
        .join(''),
    );
    return JSON.parse(json) as PlatformClaims;
  } catch {
    return null;
  }
}

function isExpired(claims: PlatformClaims | null): boolean {
  if (!claims?.exp) return false;
  return claims.exp * 1000 <= Date.now();
}

export interface PlatformAuthState {
  token: string | null;
  admin: PlatformAdmin | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const PlatformAuthContext = createContext<PlatformAuthState | null>(null);

export function PlatformAuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(() => {
    const t = getPlatformToken();
    if (t && isExpired(decodeJwt(t))) {
      clearPlatformToken();
      clearPlatformAdmin();
      return null;
    }
    return t;
  });
  const [admin, setAdminState] = useState<PlatformAdmin | null>(() =>
    getPlatformToken() ? getPlatformAdmin() : null,
  );

  const logout = useCallback(() => {
    clearPlatformToken();
    clearPlatformAdmin();
    setTokenState(null);
    setAdminState(null);
  }, []);

  // Reaccionar a un 401 global del cliente de plataforma.
  useEffect(() => {
    setPlatformUnauthorizedHandler(() => logout());
    return () => setPlatformUnauthorizedHandler(null);
  }, [logout]);

  const login = useCallback(async (email: string, password: string) => {
    const res = await platformApi.login({ email, password });
    setPlatformToken(res.access_token);
    setPlatformAdmin(res.admin);
    setTokenState(res.access_token);
    setAdminState(res.admin);
  }, []);

  const value = useMemo<PlatformAuthState>(
    () => ({ token, admin, login, logout }),
    [token, admin, login, logout],
  );

  return (
    <PlatformAuthContext.Provider value={value}>{children}</PlatformAuthContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function usePlatformAuth(): PlatformAuthState {
  const ctx = useContext(PlatformAuthContext);
  if (!ctx) {
    throw new Error('usePlatformAuth debe usarse dentro de <PlatformAuthProvider>');
  }
  return ctx;
}
