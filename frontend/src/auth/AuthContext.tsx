import {
  createContext,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import {
  api,
  clearToken,
  getToken,
  setToken,
  setUnauthorizedHandler,
  ApiError,
} from '@/api/client';
import type { Role, UserOut } from '@/api/types';

// El JWT (C4) lleva org_id, role y sucursal_ids. Decodificamos el payload
// solo para conocer el alcance (sucursal_ids) en la UI; la verdad la impone el backend.
interface JwtClaims {
  sub?: string;
  org_id?: string;
  role?: Role;
  sucursal_ids?: string[];
  exp?: number;
}

function decodeJwt(token: string): JwtClaims | null {
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
    return JSON.parse(json) as JwtClaims;
  } catch {
    return null;
  }
}

function isExpired(claims: JwtClaims | null): boolean {
  if (!claims?.exp) return false;
  return claims.exp * 1000 <= Date.now();
}

export interface AuthState {
  user: UserOut | null;
  role: Role | null;
  orgId: string | null;
  sucursalIds: string[];
  token: string | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  // Toggle visual de rol del prototipo (Administrador ⇄ Entrenador). No cambia permisos
  // reales del backend; solo adapta la vista localmente para demo/diseño.
  viewRole: Role | null;
  setViewRole: (role: Role) => void;
}

// eslint-disable-next-line react-refresh/only-export-components
export const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(() => {
    const t = getToken();
    if (t && isExpired(decodeJwt(t))) {
      clearToken();
      return null;
    }
    return t;
  });
  const [user, setUser] = useState<UserOut | null>(null);
  const [viewRole, setViewRoleState] = useState<Role | null>(null);
  const [loading, setLoading] = useState<boolean>(!!token);

  const claims = useMemo(() => (token ? decodeJwt(token) : null), [token]);

  const logout = useCallback(() => {
    clearToken();
    setTokenState(null);
    setUser(null);
    setViewRoleState(null);
  }, []);

  // Reaccionar a 401 global desde el cliente API.
  useEffect(() => {
    setUnauthorizedHandler(() => logout());
    return () => setUnauthorizedHandler(null);
  }, [logout]);

  // Hidratar el usuario al cargar si hay token persistido.
  useEffect(() => {
    if (!token) {
      setLoading(false);
      return;
    }
    let active = true;
    const controller = new AbortController();
    setLoading(true);
    api
      .me(controller.signal)
      .then((u) => {
        if (!active) return;
        setUser(u);
        setViewRoleState((prev) => prev ?? u.role);
      })
      .catch((err) => {
        if (!active) return;
        // 401 ya limpia token vía handler; otros errores no deslogean.
        if (err instanceof ApiError && err.isUnauthorized) {
          logout();
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [token, logout]);

  const login = useCallback(async (email: string, password: string) => {
    const res = await api.login({ email, password });
    setToken(res.access_token);
    setTokenState(res.access_token);
    setUser(res.user);
    setViewRoleState(res.user.role);
  }, []);

  const setViewRole = useCallback((role: Role) => setViewRoleState(role), []);

  const value: AuthState = useMemo(
    () => ({
      user,
      role: user?.role ?? null,
      orgId: user?.org_id ?? claims?.org_id ?? null,
      sucursalIds: claims?.sucursal_ids ?? [],
      token,
      loading,
      login,
      logout,
      viewRole: viewRole ?? user?.role ?? null,
      setViewRole,
    }),
    [user, claims, token, loading, login, logout, viewRole, setViewRole],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
