# Referencia de diseño — UI de LATINOSPORT

> Capturado del prototipo clickable de claude.ai (efímero) el 2026-06-05. Fuente de verdad
> **visual** para `frontend-dev`. El SRS manda en reglas de negocio; esto manda en look&feel.
> Prototipo = solo UI: datos de ejemplo, y acciones PDF/WhatsApp son visuales.

## Marca y nomenclatura
- **Nombre oficial: LATINOSPORT** (decisión del usuario, 2026-06-06). Configurable vía
  `APP_NAME`/`VITE_APP_NAME` (no hardcodear). Nombres previos del prototipo: CanteraSport/LATINASPORT.
- Desarrolla: **SnapCoding**.

## Sistema de diseño (design tokens)
- **Tipografía:** `Space Grotesk` (display, cifras, encabezados) + `Hanken Grotesk` (UI,
  cuerpo). Carácter geométrico/deportivo.
- **Acento:** **AZUL por defecto** (oklch matiz ~250°: principal `oklch(0.58 0.16 250)` ≈ #2F6BD6,
  fuerte `oklch(0.50 0.17 252)`, suave `oklch(0.95 0.03 250)`, tinta `oklch(0.46 0.14 252)`); verde
  como alterno, **intercambiable** vía `[data-accent]`. Acento como variable de tema, no color fijo.
- **Modo:** claro, superficies **planas** (sin sombras pesadas), bordes/divisores sutiles.
- **Densidad:** cómoda (más aire, legible).
- **Radio de esquinas:** redondeado, configurable.
- **Badges de estado (fijos y consistentes):** verde = **Pagado**, ámbar = **Pendiente**,
  rojo = **Vencido**. Reusa el mismo componente Badge en todas las pantallas.
- **Moneda/locale:** `Bs` (bolivianos), datos realistas de Bolivia. Moneda/fecha por
  organización (no hardcodear — RNF-04).

## Shell común (layout)
- **Top bar:** logo + selector de sucursal (`Todas las sucursales ▾`) + buscador
  (`Buscar alumno, CI o…`) + campana de notificaciones + avatar de usuario con rol.
- **Sidebar izquierda colapsable**, adaptada al rol:
  - `GESTIÓN`: **Panel**, **Alumnos**, **Pagos**, **Asistencia**
  - `ACCIONES`: **Generar QR**
  - pie: usuario actual + rol (con punto de estado)
- **Toggle de rol:** clic en el avatar alterna **Administrador ⇄ Entrenador**; la sidebar y
  las vistas se adaptan (Entrenador ve "Mis categorías" reutilizando la vista de lista).

## Pantallas

### 1. Panel del Administrador — "Panel de cobranza"
Subtítulo: `RESUMEN · TODA LA ESCUELA` · `Junio 2026 · estado de cuotas y pagos en tiempo real`.
- **Acciones:** `Nuevo alumno`, `Generar QR`, `Registrar pago` (primario, verde).
- **4 KPI cards:**
  - Ingresos del mes — `Bs 28.450` (`▲ 8.2% vs mayo`)
  - Alumnos activos — `142` (`en 2 sucursales · 3 disciplinas`)
  - Cuotas pendientes — `23` (`Bs 5.290 por cobrar`)
  - Cuotas vencidas — `7` (`Bs 1.680 en mora`) — **card resaltada en rojo**
- **Filtro por estado (chips):** `Todos 15` · `Pagado 8` · `Pendiente 4` · `Vencido 3`.
- **Tabla de alumnos:** columnas `ALUMNO` (avatar inicial + nombre + `Sub-14 Intermedio ·
  Fútbol`), `SUCURSAL` (Centro / Cala Cala), `ESTADO` (badge), + monto / vencimiento /
  método / acción. Tabla con **scroll interno**; "Último pago" se oculta en anchos medianos
  priorizando el botón de acción.
- **Panel derecho "Alertas de morosidad":** filas `nombre · categoría · Bs monto · N días` +
  `Ver todos los vencidos`.

### 2. Registrar pago (modal)
- Selección de **alumno** y **cuota(s)**.
- **Método Efectivo:** confirmación manual.
- **Método QR:** estado en vivo `Esperando pago…` → `Pago confirmado` (conciliación
  automática **simulada** en el prototipo; en real = webhook OpenBCB idempotente).
- **Comprobante:** acciones `PDF` y `WhatsApp` (visuales en el prototipo).

### 3. Perfil del deportista
- **Header:** nombre, badge de categoría (`Sub-14 Intermedio`), disciplina (`Fútbol`),
  `Sucursal Cala Cala`, `CI 9123456 LP`, `Cuota mensual Bs 250`, `Alumno desde 10 feb 2024`.
- **Pestañas:**
  - **Datos personales:** Apellidos, Nombres, CI, Fecha de nacimiento (+ edad calculada),
    Disciplina, Categoría.
  - **Tutores y emergencia.**
  - **Ficha médica:** badge `✓ Consentimiento del tutor`; Tipo de sangre (`O+`), Alergias
    (`Penicilina`), Condiciones (`Asma leve (inhalador)`). Aviso: **"Información visible solo
    para administradores y entrenador de la categoría"** (acceso por rol — RNF-02).
  - **Inscripción.**
  - **Historial de pagos.**

### 4. Asistencia (entrenador)
- Toma de lista con **toggles Presente/Ausente**, contadores y botón **Guardar**.
- **Optimizada para móvil.**

## Datos de ejemplo (estilo Bolivia, para fixtures/seeds)
- Nombres: Mateo Quispe Mamani, Valentina Condori Huanca, Santiago Vargas Apaza, Diego Mamani
  Ticona, Luciana Choque Calle, Sebastián Gutiérrez Rojas, Daniela Aliaga Cuéllar…
- Sucursales: **Centro**, **Cala Cala**. Disciplinas: **Fútbol**, **Básquetbol**, **Natación**.
- Categorías: `Sub-10 Principiante`, `Sub-14 Intermedio`, `Sub-17 Avanzado`.
- CI formato: `9123456 LP`. Cuota típica: `Bs 250`.

## Notas para el desarrollo
- El frontend muestra/valida UX; las reglas duras (cuotas, idempotencia, conciliación) las
  decide el backend. No dupliques esa lógica en el cliente.
- Respeta el alcance por rol en la UI (un Entrenador no ve datos fuera de sus categorías).
- Reusa: `Badge` de estado, `KPICard`, `DataTable` (con columnas ocultables), shell común.
