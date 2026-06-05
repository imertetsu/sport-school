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
