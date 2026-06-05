// Tipos espejo EXACTO de los contratos C4 (auth) y C5 (API REST).
// No inventar campos. Si falta algo, es hand-off a backend-dev.

// ---- C4: Auth / JWT ----
export type Role = 'ADMIN' | 'ENTRENADOR';

export interface UserOut {
  id: string;
  nombre: string;
  email: string;
  role: Role;
  org_id: string;
}

// POST /api/v1/auth/login -> token + user
export interface TokenOut {
  access_token: string;
  token_type: 'bearer';
  user: UserOut;
}

export interface LoginRequest {
  email: string;
  password: string;
}

// ---- C5: catálogos ----
export interface Sucursal {
  id: string;
  nombre: string;
  direccion: string;
}

export type Nivel = 'PRINCIPIANTE' | 'INTERMEDIO' | 'AVANZADO';

export interface Categoria {
  id: string;
  nombre: string;
  nivel: Nivel;
  rango_edad: string;
  sucursal_id: string;
}

// Forma reducida de categoría embebida en alumno (sin rango_edad/sucursal_id).
export interface CategoriaRef {
  id: string;
  nombre: string;
  nivel: Nivel;
}

export interface SucursalRef {
  id: string;
  nombre: string;
}

// ---- C5: Alumnos ----
// GET /alumnos -> item de lista
export interface AlumnoListItem {
  id: string;
  ap_paterno: string;
  ap_materno: string;
  nombres: string;
  nombre_completo: string;
  ci: string;
  disciplina: string;
  categoria: CategoriaRef | null;
  sucursal: SucursalRef;
}

export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export type AlumnosListResponse = Paginated<AlumnoListItem>;

// Tutor embebido en el perfil del alumno (GET /alumnos/{id})
export interface Tutor {
  id: string;
  nombres: string;
  telefono: string;
  ci: string;
  parentesco: string;
  responsable_pago: boolean;
}

export type ModoCobro = 'FIJO' | 'ANIVERSARIO';
export type EstadoInscripcion = 'ACTIVA' | 'INACTIVA';

export interface Inscripcion {
  fecha_inscripcion: string; // date
  monto_mensual: string; // numeric(10,2) serializado como string
  disciplina: string;
  estado: EstadoInscripcion;
}

export interface Consentimiento {
  aceptado_en: string; // timestamp
  version_terminos: string;
  canal: string;
}

export interface FichaMedica {
  tipo_sangre: string;
  alergias: string;
  condiciones: string;
}

// GET /alumnos/{id} -> perfil completo
export interface AlumnoDetail {
  id: string;
  ap_paterno: string;
  ap_materno: string;
  nombres: string;
  nombre_completo: string;
  ci: string;
  fecha_nac: string; // date
  edad: number;
  disciplina: string;
  contacto_emergencia: string;
  sucursal: SucursalRef;
  categoria: CategoriaRef | null;
  inscripcion: Inscripcion | null;
  tutores: Tutor[];
  consentimiento: Consentimiento | null;
  // null si el rol no tiene acceso (RNF-02).
  ficha_medica: FichaMedica | null;
}

// ---- C5: POST /alumnos (AlumnoCreate) ----
export interface TutorCreate {
  nombres: string;
  telefono: string;
  ci: string;
  parentesco: string;
  responsable_pago: boolean;
}

export interface ConsentimientoCreate {
  version_terminos: string;
  canal: string;
}

export interface InscripcionCreate {
  disciplina: string;
  fecha_inscripcion: string;
  monto_mensual: string;
  modo_cobro?: ModoCobro | null;
  dia_corte?: number | null;
}

export interface FichaMedicaCreate {
  tipo_sangre: string;
  alergias: string;
  condiciones: string;
}

export interface AlumnoCreate {
  ap_paterno: string;
  ap_materno: string;
  nombres: string;
  ci: string;
  fecha_nac: string; // date
  disciplina: string;
  sucursal_id: string;
  categoria_id?: string | null;
  contacto_emergencia: string;
  tutores: TutorCreate[]; // >= 1 (validación dura backend -> 422)
  consentimiento: ConsentimientoCreate; // obligatorio
  inscripcion?: InscripcionCreate | null;
  ficha_medica?: FichaMedicaCreate | null;
}

