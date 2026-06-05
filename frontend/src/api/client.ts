// Wrapper fetch tipado contra la API de CanteraSport (C5).
// - Base: import.meta.env.VITE_API_URL + /api/v1
// - Agrega Authorization: Bearer desde el token guardado
// - Maneja 401 (token inválido/expirado) y 422 (validación)

import { API_BASE_URL, API_PREFIX, TOKEN_STORAGE_KEY } from '@/config';
import type {
  AlumnoCreate,
  AlumnoCreated,
  AlumnoDetail,
  AlumnosListResponse,
  Categoria,
  LoginRequest,
  Sucursal,
  TokenOut,
  UserOut,
} from './types';

// ---- Token storage ----
export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_STORAGE_KEY, token);
  } catch {
    /* almacenamiento no disponible: la sesión vivirá solo en memoria */
  }
}

export function clearToken(): void {
  try {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    /* noop */
  }
}

// ---- Error de API tipado ----
export interface FieldError {
  loc: (string | number)[];
  msg: string;
  type?: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;
  readonly fieldErrors: FieldError[];

  constructor(status: number, message: string, detail: unknown, fieldErrors: FieldError[] = []) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.fieldErrors = fieldErrors;
  }

  get isUnauthorized(): boolean {
    return this.status === 401;
  }

  get isForbidden(): boolean {
    return this.status === 403;
  }

  get isValidation(): boolean {
    return this.status === 422;
  }
}

// Callback que la capa de auth registra para reaccionar a un 401 global.
let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  query?: Record<string, string | number | undefined | null>;
  signal?: AbortSignal;
  // Endpoints públicos (login) no requieren ni envían token.
  auth?: boolean;
}

function buildUrl(path: string, query?: RequestOptions['query']): string {
  const url = new URL(`${API_BASE_URL}${API_PREFIX}${path}`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== '') {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url.toString();
}

function parseFieldErrors(detail: unknown): FieldError[] {
  // FastAPI 422: { detail: [{ loc, msg, type }] }
  if (Array.isArray(detail)) {
    return detail.filter(
      (e): e is FieldError =>
        typeof e === 'object' && e !== null && 'msg' in e && 'loc' in e,
    );
  }
  return [];
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, query, signal, auth = true } = options;

  const headers: Record<string, string> = {
    Accept: 'application/json',
  };
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
  }
  if (auth) {
    const token = getToken();
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
  }

  const res = await fetch(buildUrl(path, query), {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  });

  if (res.status === 401) {
    clearToken();
    if (auth && onUnauthorized) onUnauthorized();
  }

  if (res.status === 204) {
    return undefined as T;
  }

  let payload: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }

  if (!res.ok) {
    const detail =
      payload && typeof payload === 'object' && 'detail' in payload
        ? (payload as { detail: unknown }).detail
        : payload;
    const fieldErrors = parseFieldErrors(detail);
    const message =
      typeof detail === 'string'
        ? detail
        : fieldErrors[0]?.msg ?? `Error ${res.status}`;
    throw new ApiError(res.status, message, detail, fieldErrors);
  }

  return payload as T;
}

// ---- Endpoints tipados (C4 / C5) ----
export const api = {
  // C4
  login(data: LoginRequest, signal?: AbortSignal): Promise<TokenOut> {
    return request<TokenOut>('/auth/login', {
      method: 'POST',
      body: data,
      auth: false,
      signal,
    });
  },
  me(signal?: AbortSignal): Promise<UserOut> {
    return request<UserOut>('/auth/me', { signal });
  },

  // C5
  sucursales(signal?: AbortSignal): Promise<Sucursal[]> {
    return request<Sucursal[]>('/sucursales', { signal });
  },
  categorias(sucursalId?: string, signal?: AbortSignal): Promise<Categoria[]> {
    return request<Categoria[]>('/categorias', {
      query: { sucursal_id: sucursalId },
      signal,
    });
  },
  alumnos(
    params: { q?: string; sucursal_id?: string; page?: number; page_size?: number } = {},
    signal?: AbortSignal,
  ): Promise<AlumnosListResponse> {
    return request<AlumnosListResponse>('/alumnos', { query: params, signal });
  },
  alumno(id: string, signal?: AbortSignal): Promise<AlumnoDetail> {
    return request<AlumnoDetail>(`/alumnos/${id}`, { signal });
  },
  crearAlumno(data: AlumnoCreate, signal?: AbortSignal): Promise<AlumnoCreated> {
    return request<AlumnoCreated>('/alumnos', { method: 'POST', body: data, signal });
  },
};
