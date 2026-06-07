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
  // Disciplinas (S2): FK opcional al catálogo global + ref embebida {id,nombre}.
  // El backend la sirve al leer la categoría; null si la categoría no tiene
  // disciplina asignada.
  disciplina_id?: string | null;
  disciplina?: DisciplinaRef | null;
}

// Forma reducida de categoría embebida en deportista (sin rango_edad/sucursal_id).
export interface CategoriaRef {
  id: string;
  nombre: string;
  nivel: Nivel;
}

export interface SucursalRef {
  id: string;
  nombre: string;
}

// ---- C5: Deportistas ----
// GET /deportistas -> item de lista
export interface DeportistaListItem {
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

export type DeportistasListResponse = Paginated<DeportistaListItem>;

// Tutor embebido en el perfil del deportista (GET /deportistas/{id})
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

// GET /deportistas/{id} -> perfil completo
export interface DeportistaDetail {
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

// --- GET /tutores/por-ci/{ci} (recuperar-por-CI del tutor; S3) ---
// Solo los datos propios del tutor (sin parentesco/responsable_pago, que viven en
// el puente deportista_tutor y dependen del vínculo, no del tutor). 404 si no hay
// tutor con ese CI en la org. Mirror EXACTO de TutorByCiOut del backend.
export interface TutorByCi {
  id: string;
  nombres: string;
  telefono: string | null;
  ci: string | null;
}

// ---- C5: POST /deportistas (DeportistaCreate) ----
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

export interface DeportistaCreate {
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

// DeportistaCreate produce un DeportistaDetail al crear.
export type DeportistaCreated = DeportistaDetail;

// ============================================================
// C4: Cobranza (espejo EXACTO de los contratos del epic Cobranza)
// No inventar campos. Si falta algo, es hand-off a backend-dev.
// ============================================================

// PARCIAL = saldo > 0 y < monto, sin vencer (epic Abonos). El backend manda el estado.
export type EstadoCuota = 'PENDIENTE' | 'PARCIAL' | 'PAGADO' | 'VENCIDO';
export type MetodoPago = 'EFECTIVO' | 'QR';
// estado del PAGO (distinto del estado de la CUOTA)
export type EstadoPago = 'PENDIENTE' | 'CONFIRMADO' | 'FALLIDO';

// --- GET /cobranza/cuotas -> item de lista ---
// {id, deportista:{id,nombre_completo}, sucursal:{nombre}, categoria:{nombre},
//  periodo_inicio, vence_el, monto, estado, ultimo_metodo|null}
export interface CuotaDeportistaRef {
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
  deportista: CuotaDeportistaRef;
  sucursal: CuotaSucursalRef;
  categoria: CuotaCategoriaRef;
  periodo_inicio: string; // date
  vence_el: string; // date
  monto: string; // numeric(10,2) serializado como string
  // Abonos: monto ya cubierto y saldo derivado (monto - monto_pagado). Strings numeric.
  monto_pagado: string; // numeric(10,2) serializado como string
  saldo: string; // numeric(10,2) serializado como string (lo deriva el backend)
  estado: EstadoCuota;
  ultimo_metodo: MetodoPago | null;
}

export type CuotasListResponse = Paginated<CuotaListItem>;

// --- GET /cobranza/panel ---
// {ingresos_mes:{monto}, deportistas_activos:{count, sucursales, disciplinas},
//  cuotas_pendientes:{count, monto}, cuotas_vencidas:{count, monto},
//  morosidad:[{deportista_id, nombre_completo, categoria, monto, dias_mora}]}
export interface PanelIngresosMes {
  monto: string;
}

export interface PanelDeportistasActivos {
  count: number;
  sucursales: number;
  disciplinas: number;
}

export interface PanelCuotasAgg {
  count: number;
  monto: string;
}

export interface MorosidadItem {
  deportista_id: string;
  nombre_completo: string;
  categoria: string;
  monto: string;
  dias_mora: number;
}

export interface PanelCobranza {
  ingresos_mes: PanelIngresosMes;
  deportistas_activos: PanelDeportistasActivos;
  // Abonos: cuotas_pendientes/cuotas_vencidas suman SALDO (no monto nominal); el
  // backend ya lo calcula así. credito_total = Σ credito.saldo de la org.
  cuotas_pendientes: PanelCuotasAgg;
  cuotas_vencidas: PanelCuotasAgg;
  credito_total: string; // numeric(10,2) serializado como string
  morosidad: MorosidadItem[];
}

// --- POST /cobranza/pagos/efectivo (body) ---
// crea pago EFECTIVO CONFIRMADO aplicado a cuota_ids (FIFO en backend).
export interface RegistrarPagoEfectivoBody {
  cuota_ids: string[];
  // Abonos (RF-ABO): monto recibido en caja. null/omitido => paga el total (Σ saldo).
  // El backend distribuye FIFO y guarda el sobrepago como crédito de la inscripción.
  monto_recibido?: string | null; // numeric(10,2) serializado como string
}

// --- POST /cobranza/pagos/qr (body) ---
// crea pago QR PENDIENTE; devuelve el QR para mostrar.
export interface RegistrarPagoQrBody {
  cuota_ids: string[];
}

// Abonos: aplicación del pago a una cuota concreta (FIFO en backend).
export interface PagoCuotaAplicada {
  cuota_id: string;
  monto_aplicado: string; // numeric(10,2) serializado como string
  saldo_restante: string; // numeric(10,2) serializado como string (0 => quedó PAGADO)
  estado: EstadoCuota; // estado destino de la cuota tras aplicar
}

// --- GET /cobranza/pagos/{id} (polling) ---
// {id, estado, metodo, monto, comprobante_url} + campos de abonos.
// monto = solo efectivo de caja; credito_aplicado = crédito previo consumido;
// credito_generado = sobrepago guardado como saldo a favor. Defaults 0/[] => QR
// y el polling existente no se rompen.
export interface PagoOut {
  id: string;
  estado: EstadoPago;
  metodo: MetodoPago;
  monto: string;
  comprobante_url: string | null;
  credito_generado: string; // numeric(10,2) serializado como string
  credito_aplicado: string; // numeric(10,2) serializado como string
  cuotas_aplicadas: PagoCuotaAplicada[];
  // Recibo (epic Recibo): N° correlativo por org REC-NNNNNN, asignado al
  // confirmar. null hasta confirmar / pagos históricos sin backfill.
  numero_recibo?: string | null;
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

// --- POST /cobranza/cuotas/{cuota_id}/recordatorio (ADMIN) ---
// Dispara el recordatorio de cobro por WhatsApp para una cuota (RNF-07: tiene
// costo; el backend respeta toggles e idempotencia). Body opcional: { forzar }
// (default false) para reenviar uno ya enviado.
export interface RecordatorioIn {
  forzar?: boolean;
}

// motivo describe el resultado: "ok" (enviado), "ya_enviado" (idempotencia),
// "sin_telefono" (tutor sin teléfono), "error_envio" (falló el proveedor).
export type MotivoRecordatorio = 'ok' | 'ya_enviado' | 'sin_telefono' | 'error_envio';

export interface RecordatorioOut {
  enviado: boolean;
  cuota_id: string; // uuid
  provider_message_id: string | null;
  motivo: MotivoRecordatorio | null;
}

// ============================================================
// C2: Asistencia (espejo EXACTO de los contratos del epic Asistencia)
// No inventar campos. Si falta algo, es hand-off a backend-dev.
// ============================================================

export type EstadoAsistencia = 'PRESENTE' | 'AUSENTE';

// --- GET /asistencia/categorias -> categorías visibles por rol ---
// [{id, nombre, nivel, sucursal:{id,nombre}, total_deportistas}]
export interface CategoriaAsistencia {
  id: string;
  nombre: string;
  nivel: Nivel;
  sucursal: SucursalRef;
  total_deportistas: number;
}

// --- GET /asistencia/roster?categoria_id=&fecha=YYYY-MM-DD ---
// item por deportista; estado=null si aún no hay sesión guardada.
export interface RosterItem {
  deportista_id: string;
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
// {categoria_id, fecha, hora?, marcas:[{deportista_id, estado}]} -> idempotente.
// Devuelve el roster guardado (RosterOut).
export interface MarcaAsistencia {
  deportista_id: string;
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

// ============================================================
// C2: Programación de clases / Horarios (espejo EXACTO del contrato C2 del
// epic "Programación de clases"). Vista scoped por rol en el backend (ADMIN ve
// todos los activos de la org; ENTRENADOR solo los de sus sucursales).
// Escritura solo ADMIN (POST/PUT/DELETE soft). No inventar campos: si falta
// algo, es hand-off a backend-dev.
// ============================================================

// 0=Lunes … 6=Domingo (= date.weekday() en el backend). dia_label lo da el backend.
export type DiaSemana = 0 | 1 | 2 | 3 | 4 | 5 | 6;

// Categoría embebida en un horario (forma reducida {id, nombre}).
export interface HorarioCategoriaRef {
  id: string;
  nombre: string;
}

// Entrenador embebido en un horario (forma reducida {id, nombres}). Puede ser null.
export interface HorarioEntrenadorRef {
  id: string;
  nombres: string;
}

// --- GET /horarios?categoria_id=&sucursal_id= -> item de la lista ---
// {id, categoria:{id,nombre}, sucursal:{id,nombre}, dia_semana, dia_label,
//  hora_inicio, hora_fin, entrenador:{id,nombres}|null, activo}
export interface HorarioOut {
  id: string;
  categoria: HorarioCategoriaRef;
  sucursal: SucursalRef;
  dia_semana: DiaSemana;
  dia_label: string; // "Lunes", "Martes", … (lo da el backend)
  hora_inicio: string; // time HH:MM
  hora_fin: string; // time HH:MM
  entrenador: HorarioEntrenadorRef | null;
  activo: boolean;
}

// Clase dentro de un día de la rejilla semanal (GET /horarios/semana).
// {id, categoria, hora_inicio, hora_fin, entrenador}
export interface ClaseSemana {
  id: string;
  categoria: HorarioCategoriaRef;
  hora_inicio: string; // time HH:MM
  hora_fin: string; // time HH:MM
  entrenador: HorarioEntrenadorRef | null;
}

// Un día de la rejilla semanal con sus clases (siempre 7 días, 0..6).
export interface DiaSemanaOut {
  dia_semana: DiaSemana;
  dia_label: string;
  clases: ClaseSemana[];
}

// --- GET /horarios/semana?sucursal_id=&categoria_id= -> rejilla semanal ---
// {dias:[{dia_semana, dia_label, clases:[...]}]} (7 días, 0..6).
export interface SemanaOut {
  dias: DiaSemanaOut[];
}

// --- POST /horarios (ADMIN) / PUT /horarios/{id} (ADMIN) (body) ---
// {categoria_id, dia_semana, hora_inicio, hora_fin, entrenador_id?}.
// El backend valida hora_fin > hora_inicio (422) y unicidad (409).
export interface HorarioCreate {
  categoria_id: string;
  dia_semana: DiaSemana;
  hora_inicio: string; // time HH:MM
  hora_fin: string; // time HH:MM
  entrenador_id?: string | null; // opcional
}

// POST/PUT /horarios devuelven el horario (mismo shape que un item de la lista).
export type HorarioCreated = HorarioOut;

// ============================================================
// C2/C3: Auto-registro de deportista — Solicitudes (espejo EXACTO de los contratos
// C2/C3 del epic Auto-registro, versión EN SISTEMA). Toda la API es autenticada
// (NADA público, sin token/link). Captura: ADMIN o ENTRENADOR. Aprobar/rechazar:
// solo ADMIN. No inventar campos: si falta algo, es hand-off a backend-dev.
// ============================================================

export type EstadoSolicitud = 'PENDIENTE' | 'APROBADA' | 'RECHAZADA';

// Ficha médica de la solicitud (jsonb opcional). Misma forma que FichaMedicaCreate.
export interface SolicitudFichaMedica {
  tipo_sangre: string;
  alergias: string;
  condiciones: string;
}

// Datos del tutor capturados en la solicitud (sin responsable_pago: lo decide el
// admin al aprobar reutilizando la creación de deportista).
export interface SolicitudTutorCreate {
  nombres: string;
  telefono: string;
  ci?: string | null;
  parentesco: string;
}

// Consentimiento capturado en el sistema (aceptado debe ser true → 422 si no).
export interface SolicitudConsentimientoCreate {
  aceptado: true;
  version_terminos: string;
}

// --- POST /solicitudes (body) — C2 ---
// creado_por lo fija el backend desde el token. Si es ENTRENADOR, la
// sucursal_sugerida_id (si viene) debe estar en sus sucursales (403 si no).
export interface SolicitudCreate {
  ap_paterno: string;
  ap_materno: string;
  nombres: string;
  ci: string;
  fecha_nac: string; // date YYYY-MM-DD
  disciplina: string;
  contacto_emergencia?: string | null;
  ficha_medica?: SolicitudFichaMedica | null;
  tutor: SolicitudTutorCreate; // datos mínimos del tutor → 422 si faltan
  consentimiento: SolicitudConsentimientoCreate; // aceptado:true obligatorio → 422
  sucursal_sugerida_id?: string | null;
  categoria_sugerida_id?: string | null;
}

// Tutor embebido en la solicitud (forma de salida).
export interface SolicitudTutor {
  nombres: string;
  telefono: string;
  ci: string | null;
  parentesco: string;
}

// --- GET /solicitudes (item) y GET /solicitudes/{id} — C3 (SolicitudOut) ---
// datos enviados + estado + creado_por_nombre + sucursal/categoria sugeridas +
// created_at + deportista_id|null + motivo_rechazo|null.
export interface SolicitudOut {
  id: string;
  estado: EstadoSolicitud;
  ap_paterno: string;
  ap_materno: string;
  nombres: string;
  ci: string;
  fecha_nac: string; // date YYYY-MM-DD
  disciplina: string;
  contacto_emergencia: string | null;
  ficha_medica: SolicitudFichaMedica | null;
  tutor: SolicitudTutor;
  sucursal_sugerida: SucursalRef | null;
  categoria_sugerida: CategoriaRef | null;
  creado_por_nombre: string | null;
  created_at: string; // timestamptz
  deportista_id: string | null; // set al aprobar
  motivo_rechazo: string | null; // set al rechazar
}

// GET /solicitudes -> {items, total, page, page_size}.
export type SolicitudesPage = Paginated<SolicitudOut>;

// --- POST /solicitudes/{id}/aprobar (ADMIN) body — C3 ---
// Crea el deportista real reutilizando la lógica del epic Deportistas. 409 si ya resuelta.
export interface AprobarBody {
  sucursal_id: string; // requerido
  categoria_id?: string | null;
  monto_mensual?: string | null; // numeric serializado como string; si viene → inscripción
  modo_cobro?: ModoCobro | null;
}

// POST /solicitudes/{id}/aprobar devuelve el deportista creado.
export type SolicitudDeportistaCreado = DeportistaDetail;

// --- POST /solicitudes/{id}/rechazar (ADMIN) body — C3 ---
// 409 si ya resuelta. Devuelve la solicitud actualizada (RECHAZADA).
export interface RechazarBody {
  motivo: string;
}

// ============================================================
// Epic A: Super Admin / consola de plataforma (rol SUPERADMIN, token SIN org_id).
// App SEPARADA del panel de escuela: su token vive en otra clave de storage y el
// cliente lo manda solo a /plataforma/*. Espejo EXACTO del contrato de la spec
// docs/specs/super-admin.md; no inventar campos: si falta algo, es hand-off a
// backend-dev.
// ============================================================

// Identidad de plataforma (sin org_id, sin RLS). Devuelta por el login.
export interface PlatformAdmin {
  id: string;
  nombre: string;
  email: string;
}

// --- POST /plataforma/login ---
// req {email,password} -> token SUPERADMIN (sin org_id) + datos del admin.
export interface PlatformLoginOut {
  access_token: string;
  admin: PlatformAdmin;
}

// Estado de una escuela (organización) gestionada desde la consola.
export type EstadoEscuela = 'ACTIVA' | 'SUSPENDIDA';

// --- GET /plataforma/escuelas -> item de lista ---
export interface Escuela {
  id: string;
  nombre: string;
  pais: string | null;
  moneda: string | null;
  estado: EstadoEscuela;
  created_at: string; // timestamptz
}

// --- POST /plataforma/escuelas (body) ---
// Crea la organización ACTIVA + su primer usuario ADMIN. 409 si admin_email existe.
export interface CrearEscuelaIn {
  nombre: string;
  pais?: string | null;
  moneda?: string | null;
  admin_nombre: string;
  admin_email: string;
  admin_password: string;
}

// --- POST /plataforma/escuelas -> 201 ---
export interface EscuelaCreada {
  id: string;
  nombre: string;
  estado: EstadoEscuela;
  admin: { id: string; email: string };
}

// --- POST /plataforma/escuelas/{id}/suspender|reactivar -> estado nuevo ---
export interface EscuelaEstadoOut {
  id: string;
  estado: EstadoEscuela;
}

// --- GET /plataforma/admins -> item de lista (nunca expone password_hash) ---
export interface SuperAdmin {
  id: string;
  nombre: string;
  email: string;
  activo: boolean;
  created_at: string; // timestamptz
}

// --- POST /plataforma/admins (body) -> 201. 409 si email duplicado. ---
export interface CrearSuperAdminIn {
  nombre: string;
  email: string;
  password: string;
}

// --- POST /plataforma/admins -> 201 (sin password_hash) ---
export interface SuperAdminCreado {
  id: string;
  nombre: string;
  email: string;
  activo: boolean;
}

// --- POST /plataforma/admins/{id}/activar|desactivar -> activo nuevo ---
// 409 si desactivar dejaría 0 super admins activos (siempre debe quedar >=1).
export interface SuperAdminActivoOut {
  id: string;
  activo: boolean;
}

// ============================================================
// S2 · Disciplinas (catálogo GLOBAL, sin org_id). CRUD por SUPERADMIN desde la
// consola /plataforma (platformApi). Lectura para escuela (admin/entrenador):
// solo catálogo, cero datos de tenant. Espejo EXACTO del CONTRATO 2 de
// docs/specs/disciplinas.md; no inventar campos: si falta algo, es hand-off a
// backend-dev.
// ============================================================

// Forma reducida para selects de escuela (GET /catalogo/disciplinas) y como ref
// embebida en Categoria/Deportista. Cero datos de tenant.
export interface DisciplinaRef {
  id: string;
  nombre: string;
}

// --- GET /plataforma/disciplinas -> item de lista (activas + inactivas) ---
export interface Disciplina {
  id: string;
  nombre: string;
  activo: boolean;
  created_at: string; // timestamptz
}

// --- POST /plataforma/disciplinas (body) -> 201. 409 si lower(nombre) ya existe. ---
export interface DisciplinaCreate {
  nombre: string;
}

// --- PUT /plataforma/disciplinas/{id} (body) ---
// Renombrar y/o cambiar activo (soft-delete = activo:false). 409 colisión,
// 404 no existe. Ambos opcionales.
export interface DisciplinaUpdate {
  nombre?: string;
  activo?: boolean;
}

// ============================================================
// Epic B · Gestión de Entrenadores (espejo EXACTO del contrato fijado por main).
// Listar: cualquier rol autenticado (pobla selectores). Alta/edición: SOLO ADMIN
// (el backend responde 403 a ENTRENADOR). No inventar campos: si falta algo, es
// hand-off a backend-dev.
// ============================================================

// --- GET /entrenadores?solo_activos= -> item de lista ---
// {id, usuario_id, nombres, email, especialidad|null, disciplinas[], activo}.
// email y activo provienen del usuario ligado (join por entrenador.usuario_id).
// telefono: E.164 sin "+" (p.ej. "59170000000"), opcional. sucursal_ids: set de
// sucursales asignadas al entrenador (M:N) que alimenta el digest de deudores.
export interface EntrenadorOut {
  id: string;
  usuario_id: string;
  nombres: string;
  email: string;
  especialidad: string | null;
  disciplinas: string[];
  activo: boolean;
  telefono?: string | null;
  sucursal_ids: string[];
}

// --- POST /entrenadores (ADMIN) body ---
// Crea usuario(ENTRENADOR, activo) + entrenador en una transacción.
// Email ya en uso (en esta org o en otra) -> 409. password < 8 -> 422.
// telefono: E.164 sin "+" (opcional). sucursal_ids: set de sucursales asignadas.
export interface EntrenadorCreate {
  nombres: string;
  email: string;
  password: string;
  especialidad?: string | null;
  disciplinas?: string[];
  telefono?: string | null;
  sucursal_ids: string[];
}

// --- PUT /entrenadores/{id} (ADMIN) body (todos opcionales) ---
// Edita nombres/especialidad/disciplinas y activo (+ password si viene).
// activo=false da de baja; activo=true reactiva. password < 8 (si viene) -> 422.
// telefono: E.164 sin "+". sucursal_ids: null = no tocar; [] = limpiar; lista
// REEMPLAZA el set actual (el backend resuelve el delta).
export interface EntrenadorUpdate {
  nombres?: string;
  especialidad?: string | null;
  disciplinas?: string[];
  activo?: boolean;
  password?: string;
  telefono?: string | null;
  sucursal_ids?: string[] | null;
}

// --- POST /entrenadores/{id}/recordatorio-deudores (ADMIN) — CONTRATO 4 ---
// Dispara el digest de deudores por WhatsApp para TODAS las sucursales asignadas
// al entrenador (origen MANUAL). Sin body. 404 si el entrenador no existe en la
// org. Entrenador sin teléfono -> 200 con todas las sucursales en FALLIDO (estado
// de negocio, no error HTTP). El backend impone idempotencia (RNF-07).
export type EstadoRecordatorioDeudores = 'ENVIADO' | 'SIN_DEUDORES' | 'FALLIDO';

// Resultado por sucursal: nº de deudores, monto adeudado total (Σ saldo) y estado.
export interface RecordatorioDeudoresSucursalOut {
  sucursal_id: string;
  sucursal_nombre: string;
  num_deudores: number;
  monto_total: string; // numeric(10,2) serializado como string (Decimal en backend)
  estado: EstadoRecordatorioDeudores;
}

export interface RecordatorioDeudoresResult {
  entrenador_id: string;
  periodo: string; // MANUAL-<ts> en el disparo a demanda
  enviados: number; // nº de mensajes/sucursales efectivamente enviados
  sucursales: RecordatorioDeudoresSucursalOut[];
}

// ============================================================
// Sucursales / Categorías — CRUD (epic Sucursales-Recibo, Sesión C).
// SOLO ADMIN (el backend responde 403 a ENTRENADOR). El GET ya existe
// (Sucursal/Categoria arriba). Aquí los bodies de escritura. DELETE devuelve
// 204 y 409 (CONFLICT) si la entidad está en uso (no cascada). No inventar
// campos: si falta algo, es hand-off a backend-dev.
// ============================================================

// SucursalOut del contrato: direccion es nullable. La forma de lectura `Sucursal`
// (arriba) la sirve como string ("" si no hay); los bodies aceptan null/omitido.

// --- POST /sucursales (ADMIN) -> SucursalOut (201) ---
export interface SucursalCreate {
  nombre: string;
  direccion?: string | null;
}

// --- PUT /sucursales/{id} (ADMIN) -> SucursalOut ---
export type SucursalUpdate = SucursalCreate;

// --- POST /categorias (ADMIN) -> CategoriaOut (201) ---
// nivel validado contra PRINCIPIANTE|INTERMEDIO|AVANZADO (422 si difiere).
export interface CategoriaCreate {
  nombre: string;
  nivel: Nivel;
  rango_edad?: string | null;
  sucursal_id: string;
  // Disciplinas (S2): opcional. El backend valida que exista y esté activa
  // (404/422). null/omitido => categoría sin disciplina.
  disciplina_id?: string | null;
}

// --- PUT /categorias/{id} (ADMIN) -> CategoriaOut ---
// sucursal_id NO editable (no se envía en el update).
export interface CategoriaUpdate {
  nombre: string;
  nivel: Nivel;
  rango_edad?: string | null;
  // Disciplinas (S2): opcional. null limpia la disciplina; omitirlo NO la toca
  // según el contrato del backend (validar existencia/activa => 404/422).
  disciplina_id?: string | null;
}