// AlumnoCreate produce un AlumnoDetail al crear.
export type AlumnoCreated = AlumnoDetail;

// ============================================================
// C4: Cobranza (espejo EXACTO de los contratos del epic Cobranza)
// No inventar campos. Si falta algo, es hand-off a backend-dev.
// ============================================================

export type EstadoCuota = 'PENDIENTE' | 'PAGADO' | 'VENCIDO';
export type MetodoPago = 'EFECTIVO' | 'QR';
// estado del PAGO (distinto del estado de la CUOTA)
export type EstadoPago = 'PENDIENTE' | 'CONFIRMADO' | 'FALLIDO';

// --- GET /cobranza/cuotas -> item de lista ---
// {id, alumno:{id,nombre_completo}, sucursal:{nombre}, categoria:{nombre},
//  periodo_inicio, vence_el, monto, estado, ultimo_metodo|null}
export interface CuotaAlumnoRef {
  id: string;
  nombre_completo: string;
}

export interface CuotaSucursalRef {
  nombre: string;
}

export interface CuotaCategoriaRef {
  nombre: string;
}

export interface CuotaListItem {
  id: string;
  alumno: CuotaAlumnoRef;
  sucursal: CuotaSucursalRef;
  categoria: CuotaCategoriaRef;
  periodo_inicio: string; // date
  vence_el: string; // date
  monto: string; // numeric(10,2) serializado como string
  estado: EstadoCuota;
  ultimo_metodo: MetodoPago | null;
}

export type CuotasListResponse = Paginated<CuotaListItem>;

// --- GET /cobranza/panel ---
// {ingresos_mes:{monto}, alumnos_activos:{count, sucursales, disciplinas},
//  cuotas_pendientes:{count, monto}, cuotas_vencidas:{count, monto},
//  morosidad:[{alumno_id, nombre_completo, categoria, monto, dias_mora}]}
export interface PanelIngresosMes {
  monto: string;
}

export interface PanelAlumnosActivos {
  count: number;
  sucursales: number;
  disciplinas: number;
}

export interface PanelCuotasAgg {
  count: number;
  monto: string;
}

export interface MorosidadItem {
  alumno_id: string;
  nombre_completo: string;
  categoria: string;
  monto: string;
  dias_mora: number;
}

export interface PanelCobranza {
  ingresos_mes: PanelIngresosMes;
  alumnos_activos: PanelAlumnosActivos;
  cuotas_pendientes: PanelCuotasAgg;
  cuotas_vencidas: PanelCuotasAgg;
  morosidad: MorosidadItem[];
}

// --- POST /cobranza/pagos/efectivo (body) ---
// crea pago EFECTIVO CONFIRMADO aplicado a cuota_ids (FIFO en backend).
export interface RegistrarPagoEfectivoBody {
  cuota_ids: string[];
}

// --- POST /cobranza/pagos/qr (body) ---
// crea pago QR PENDIENTE; devuelve el QR para mostrar.
export interface RegistrarPagoQrBody {
  cuota_ids: string[];
}

// --- GET /cobranza/pagos/{id} (polling) ---
// {id, estado, metodo, monto, comprobante_url}
export interface PagoOut {
  id: string;
  estado: EstadoPago;
  metodo: MetodoPago;
  monto: string;
  comprobante_url: string | null;
}

// --- POST /cobranza/pagos/qr -> QR a mostrar ---
// Respuesta PLANA del backend (C3/C4): pago PENDIENTE + datos del QR.
export interface QrResponse {
  pago_id: string;
  estado: EstadoPago;
  monto: string;
  qr_ref: string;
  qr_payload: string;
  qr_png_data_url: string;
}

// --- POST /cobranza/generar -> {creadas:n} ---
export interface GenerarCuotasResponse {
  creadas: number;
}

// ============================================================
// C2: Asistencia (espejo EXACTO de los contratos del epic Asistencia)
// No inventar campos. Si falta algo, es hand-off a backend-dev.
// ============================================================

export type EstadoAsistencia = 'PRESENTE' | 'AUSENTE';

