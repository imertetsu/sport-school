// Wrapper fetch tipado contra la API de LATINOSPORT (C5).
// - Base: import.meta.env.VITE_API_URL + /api/v1
// - Agrega Authorization: Bearer desde el token guardado
// - Maneja 401 (token inválido/expirado) y 422 (validación)

import { API_BASE_URL, API_PREFIX, TOKEN_STORAGE_KEY } from '@/config';
import type {
  AlumnoCreate,
  AlumnoCreated,
  AlumnoDetail,
  AlumnosListResponse,
  AsistenciaReporte,
  AvisoCreate,
  AvisoCreated,
  AvisosPage,
  Categoria,
  CategoriaAsistencia,
  CuotasListResponse,
  EgresoCreate,
  EgresoCreated,
  EgresoResumenItem,
  EgresosFilters,
  EgresosPage,
  EstadoCuota,
  GenerarCuotasResponse,
  GuardarBody,
  HorarioCreate,
  HorarioCreated,
  HorarioOut,
  IngresosReporte,
  LoginRequest,
  PagoOut,
  PanelCobranza,
  QrResponse,
  RegistrarPagoEfectivoBody,
  RegistrarPagoQrBody,
  RosterOut,
  SemanaOut,
  SesionesListResponse,
  AprobarBody,
  EstadoSolicitud,
  RechazarBody,
  SolicitudAlumnoCreado,
  SolicitudCreate,
  SolicitudOut,
  SolicitudesPage,
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
  // 2º arg = base: si API_BASE_URL está vacío (mismo origen), resuelve la ruta
  // relativa contra el origen actual; si es absoluto, el base se ignora.
  const url = new URL(`${API_BASE_URL}${API_PREFIX}${path}`, window.location.origin);
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

  // ---- Cobranza (C4) ----
  panelCobranza(signal?: AbortSignal): Promise<PanelCobranza> {
    return request<PanelCobranza>('/cobranza/panel', { signal });
  },
  cuotas(
    params: {
      estado?: EstadoCuota;
      alumno_id?: string;
      sucursal_id?: string;
      page?: number;
      page_size?: number;
    } = {},
    signal?: AbortSignal,
  ): Promise<CuotasListResponse> {
    return request<CuotasListResponse>('/cobranza/cuotas', { query: params, signal });
  },
  generarCuotas(signal?: AbortSignal): Promise<GenerarCuotasResponse> {
    return request<GenerarCuotasResponse>('/cobranza/generar', { method: 'POST', signal });
  },
  pagoEfectivo(body: RegistrarPagoEfectivoBody, signal?: AbortSignal): Promise<PagoOut> {
    return request<PagoOut>('/cobranza/pagos/efectivo', {
      method: 'POST',
      body,
      signal,
    });
  },
  pagoQr(body: RegistrarPagoQrBody, signal?: AbortSignal): Promise<QrResponse> {
    return request<QrResponse>('/cobranza/pagos/qr', { method: 'POST', body, signal });
  },
  pago(id: string, signal?: AbortSignal): Promise<PagoOut> {
    return request<PagoOut>(`/cobranza/pagos/${id}`, { signal });
  },
  // Sandbox: dispara el flujo del webhook para demostrar el QR en vivo (C3).
  simularConfirmacionQr(id: string, signal?: AbortSignal): Promise<PagoOut> {
    return request<PagoOut>(`/cobranza/pagos/qr/${id}/simular-confirmacion`, {
      method: 'POST',
      signal,
    });
  },

  // ---- Asistencia (C2) ----
  // GET /asistencia/categorias -> categorías visibles por rol.
  asistenciaCategorias(signal?: AbortSignal): Promise<CategoriaAsistencia[]> {
    return request<CategoriaAsistencia[]>('/asistencia/categorias', { signal });
  },
  // GET /asistencia/roster?categoria_id=&fecha= -> roster (get-or-create lógico).
  asistenciaRoster(
    categoriaId: string,
    fecha: string,
    signal?: AbortSignal,
  ): Promise<RosterOut> {
    return request<RosterOut>('/asistencia/roster', {
      query: { categoria_id: categoriaId, fecha },
      signal,
    });
  },
  // POST /asistencia/guardar -> idempotente; devuelve el roster guardado.
  asistenciaGuardar(body: GuardarBody, signal?: AbortSignal): Promise<RosterOut> {
    return request<RosterOut>('/asistencia/guardar', { method: 'POST', body, signal });
  },
  // GET /asistencia/sesiones?categoria_id=&page=&page_size= -> historial.
  asistenciaSesiones(
    categoriaId: string,
    params: { page?: number; page_size?: number } = {},
    signal?: AbortSignal,
  ): Promise<SesionesListResponse> {
    return request<SesionesListResponse>('/asistencia/sesiones', {
      query: { categoria_id: categoriaId, ...params },
      signal,
    });
  },

  // ---- Egresos (SOLO ADMIN; el backend responde 403 a ENTRENADOR) ----
  // GET /egresos?sucursal_id=&categoria=&desde=&hasta=&page=&page_size=
  // -> página + total_monto del filtro.
  listEgresos(filtros: EgresosFilters = {}, signal?: AbortSignal): Promise<EgresosPage> {
    return request<EgresosPage>('/egresos', { query: { ...filtros }, signal });
  },
  // POST /egresos -> crea el egreso (registrado_por lo fija el token) y lo devuelve.
  createEgreso(body: EgresoCreate, signal?: AbortSignal): Promise<EgresoCreated> {
    return request<EgresoCreated>('/egresos', { method: 'POST', body, signal });
  },
  // GET /egresos/resumen?desde=&hasta= -> totales agrupados por categoría.
  resumenEgresos(
    params: { desde?: string; hasta?: string } = {},
    signal?: AbortSignal,
  ): Promise<EgresoResumenItem[]> {
    return request<EgresoResumenItem[]>('/egresos/resumen', { query: params, signal });
  },
  // ---- Reportes (C1) — solo ADMIN ----
  // GET /reportes/ingresos?anio=YYYY -> 12 meses + total del año.
  reportesIngresos(anio?: number, signal?: AbortSignal): Promise<IngresosReporte> {
    return request<IngresosReporte>('/reportes/ingresos', {
      query: { anio },
      signal,
    });
  },
  // ---- Muro de avisos (C2) ----
  // GET /avisos?incluir_expirados=&page=&page_size= -> feed scoped por rol.
  // ADMIN ve todos los activos (los vencidos solo si incluir_expirados=true);
  // ENTRENADOR ve los activos no vencidos que le aplican. Orden publicado_en desc.
  avisos(
    params: { incluirExpirados?: boolean; page?: number; page_size?: number } = {},
    signal?: AbortSignal,
  ): Promise<AvisosPage> {
    return request<AvisosPage>('/avisos', {
      query: {
        incluir_expirados: params.incluirExpirados ? 'true' : undefined,
        page: params.page,
        page_size: params.page_size,
      },
      signal,
    });
  },
  // POST /avisos (ADMIN) -> crea el aviso (creado_por lo fija el token) y lo devuelve.
  crearAviso(body: AvisoCreate, signal?: AbortSignal): Promise<AvisoCreated> {
    return request<AvisoCreated>('/avisos', { method: 'POST', body, signal });
  },
  // PUT /avisos/{id} (ADMIN) -> edita el aviso (misma validación de invariante).
  actualizarAviso(id: string, body: AvisoCreate, signal?: AbortSignal): Promise<AvisoCreated> {
    return request<AvisoCreated>(`/avisos/${id}`, { method: 'PUT', body, signal });
  },
  // DELETE /avisos/{id} (ADMIN) -> soft-delete (activo=false), responde 204.
  eliminarAviso(id: string, signal?: AbortSignal): Promise<void> {
    return request<void>(`/avisos/${id}`, { method: 'DELETE', signal });
  },

  // ---- Horarios / Programación de clases (C2) ----
  // GET /horarios?categoria_id=&sucursal_id= -> lista scoped por rol.
  // ADMIN: todos los activos de la org; ENTRENADOR: solo los de sus sucursales.
  horarios(
    params: { categoriaId?: string; sucursalId?: string } = {},
    signal?: AbortSignal,
  ): Promise<HorarioOut[]> {
    return request<HorarioOut[]>('/horarios', {
      query: { categoria_id: params.categoriaId, sucursal_id: params.sucursalId },
      signal,
    });
  },
  // GET /horarios/semana?sucursal_id=&categoria_id= -> rejilla semanal (7 días, 0..6).
  horariosSemana(
    params: { sucursalId?: string; categoriaId?: string } = {},
    signal?: AbortSignal,
  ): Promise<SemanaOut> {
    return request<SemanaOut>('/horarios/semana', {
      query: { sucursal_id: params.sucursalId, categoria_id: params.categoriaId },
      signal,
    });
  },
  // POST /horarios (ADMIN) -> crea el horario y lo devuelve. Valida hora_fin>hora_inicio
  // (422) y unicidad (409); el cliente refleja esos errores.
  crearHorario(body: HorarioCreate, signal?: AbortSignal): Promise<HorarioCreated> {
    return request<HorarioCreated>('/horarios', { method: 'POST', body, signal });
  },
  // PUT /horarios/{id} (ADMIN) -> edita el horario (misma validación) y lo devuelve.
  actualizarHorario(
    id: string,
    body: HorarioCreate,
    signal?: AbortSignal,
  ): Promise<HorarioCreated> {
    return request<HorarioCreated>(`/horarios/${id}`, { method: 'PUT', body, signal });
  },
  // DELETE /horarios/{id} (ADMIN) -> soft-delete (activo=false), responde 204.
  eliminarHorario(id: string, signal?: AbortSignal): Promise<void> {
    return request<void>(`/horarios/${id}`, { method: 'DELETE', signal });
  },

  // ---- Auto-registro / Solicitudes (C2/C3) — TODO autenticado, NADA público ----
  // GET /solicitudes?estado=&page=&page_size= -> cola scoped por rol en el backend.
  // ADMIN ve todas las de la org; ENTRENADOR solo las de sus sucursales.
  solicitudes(
    params: { estado?: EstadoSolicitud; page?: number; page_size?: number } = {},
    signal?: AbortSignal,
  ): Promise<SolicitudesPage> {
    return request<SolicitudesPage>('/solicitudes', { query: params, signal });
  },
  // GET /solicitudes/{id} -> SolicitudOut.
  solicitud(id: string, signal?: AbortSignal): Promise<SolicitudOut> {
    return request<SolicitudOut>(`/solicitudes/${id}`, { signal });
  },
  // POST /solicitudes (ADMIN o ENTRENADOR) -> crea la solicitud PENDIENTE y la devuelve.
  // 422 si falta consentimiento/datos del tutor; 403 si entrenador sugiere sucursal fuera de su alcance.
  crearSolicitud(body: SolicitudCreate, signal?: AbortSignal): Promise<SolicitudOut> {
    return request<SolicitudOut>('/solicitudes', { method: 'POST', body, signal });
  },
  // POST /solicitudes/{id}/aprobar (ADMIN) -> crea el alumno real (reusa Alumnos) y lo devuelve.
  // Marca APROBADA y set alumno_id. 409 si ya resuelta; 403 si no es ADMIN.
  aprobarSolicitud(
    id: string,
    body: AprobarBody,
    signal?: AbortSignal,
  ): Promise<SolicitudAlumnoCreado> {
    return request<SolicitudAlumnoCreado>(`/solicitudes/${id}/aprobar`, {
      method: 'POST',
      body,
      signal,
    });
  },
  // POST /solicitudes/{id}/rechazar (ADMIN) -> RECHAZADA con motivo; devuelve la solicitud.
  // 409 si ya resuelta; 403 si no es ADMIN.
  rechazarSolicitud(
    id: string,
    motivo: string,
    signal?: AbortSignal,
  ): Promise<SolicitudOut> {
    const body: RechazarBody = { motivo };
    return request<SolicitudOut>(`/solicitudes/${id}/rechazar`, {
      method: 'POST',
      body,
      signal,
    });
  },

  // GET /reportes/asistencia?desde=&hasta=&sucursal_id=&categoria_id=
  // -> % global + desglose por categoría.
  reportesAsistencia(
    params: {
      desde?: string;
      hasta?: string;
      sucursalId?: string;
      categoriaId?: string;
    } = {},
    signal?: AbortSignal,
  ): Promise<AsistenciaReporte> {
    return request<AsistenciaReporte>('/reportes/asistencia', {
      query: {
        desde: params.desde,
        hasta: params.hasta,
        sucursal_id: params.sucursalId,
        categoria_id: params.categoriaId,
      },
      signal,
    });
  },
};

// URL absoluta del comprobante PDF (descarga binaria; no pasa por request<T>()).
// GET /cobranza/comprobantes/{pago_id}.pdf -> application/pdf.
export function comprobantePdfUrl(pagoId: string): string {
  return `${API_BASE_URL}${API_PREFIX}/cobranza/comprobantes/${pagoId}.pdf`;
}
