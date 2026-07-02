// Wrapper fetch tipado contra la API de LATINOSPORT (C5).
// - Base: import.meta.env.VITE_API_URL + /api/v1
// - Agrega Authorization: Bearer desde el token guardado
// - Maneja 401 (token inválido/expirado) y 422 (validación)

import { API_BASE_URL, API_PREFIX, ORG_STORAGE_KEY, TOKEN_STORAGE_KEY } from '@/config';
import type {
  DeportistaCreate,
  DeportistaCreated,
  DeportistaDetail,
  DeportistasListResponse,
  DeportistaUpdate,
  MiEscuela,
  TokenOrg,
  AsistenciaReporte,
  AvisoCreate,
  AvisoCreated,
  AvisosPage,
  Categoria,
  CategoriaAsistencia,
  CategoriaCreate,
  CategoriaUpdate,
  ComprobanteCuotaElegible,
  ComprobantesPendientesPage,
  ConfirmarComprobanteBody,
  EstadoComprobante,
  CuotasListResponse,
  DisciplinaRef,
  EgresoCreate,
  EgresoCreated,
  EgresoResumenItem,
  EgresosFilters,
  EgresosPage,
  EntrenadorCreate,
  EntrenadorOut,
  EntrenadorUpdate,
  EstadoCuota,
  GenerarCuotasResponse,
  GuardarBody,
  HorarioCreate,
  HorarioCreated,
  HorarioOut,
  IngresosReporte,
  LoginRequest,
  AnularPagoBody,
  PagoAnuladoOut,
  PagoOut,
  PagosListResponse,
  PanelCobranza,
  PreviewNotificacionIn,
  PreviewNotificacionOut,
  QrCobroMeta,
  QrResponse,
  RechazarComprobanteOut,
  RecordatorioDeudoresResult,
  RecordatorioOut,
  RegistrarPagoEfectivoBody,
  RegistrarPagoQrBody,
  RosterOut,
  SemanaOut,
  SesionesListResponse,
  AprobarBody,
  EstadoSolicitud,
  RechazarBody,
  SolicitudDeportistaCreado,
  SolicitudCreate,
  SolicitudOut,
  SolicitudesPage,
  Sucursal,
  SucursalCreate,
  SucursalUpdate,
  TokenOut,
  TutorByCi,
  UserOut,
  WhatsAppDesvincularOut,
  WhatsAppEstadoOut,
  WhatsAppQrOut,
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

// ---- Org embebida (epic escuela-y-bajas, C1): {id,nombre,color} ----
// La org viaja en el login y la persistimos junto al token para que el TopBar
// pinte nombre+monograma tras recargar sin una segunda llamada. El editor de
// /mi-escuela la refresca (setOrg) para reflejar el cambio al instante.
export function getOrg(): TokenOrg | null {
  try {
    const raw = localStorage.getItem(ORG_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as TokenOrg) : null;
  } catch {
    return null;
  }
}

export function setOrg(org: TokenOrg): void {
  try {
    localStorage.setItem(ORG_STORAGE_KEY, JSON.stringify(org));
  } catch {
    /* almacenamiento no disponible: la org vivirá solo en memoria */
  }
}

export function clearOrg(): void {
  try {
    localStorage.removeItem(ORG_STORAGE_KEY);
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

  get isConflict(): boolean {
    return this.status === 409;
  }

  get isNotFound(): boolean {
    return this.status === 404;
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

// Variante para subir multipart/form-data (p. ej. imagen del QR de cobro).
// NO fija Content-Type a mano: el navegador lo pone con el boundary correcto.
// Reusa el mismo manejo de 401/422/error que request<T>.
async function requestMultipart<T>(
  path: string,
  form: FormData,
  options: { method?: string; signal?: AbortSignal } = {},
): Promise<T> {
  const { method = 'POST', signal } = options;

  const headers: Record<string, string> = { Accept: 'application/json' };
  const token = getToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const res = await fetch(buildUrl(path), {
    method,
    headers,
    body: form,
    signal,
  });

  if (res.status === 401) {
    clearToken();
    if (onUnauthorized) onUnauthorized();
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
      typeof detail === 'string' ? detail : fieldErrors[0]?.msg ?? `Error ${res.status}`;
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
  // GET /catalogo/disciplinas?solo_activas=true -> catálogo global de disciplinas
  // (DisciplinaRef[], solo {id,nombre}; cero datos de tenant). Pobla selects de
  // escuela (categoría en S2; persona en S3/S4). Visible a ADMIN y ENTRENADOR.
  disciplinasCatalogo(signal?: AbortSignal): Promise<DisciplinaRef[]> {
    return request<DisciplinaRef[]>('/catalogo/disciplinas', {
      query: { solo_activas: 'true' },
      signal,
    });
  },
  // GET /deportistas?q=&sucursal_id=&solo_activos=&page=&page_size= -> lista scoped
  // por rol/RLS. solo_activos (epic escuela-y-bajas, C4): ESPEJO del de
  // /entrenadores; por defecto (omitido) muestra TODOS; true filtra a los activos.
  deportistas(
    params: {
      q?: string;
      sucursal_id?: string;
      solo_activos?: boolean;
      page?: number;
      page_size?: number;
    } = {},
    signal?: AbortSignal,
  ): Promise<DeportistasListResponse> {
    const { solo_activos, ...rest } = params;
    return request<DeportistasListResponse>('/deportistas', {
      query: { ...rest, solo_activos: solo_activos ? 'true' : undefined },
      signal,
    });
  },
  deportista(id: string, signal?: AbortSignal): Promise<DeportistaDetail> {
    return request<DeportistaDetail>(`/deportistas/${id}`, { signal });
  },
  crearDeportista(data: DeportistaCreate, signal?: AbortSignal): Promise<DeportistaCreated> {
    return request<DeportistaCreated>('/deportistas', { method: 'POST', body: data, signal });
  },
  // PUT /deportistas/{id} (epic escuela-y-bajas, C3) -> edición completa (datos +
  // tutores + ficha médica) y devuelve el detalle actualizado. `tutores` se
  // reconcilia por id; el backend valida el invariante de menores (>=1 tutor, no
  // quitar al del consentimiento) -> 422. Campos omitidos NO se tocan.
  actualizarDeportista(
    id: string,
    data: DeportistaUpdate,
    signal?: AbortSignal,
  ): Promise<DeportistaDetail> {
    return request<DeportistaDetail>(`/deportistas/${id}`, { method: 'PUT', body: data, signal });
  },
  // POST /deportistas/{id}/baja (ADMIN; epic escuela-y-bajas, C4) -> soft-delete
  // (activo=false, NUNCA borrado físico). Devuelve el detalle actualizado.
  darBajaDeportista(id: string, signal?: AbortSignal): Promise<DeportistaDetail> {
    return request<DeportistaDetail>(`/deportistas/${id}/baja`, { method: 'POST', signal });
  },
  // POST /deportistas/{id}/reactivar (ADMIN; epic escuela-y-bajas, C4) -> restaura
  // (activo=true). Devuelve el detalle actualizado.
  reactivarDeportista(id: string, signal?: AbortSignal): Promise<DeportistaDetail> {
    return request<DeportistaDetail>(`/deportistas/${id}/reactivar`, { method: 'POST', signal });
  },
  // GET /deportistas/por-ci/{ci} -> detalle del deportista (200) o 404 si no existe
  // en la org. Recuperar-por-CI (S3): al ingresar/escanear el CI, precarga el
  // registro anterior y evita duplicados (el backend además da 409 en el alta).
  deportistaPorCi(ci: string, signal?: AbortSignal): Promise<DeportistaDetail> {
    return request<DeportistaDetail>(`/deportistas/por-ci/${encodeURIComponent(ci)}`, { signal });
  },
  // GET /tutores/por-ci/{ci} -> tutor (200) o 404 si no existe en la org.
  // Recuperar-por-CI del tutor (S3): el CI del tutor es OPCIONAL; si existe,
  // recupera el tutor para reutilizarlo y permitir actualizar su teléfono. Devuelve
  // solo los datos propios del tutor (sin parentesco/responsable_pago del vínculo).
  tutorPorCi(ci: string, signal?: AbortSignal): Promise<TutorByCi> {
    return request<TutorByCi>(`/tutores/por-ci/${encodeURIComponent(ci)}`, { signal });
  },

  // ---- Cobranza (C4) ----
  panelCobranza(signal?: AbortSignal): Promise<PanelCobranza> {
    return request<PanelCobranza>('/cobranza/panel', { signal });
  },
  cuotas(
    params: {
      estado?: EstadoCuota;
      deportista_id?: string;
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
  // POST /cobranza/cuotas/{cuota_id}/recordatorio (ADMIN) -> envía el recordatorio
  // de cobro por WhatsApp. forzar=true reenvía uno ya enviado (default false).
  // El backend impone idempotencia y los toggles de notificaciones (RNF-07).
  enviarRecordatorio(
    cuotaId: string,
    forzar = false,
    signal?: AbortSignal,
  ): Promise<RecordatorioOut> {
    return request<RecordatorioOut>(`/cobranza/cuotas/${cuotaId}/recordatorio`, {
      method: 'POST',
      body: { forzar },
      signal,
    });
  },
  // ---- Pagos (epic anular-pago, C4) — SOLO ADMIN (el backend impone require_role) ----
  // GET /cobranza/pagos?page=&page_size= -> lista paginada scoped por RLS, orden
  // created_at DESC. Punto de acceso a "Anular": cada item trae `anulable`
  // (efectivo+CONFIRMADO) y, si ya anulado, motivo_anulacion/anulado_en.
  listarPagos(page = 1, pageSize = 20, signal?: AbortSignal): Promise<PagosListResponse> {
    return request<PagosListResponse>('/cobranza/pagos', {
      query: { page, page_size: pageSize },
      signal,
    });
  },
  // GET /cobranza/pagos?deportista_id=... -> historial de pagos de UN deportista
  // (mismo item + las cuotas que cubrió, con su vencimiento). Para el perfil.
  pagosDeportista(
    deportistaId: string,
    page = 1,
    pageSize = 50,
    signal?: AbortSignal,
  ): Promise<PagosListResponse> {
    return request<PagosListResponse>('/cobranza/pagos', {
      query: { deportista_id: deportistaId, page, page_size: pageSize },
      signal,
    });
  },
  // GET /cobranza/comprobantes/{id}.pdf (requiere Bearer) -> descarga el recibo PDF
  // como blob y devuelve un objectURL para abrir/imprimir. El caller debe llamar
  // URL.revokeObjectURL cuando termine. Se usa fetch directo (no `request`) porque la
  // respuesta es binaria, no JSON.
  async comprobantePdfUrl(pagoId: string, signal?: AbortSignal): Promise<string> {
    const url = new URL(
      `${API_BASE_URL}${API_PREFIX}/cobranza/comprobantes/${pagoId}.pdf`,
      window.location.origin,
    );
    const token = getToken();
    const res = await fetch(url.toString(), {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      signal,
    });
    if (!res.ok) {
      throw new ApiError(res.status, 'No se pudo cargar el recibo', null);
    }
    const blob = await res.blob();
    return URL.createObjectURL(blob);
  },
  // POST /cobranza/pagos/{id}/anular {motivo} -> reversa CON rastro (estado ANULADO
  // + motivo/quién/cuándo). Solo efectivo CONFIRMADO. Mapeo de errores del backend:
  // 404 inexistente/otra org, 422 no anulable (QR/estado), 409 crédito ya consumido,
  // 422 motivo vacío. Anular un pago ya ANULADO es idempotente (200).
  anularPago(pagoId: string, motivo: string, signal?: AbortSignal): Promise<PagoAnuladoOut> {
    const body: AnularPagoBody = { motivo };
    return request<PagoAnuladoOut>(`/cobranza/pagos/${pagoId}/anular`, {
      method: 'POST',
      body,
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
  // POST /avisos/notificacion/preview (ADMIN) -> cuenta destinatarios SIN enviar
  // (avisos-whatsapp C2). Valida la misma invariante alcance↔ids que el alta
  // (422 si no cumple). Solo se usa antes de publicar cuando hay algún grupo
  // marcado, para confirmar el conteo. No inserta ni envía nada.
  previewNotificacionAviso(
    body: PreviewNotificacionIn,
    signal?: AbortSignal,
  ): Promise<PreviewNotificacionOut> {
    return request<PreviewNotificacionOut>('/avisos/notificacion/preview', {
      method: 'POST',
      body,
      signal,
    });
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
  // POST /solicitudes/{id}/aprobar (ADMIN) -> crea el deportista real (reusa Deportistas) y lo devuelve.
  // Marca APROBADA y set deportista_id. 409 si ya resuelta; 403 si no es ADMIN.
  aprobarSolicitud(
    id: string,
    body: AprobarBody,
    signal?: AbortSignal,
  ): Promise<SolicitudDeportistaCreado> {
    return request<SolicitudDeportistaCreado>(`/solicitudes/${id}/aprobar`, {
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

  // ---- Entrenadores (Epic B) ----
  // GET /entrenadores?solo_activos= -> lista scoped por org (RLS). Listar lo
  // puede cualquier rol (pobla selectores como el de Horarios). Orden por nombres.
  listEntrenadores(soloActivos?: boolean, signal?: AbortSignal): Promise<EntrenadorOut[]> {
    return request<EntrenadorOut[]>('/entrenadores', {
      query: { solo_activos: soloActivos ? 'true' : undefined },
      signal,
    });
  },
  // POST /entrenadores (ADMIN) -> crea usuario(ENTRENADOR) + entrenador en una
  // transacción y lo devuelve (201). Email ya en uso -> 409; el cliente lo refleja.
  createEntrenador(payload: EntrenadorCreate, signal?: AbortSignal): Promise<EntrenadorOut> {
    return request<EntrenadorOut>('/entrenadores', { method: 'POST', body: payload, signal });
  },
  // PUT /entrenadores/{id} (ADMIN) -> edita nombres/especialidad/disciplinas y
  // activo (+ password si viene). activo=false da de baja; activo=true reactiva.
  // id inexistente -> 404. Devuelve el entrenador actualizado.
  updateEntrenador(
    id: string,
    payload: EntrenadorUpdate,
    signal?: AbortSignal,
  ): Promise<EntrenadorOut> {
    return request<EntrenadorOut>(`/entrenadores/${id}`, { method: 'PUT', body: payload, signal });
  },
  // POST /entrenadores/{id}/recordatorio-deudores (ADMIN) -> dispara el digest de
  // deudores por WhatsApp para TODAS las sucursales asignadas (origen MANUAL),
  // sin body. Devuelve el resumen por sucursal (nº deudores, monto, estado).
  // 404 si el entrenador no existe. Entrenador sin teléfono -> 200 con todas las
  // sucursales en FALLIDO (estado de negocio). El backend impone idempotencia.
  enviarRecordatorioDeudores(
    id: string,
    signal?: AbortSignal,
  ): Promise<RecordatorioDeudoresResult> {
    return request<RecordatorioDeudoresResult>(
      `/entrenadores/${id}/recordatorio-deudores`,
      { method: 'POST', signal },
    );
  },
  // ---- Sucursales / Categorías — CRUD (SOLO ADMIN; el backend da 403 a ENTRENADOR) ----
  // El GET de sucursales/categorías ya está arriba (sucursales/categorias).
  // POST /sucursales (ADMIN) -> SucursalOut (201).
  crearSucursal(body: SucursalCreate, signal?: AbortSignal): Promise<Sucursal> {
    return request<Sucursal>('/sucursales', { method: 'POST', body, signal });
  },
  // PUT /sucursales/{id} (ADMIN) -> SucursalOut.
  actualizarSucursal(
    id: string,
    body: SucursalUpdate,
    signal?: AbortSignal,
  ): Promise<Sucursal> {
    return request<Sucursal>(`/sucursales/${id}`, { method: 'PUT', body, signal });
  },
  // DELETE /sucursales/{id} (ADMIN) -> 204. 409 (CONFLICT) si está en uso
  // (categorías/deportistas); el cliente refleja el mensaje del backend, sin cascada.
  eliminarSucursal(id: string, signal?: AbortSignal): Promise<void> {
    return request<void>(`/sucursales/${id}`, { method: 'DELETE', signal });
  },
  // POST /categorias (ADMIN) -> CategoriaOut (201).
  crearCategoria(body: CategoriaCreate, signal?: AbortSignal): Promise<Categoria> {
    return request<Categoria>('/categorias', { method: 'POST', body, signal });
  },
  // PUT /categorias/{id} (ADMIN) -> CategoriaOut (sucursal_id NO editable).
  actualizarCategoria(
    id: string,
    body: CategoriaUpdate,
    signal?: AbortSignal,
  ): Promise<Categoria> {
    return request<Categoria>(`/categorias/${id}`, { method: 'PUT', body, signal });
  },
  // DELETE /categorias/{id} (ADMIN) -> 204. 409 (CONFLICT) si está en uso
  // (deportistas/horarios/sesiones); el cliente refleja el mensaje del backend.
  eliminarCategoria(id: string, signal?: AbortSignal): Promise<void> {
    return request<void>(`/categorias/${id}`, { method: 'DELETE', signal });
  },

  // ---- Mi escuela (epic escuela-y-bajas, C2) — SOLO ADMIN (403 a ENTRENADOR) ----
  // organizacion NO tiene RLS: el endpoint scopea SIEMPRE a user.org_id server-side
  // e ignora cualquier id del cliente. GET y PUT comparten el shape { nombre, color }.
  // GET /mi-escuela -> { nombre, color } de la org del usuario.
  miEscuela(signal?: AbortSignal): Promise<MiEscuela> {
    return request<MiEscuela>('/mi-escuela', { signal });
  },
  // PUT /mi-escuela -> actualiza nombre + color del monograma y devuelve el recurso.
  actualizarMiEscuela(body: MiEscuela, signal?: AbortSignal): Promise<MiEscuela> {
    return request<MiEscuela>('/mi-escuela', { method: 'PUT', body, signal });
  },

  // ---- WhatsApp de la escuela (epic whatsapp-multitenant) — SOLO ADMIN ----
  // Un número por org, vinculado por QR. El backend scopea SIEMPRE a user.org_id
  // (el cliente NUNCA manda org_id) y es el ÚNICO que habla con el sidecar: el
  // browser nunca ve el X-Gateway-Token ni la URL del sidecar; el QR (data-url)
  // viaja browser<-backend<-sidecar.
  // GET /mi-escuela/whatsapp/estado -> estado reconciliado de la sesión.
  whatsappEstado(signal?: AbortSignal): Promise<WhatsAppEstadoOut> {
    return request<WhatsAppEstadoOut>('/mi-escuela/whatsapp/estado', { signal });
  },
  // POST /mi-escuela/whatsapp/vincular -> arranca el pairing (lazy en el sidecar)
  // y devuelve el QR (data-url) o, si ya estaba conectada, el número.
  whatsappVincular(signal?: AbortSignal): Promise<WhatsAppQrOut> {
    return request<WhatsAppQrOut>('/mi-escuela/whatsapp/vincular', {
      method: 'POST',
      signal,
    });
  },
  // GET /mi-escuela/whatsapp/qr -> polling del QR mientras PENDIENTE_QR (mismo
  // shape que vincular). qr:null => el sidecar aún no lo generó; reintentar.
  whatsappQr(signal?: AbortSignal): Promise<WhatsAppQrOut> {
    return request<WhatsAppQrOut>('/mi-escuela/whatsapp/qr', { signal });
  },
  // DELETE /mi-escuela/whatsapp -> desvincula (idempotente); estado DESVINCULADA.
  whatsappDesvincular(signal?: AbortSignal): Promise<WhatsAppDesvincularOut> {
    return request<WhatsAppDesvincularOut>('/mi-escuela/whatsapp', {
      method: 'DELETE',
      signal,
    });
  },

  // ---- QR de cobro (epic pagos-qr-comprobante, C6) — SOLO ADMIN ----
  // 1 fila por org. El backend scopea SIEMPRE al org del token. La imagen binaria
  // se sirve por URL FIRMADA HMAC stateless: el meta trae `imagen_url` (resuélvela
  // con resolveSignedUrl para el <img>). Renueva al recargar el meta.
  // GET /qr-cobro/meta -> {tiene_qr, mime|null, tamano_bytes|null, imagen_url|null}.
  qrCobroMeta(signal?: AbortSignal): Promise<QrCobroMeta> {
    return request<QrCobroMeta>('/qr-cobro/meta', { signal });
  },
  // POST /qr-cobro (multipart `file`, image/png|image/jpeg) -> metadata del QR.
  subirQrCobro(file: File, signal?: AbortSignal): Promise<QrCobroMeta> {
    const form = new FormData();
    form.append('file', file);
    return requestMultipart<QrCobroMeta>('/qr-cobro', form, { signal });
  },
  // DELETE /qr-cobro -> {tiene_qr:false}.
  eliminarQrCobro(signal?: AbortSignal): Promise<QrCobroMeta> {
    return request<QrCobroMeta>('/qr-cobro', { method: 'DELETE', signal });
  },

  // ---- Comprobantes por verificar (epic pagos-qr-comprobante, C6) — SOLO ADMIN ----
  // GET /comprobantes/pendientes?estado=&page=&page_size= -> cola pre-llena.
  comprobantesPendientes(
    params: { estado?: EstadoComprobante; page?: number; page_size?: number } = {},
    signal?: AbortSignal,
  ): Promise<ComprobantesPendientesPage> {
    return request<ComprobantesPendientesPage>('/comprobantes/pendientes', {
      query: params,
      signal,
    });
  },
  // GET /comprobantes/{id}/cuotas -> cuotas con saldo de la escuela (para asignar
  // un comprobante "sin identificar" o reasignar la cuota antes de confirmar).
  comprobanteCuotas(id: string, signal?: AbortSignal): Promise<ComprobanteCuotaElegible[]> {
    return request<ComprobanteCuotaElegible[]>(`/comprobantes/${id}/cuotas`, { signal });
  },
  // POST /comprobantes/{id}/confirmar {cuota_id, monto} -> PagoOut (reusa
  // registrar_pago_efectivo; marca el comprobante CONFIRMADO server-side).
  confirmarComprobante(
    id: string,
    body: ConfirmarComprobanteBody,
    signal?: AbortSignal,
  ): Promise<PagoOut> {
    return request<PagoOut>(`/comprobantes/${id}/confirmar`, {
      method: 'POST',
      body,
      signal,
    });
  },
  // POST /comprobantes/{id}/rechazar {motivo?} -> {id, estado:'RECHAZADO'}.
  rechazarComprobante(
    id: string,
    motivo?: string,
    signal?: AbortSignal,
  ): Promise<RechazarComprobanteOut> {
    return request<RechazarComprobanteOut>(`/comprobantes/${id}/rechazar`, {
      method: 'POST',
      body: { motivo },
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

// Resuelve una URL FIRMADA (QR de cobro / comprobante) que el backend puede servir
// como ruta relativa (p.ej. "/api/v1/qr-cobro/imagen?sig=…"). Si ya es absoluta
// (http/https) o no hay base configurada (mismo origen) la deja igual; si es una
// ruta relativa y hay base (dev, API en otro host), le antepone API_BASE_URL para
// que el <img> apunte a la API y no al origen de la SPA. La URL firmada ES el
// mecanismo de auth (HMAC stateless): no se le añade token ni header.
export function resolveSignedUrl(url: string): string {
  if (/^https?:\/\//i.test(url)) return url;
  if (!API_BASE_URL) return url;
  return `${API_BASE_URL}${url.startsWith('/') ? '' : '/'}${url}`;
}

// ============================================================
// Epic A: consola de PLATAFORMA (rol SUPERADMIN). Sesión/token SEPARADOS de la de
// escuela: el token de plataforma vive en su propia clave de storage y SOLO se
// manda a las rutas /plataforma/*. El cliente de escuela (request<T>) nunca lo usa
// y este cliente nunca manda el token de escuela. No se rompe el flujo existente.
// ============================================================

import {
  PLATFORM_TOKEN_STORAGE_KEY,
  PLATFORM_ADMIN_STORAGE_KEY,
} from '@/config';
import type {
  CrearEscuelaIn,
  CrearSuperAdminIn,
  Disciplina,
  DisciplinaCreate,
  DisciplinaUpdate,
  Escuela,
  EscuelaCreada,
  EscuelaEstadoOut,
  PlatformAdmin,
  PlatformLoginOut,
  SuperAdmin,
  SuperAdminActivoOut,
  SuperAdminCreado,
} from './types';

// ---- Storage del token/admin de plataforma (claves DISTINTAS de la de escuela) ----
export function getPlatformToken(): string | null {
  try {
    return localStorage.getItem(PLATFORM_TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setPlatformToken(token: string): void {
  try {
    localStorage.setItem(PLATFORM_TOKEN_STORAGE_KEY, token);
  } catch {
    /* almacenamiento no disponible: la sesión vivirá solo en memoria */
  }
}

export function clearPlatformToken(): void {
  try {
    localStorage.removeItem(PLATFORM_TOKEN_STORAGE_KEY);
  } catch {
    /* noop */
  }
}

export function getPlatformAdmin(): PlatformAdmin | null {
  try {
    const raw = localStorage.getItem(PLATFORM_ADMIN_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as PlatformAdmin) : null;
  } catch {
    return null;
  }
}

export function setPlatformAdmin(admin: PlatformAdmin): void {
  try {
    localStorage.setItem(PLATFORM_ADMIN_STORAGE_KEY, JSON.stringify(admin));
  } catch {
    /* noop */
  }
}

export function clearPlatformAdmin(): void {
  try {
    localStorage.removeItem(PLATFORM_ADMIN_STORAGE_KEY);
  } catch {
    /* noop */
  }
}

// Callback que la capa de auth de plataforma registra para reaccionar a un 401.
let onPlatformUnauthorized: (() => void) | null = null;
export function setPlatformUnauthorizedHandler(handler: (() => void) | null): void {
  onPlatformUnauthorized = handler;
}

// request<T> dedicado a /plataforma/*: manda el token de PLATAFORMA (no el de
// escuela). Reusa buildUrl/parseFieldErrors/ApiError del mismo módulo.
async function platformRequest<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { method = 'GET', body, query, signal, auth = true } = options;

  const headers: Record<string, string> = { Accept: 'application/json' };
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
  }
  if (auth) {
    const token = getPlatformToken();
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
  }

  const res = await fetch(buildUrl(`/plataforma${path}`, query), {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  });

  if (res.status === 401) {
    clearPlatformToken();
    clearPlatformAdmin();
    if (auth && onPlatformUnauthorized) onPlatformUnauthorized();
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
      typeof detail === 'string' ? detail : fieldErrors[0]?.msg ?? `Error ${res.status}`;
    throw new ApiError(res.status, message, detail, fieldErrors);
  }

  return payload as T;
}

// ---- Endpoints de plataforma (todos bajo /api/v1/plataforma) ----
export const platformApi = {
  // POST /plataforma/login (público dentro de la consola: no manda token).
  login(
    data: { email: string; password: string },
    signal?: AbortSignal,
  ): Promise<PlatformLoginOut> {
    return platformRequest<PlatformLoginOut>('/login', {
      method: 'POST',
      body: data,
      auth: false,
      signal,
    });
  },

  // GET /plataforma/escuelas -> lista de orgs con su estado.
  escuelas(signal?: AbortSignal): Promise<Escuela[]> {
    return platformRequest<Escuela[]>('/escuelas', { signal });
  },
  // POST /plataforma/escuelas -> 201 (org + primer admin). 409 si admin_email dup.
  crearEscuela(body: CrearEscuelaIn, signal?: AbortSignal): Promise<EscuelaCreada> {
    return platformRequest<EscuelaCreada>('/escuelas', { method: 'POST', body, signal });
  },
  // POST /plataforma/escuelas/{id}/suspender -> estado SUSPENDIDA (idempotente).
  suspenderEscuela(id: string, signal?: AbortSignal): Promise<EscuelaEstadoOut> {
    return platformRequest<EscuelaEstadoOut>(`/escuelas/${id}/suspender`, {
      method: 'POST',
      signal,
    });
  },
  // POST /plataforma/escuelas/{id}/reactivar -> estado ACTIVA (idempotente).
  reactivarEscuela(id: string, signal?: AbortSignal): Promise<EscuelaEstadoOut> {
    return platformRequest<EscuelaEstadoOut>(`/escuelas/${id}/reactivar`, {
      method: 'POST',
      signal,
    });
  },

  // GET /plataforma/admins -> lista de super admins (sin password_hash).
  admins(signal?: AbortSignal): Promise<SuperAdmin[]> {
    return platformRequest<SuperAdmin[]>('/admins', { signal });
  },
  // POST /plataforma/admins -> 201. 409 si email duplicado.
  crearAdmin(body: CrearSuperAdminIn, signal?: AbortSignal): Promise<SuperAdminCreado> {
    return platformRequest<SuperAdminCreado>('/admins', { method: 'POST', body, signal });
  },
  // POST /plataforma/admins/{id}/activar -> activo true (idempotente).
  activarAdmin(id: string, signal?: AbortSignal): Promise<SuperAdminActivoOut> {
    return platformRequest<SuperAdminActivoOut>(`/admins/${id}/activar`, {
      method: 'POST',
      signal,
    });
  },
  // POST /plataforma/admins/{id}/desactivar -> activo false. 409 si dejaría 0 activos.
  desactivarAdmin(id: string, signal?: AbortSignal): Promise<SuperAdminActivoOut> {
    return platformRequest<SuperAdminActivoOut>(`/admins/${id}/desactivar`, {
      method: 'POST',
      signal,
    });
  },

  // ---- Disciplinas (catálogo GLOBAL, S2). CRUD solo SUPERADMIN. ----
  // GET /plataforma/disciplinas -> todas (activas + inactivas), orden del backend.
  disciplinas(signal?: AbortSignal): Promise<Disciplina[]> {
    return platformRequest<Disciplina[]>('/disciplinas', { signal });
  },
  // POST /plataforma/disciplinas -> 201. 409 si lower(nombre) ya existe.
  crearDisciplina(body: DisciplinaCreate, signal?: AbortSignal): Promise<Disciplina> {
    return platformRequest<Disciplina>('/disciplinas', { method: 'POST', body, signal });
  },
  // PUT /plataforma/disciplinas/{id} -> renombra y/o cambia activo (soft-delete =
  // activo:false). 409 colisión de nombre, 404 si no existe.
  actualizarDisciplina(
    id: string,
    body: DisciplinaUpdate,
    signal?: AbortSignal,
  ): Promise<Disciplina> {
    return platformRequest<Disciplina>(`/disciplinas/${id}`, {
      method: 'PUT',
      body,
      signal,
    });
  },
};