// --- GET /asistencia/categorias -> categorías visibles por rol ---
// [{id, nombre, nivel, sucursal:{id,nombre}, total_alumnos}]
export interface CategoriaAsistencia {
  id: string;
  nombre: string;
  nivel: Nivel;
  sucursal: SucursalRef;
  total_alumnos: number;
}

// --- GET /asistencia/roster?categoria_id=&fecha=YYYY-MM-DD ---
// item por alumno; estado=null si aún no hay sesión guardada.
export interface RosterItem {
  alumno_id: string;
  nombre_completo: string;
  estado: EstadoAsistencia | null;
}

export interface RosterCategoriaRef {
  id: string;
  nombre: string;
}

export interface RosterResumen {
  presentes: number;
  ausentes: number;
  total: number;
}

// {sesion_id|null, categoria:{id,nombre}, fecha, items:[...], resumen:{...}}
export interface RosterOut {
  sesion_id: string | null;
  categoria: RosterCategoriaRef;
  fecha: string; // date YYYY-MM-DD
  items: RosterItem[];
  resumen: RosterResumen;
}

// --- POST /asistencia/guardar (body) ---
// {categoria_id, fecha, hora?, marcas:[{alumno_id, estado}]} -> idempotente.
// Devuelve el roster guardado (RosterOut).
export interface MarcaAsistencia {
  alumno_id: string;
  estado: EstadoAsistencia;
}

export interface GuardarBody {
  categoria_id: string;
  fecha: string; // date YYYY-MM-DD
  hora?: string | null; // time HH:MM, opcional
  marcas: MarcaAsistencia[];
}

// --- GET /asistencia/sesiones?categoria_id=&page=&page_size= -> historial ---
// {items:[{id, fecha, hora, presentes, ausentes, total}], total, page, page_size}
export interface SesionHistorialItem {
  id: string;
  fecha: string; // date
  hora: string | null; // time HH:MM o null
  presentes: number;
  ausentes: number;
  total: number;
}

export type SesionesListResponse = Paginated<SesionHistorialItem>;

// ============================================================
// Egresos (espejo EXACTO del contrato C2 del epic Egresos).
// SOLO ADMIN (el backend responde 403 a ENTRENADOR). No inventar
// campos: si falta algo, es hand-off a backend-dev.
// ============================================================

// --- GET /egresos -> item de lista ---
// {id, fecha, categoria_gasto, monto, sucursal:{id,nombre}|null,
//  descripcion|null, registrado_por_nombre|null}
export interface EgresoItem {
  id: string;
  fecha: string; // date YYYY-MM-DD
  categoria_gasto: string;
  monto: string; // numeric(10,2) serializado como string
  sucursal: SucursalRef | null; // null = gasto a nivel organización
  descripcion: string | null;
  registrado_por_nombre: string | null;
}

// GET /egresos: página + total_monto (suma de TODOS los egresos que
// matchean el filtro, NO solo la página).
export interface EgresosPage extends Paginated<EgresoItem> {
  total_monto: string; // numeric(10,2) serializado como string
}

// Filtros de GET /egresos (todos opcionales y combinables).
export interface EgresosFilters {
  sucursal_id?: string;
  categoria?: string; // match exacto de categoria_gasto
  desde?: string; // YYYY-MM-DD
  hasta?: string; // YYYY-MM-DD
  page?: number;
  page_size?: number;
}

// --- POST /egresos (body) ---
// registrado_por lo fija el backend desde el token (auditoría RNF-03).
export interface EgresoCreate {
  sucursal_id?: string | null; // null/omitido = gasto a nivel org
  categoria_gasto: string;
  monto: string; // numeric > 0 (el backend valida; 422 si <= 0)
  fecha: string; // YYYY-MM-DD
  descripcion?: string | null;
}

// POST /egresos devuelve el egreso creado (mismo shape que un item).
export type EgresoCreated = EgresoItem;

// --- GET /egresos/resumen (opcional) -> agrupado por categoría ---
export interface EgresoResumenItem {
  categoria_gasto: string;
  total: string; // numeric(10,2) serializado como string
}

// ============================================================
// C1: Reportes (espejo EXACTO de los contratos del epic Reportes)
// Solo ADMIN (require_role). Montos como string (numeric). No inventar
// campos; si falta algo, es hand-off a backend-dev.
// ============================================================

// --- GET /reportes/ingresos?anio=YYYY ---
// {anio, total, n_pagos, meses:[{mes:1..12, etiqueta:"ene"…, monto, n_pagos}]}
// Fuente: pago CONFIRMADO agrupado por mes del año. Devuelve los 12 meses
// (monto "0" si no hay). total = suma del año.
export interface IngresosMesItem {
  mes: number; // 1..12
  etiqueta: string; // "ene", "feb", …
  monto: string; // numeric(10,2) serializado como string
  n_pagos: number;
}

export interface IngresosReporte {
  anio: number;
  total: string; // suma del año (numeric serializado como string)
  n_pagos: number;
  meses: IngresosMesItem[]; // siempre 12
}

// --- GET /reportes/asistencia?desde=&hasta=&sucursal_id=&categoria_id= ---
// {desde, hasta, global:{...}, por_categoria:[{...}]}
// pct_presente = round(presentes/total_marcas*100, 1) (0 si total=0).
export interface AsistenciaGlobal {
  sesiones: number;
  presentes: number;
  ausentes: number;
  total_marcas: number;
  pct_presente: number;
}

export interface AsistenciaPorCategoria {
  categoria: { id: string; nombre: string };
  sucursal: { nombre: string };
  sesiones: number;
  presentes: number;
  ausentes: number;
  total_marcas: number;
  pct_presente: number;
}

export interface AsistenciaReporte {
  desde: string; // date YYYY-MM-DD
  hasta: string; // date YYYY-MM-DD
  global: AsistenciaGlobal;
  por_categoria: AsistenciaPorCategoria[];
}

// ============================================================
// C2: Muro de avisos (espejo EXACTO del contrato C2 del epic Muro).
// Feed scoped por rol en el backend (ADMIN ve todo; ENTRENADOR solo lo que
// le aplica y no vencido). Escritura solo ADMIN (POST/PUT/DELETE soft). No
// inventar campos: si falta algo, es hand-off a backend-dev.
// ============================================================

// Alcance del aviso. Invariante (la valida el backend, 422):
//  SUCURSAL ⇒ sucursal_id no nulo; CATEGORIA ⇒ categoria_id no nulo;
//  ORG ⇒ ambos nulos.
export type AlcanceAviso = 'ORG' | 'SUCURSAL' | 'CATEGORIA';

// --- GET /avisos -> item del feed ---
// {id, titulo, cuerpo, alcance, sucursal:{id,nombre}|null,
//  categoria:{id,nombre}|null, publicado_en, vigente_hasta,
//  creado_por_nombre|null, expirado:bool}
export interface AvisoOut {
  id: string;
  titulo: string;
  cuerpo: string;
  alcance: AlcanceAviso;
  sucursal: SucursalRef | null; // {id, nombre} si alcance=SUCURSAL
  categoria: CategoriaRef | null; // {id, nombre, nivel} si alcance=CATEGORIA
  publicado_en: string; // timestamptz
  vigente_hasta: string | null; // date; null = sin caducidad
  creado_por_nombre: string | null;
  expirado: boolean;
}

// Alias semántico para el item del muro (mismo shape que AvisoOut).
export type Aviso = AvisoOut;

// GET /avisos -> {items, total, page, page_size}. Orden: publicado_en desc.
export type AvisosPage = Paginated<AvisoOut>;

// --- POST/PUT /avisos (body) ---
// creado_por lo fija el backend desde el token (auditoría RNF-03).
export interface AvisoCreate {
  titulo: string;
  cuerpo: string;
  alcance: AlcanceAviso;
  sucursal_id?: string | null; // requerido si alcance=SUCURSAL (422 si falta)
  categoria_id?: string | null; // requerido si alcance=CATEGORIA (422 si falta)
  vigente_hasta?: string | null; // YYYY-MM-DD opcional; null = sin caducidad
}

// POST/PUT /avisos devuelven el aviso (mismo shape que un item del feed).
export type AvisoCreated = AvisoOut;
