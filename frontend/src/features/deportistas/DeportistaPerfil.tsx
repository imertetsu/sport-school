import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api, ApiError } from '@/api/client';
import { useAuth } from '@/auth/useAuth';
import type { CuotaListItem, DeportistaDetail, PagoListItem } from '@/api/types';
import {
  Avatar,
  Badge,
  Button,
  Card,
  EstadoBadge,
  Tabs,
  useToast,
  type TabItem,
} from '@/components/ui';
import { formatDate, formatDateLarga, formatMoney, mesLargo, nivelLabel } from '@/lib/format';
import './DeportistaPerfil.css';

function DataRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="datarow">
      <dt className="datarow__label">{label}</dt>
      <dd className="datarow__value">{value || '—'}</dd>
    </div>
  );
}

// Historial de pagos de UN deportista: una fila por cuota (mes) con recibo, cuota,
// vencimiento, fecha de pago, método, monto y "Ver recibo" (abre el PDF imprimible).
function HistorialPagos({ deportistaId }: { deportistaId: string }) {
  const [pagos, setPagos] = useState<PagoListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reciboEnVuelo, setReciboEnVuelo] = useState<string | null>(null);
  const [kardexEnVuelo, setKardexEnVuelo] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setError(null);
    api
      .pagosDeportista(deportistaId, 1, 50, controller.signal)
      .then((res) => {
        if (active) setPagos(res.items);
      })
      .catch((err) => {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        if (active) setError('No se pudo cargar el historial de pagos.');
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [deportistaId]);

  // Descarga el recibo (blob autenticado) y lo abre en otra pestaña para ver/imprimir.
  async function verRecibo(pagoId: string) {
    setReciboEnVuelo(pagoId);
    setError(null);
    try {
      const url = await api.comprobantePdfUrl(pagoId);
      window.open(url, '_blank', 'noopener');
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch {
      setError('No se pudo abrir el recibo.');
    } finally {
      setReciboEnVuelo(null);
    }
  }

  // Kardex (estado de cuenta): consolidado de TODOS los pagos, imprimible para el padre.
  async function verKardex() {
    setKardexEnVuelo(true);
    setError(null);
    try {
      const url = await api.kardexPdfUrl(deportistaId);
      window.open(url, '_blank', 'noopener');
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch {
      setError('No se pudo generar el kardex.');
    } finally {
      setKardexEnVuelo(false);
    }
  }

  if (error && pagos === null) {
    return (
      <Card>
        <div className="page-error" role="alert">
          {error}
        </div>
      </Card>
    );
  }
  if (pagos === null) {
    return (
      <Card>
        <p className="perfil__empty">Cargando pagos…</p>
      </Card>
    );
  }
  // Solo pagos CONFIRMADOS: un QR que quedó PENDIENTE (sin confirmar) no es un pago
  // real y no debe aparecer en el historial (los ANULADOS ya no traen cuotas). Mismo
  // criterio que el kardex, para que ambos coincidan.
  const confirmados = pagos.filter((p) => p.estado === 'CONFIRMADO');
  if (confirmados.length === 0) {
    return (
      <Card>
        <p className="perfil__empty">Sin pagos aún.</p>
      </Card>
    );
  }

  // Una fila por CUOTA (mes): un pago que cubrió varios meses se despliega en varias
  // filas con el mismo recibo (el recibo/acción solo se muestran en la 1ª del grupo).
  const filas = confirmados.flatMap((p) => {
    if (p.cuotas.length === 0) {
      return [
        {
          key: p.id,
          pagoId: p.id,
          recibo: p.numero_recibo ?? '—',
          estado: p.estado,
          cuota: '',
          vence: '',
          fechaPago: p.fecha,
          metodo: p.metodo,
          monto: p.monto,
          mostrarRecibo: true,
        },
      ];
    }
    return p.cuotas.map((c, j) => ({
      key: `${p.id}-${j}`,
      pagoId: p.id,
      recibo: p.numero_recibo ?? '—',
      estado: p.estado,
      cuota: c.periodo_inicio,
      vence: c.vence_el,
      fechaPago: p.fecha,
      metodo: p.metodo,
      monto: c.monto_aplicado,
      mostrarRecibo: j === 0,
    }));
  });

  return (
    <Card>
      {error && (
        <div className="page-error" role="alert">
          {error}
        </div>
      )}
      <div className="perfil-pagos__head">
        <p className="perfil-pagos__head-text">
          {confirmados.length}{' '}
          {confirmados.length === 1 ? 'pago registrado' : 'pagos registrados'}
        </p>
        <Button variant="secondary" size="sm" onClick={verKardex} disabled={kardexEnVuelo}>
          {kardexEnVuelo ? 'Generando kardex…' : 'Descargar kardex de pagos'}
        </Button>
      </div>
      <div className="perfil-pagos__wrap">
        <table className="perfil-pagos">
          <thead>
            <tr>
              <th>Recibo</th>
              <th>Cuota</th>
              <th>Vencimiento</th>
              <th>Fecha de pago</th>
              <th>Método</th>
              <th className="perfil-pagos__num">Monto</th>
              <th aria-label="Recibo" />
            </tr>
          </thead>
          <tbody>
            {filas.map((f) => (
              <tr
                key={f.key}
                className={f.estado === 'ANULADO' ? 'perfil-pagos__anulado' : undefined}
              >
                <td>
                  {f.mostrarRecibo
                    ? f.estado === 'ANULADO'
                      ? `${f.recibo} (anulado)`
                      : f.recibo
                    : ''}
                </td>
                <td>{f.vence ? mesLargo(f.vence) : '—'}</td>
                <td>{f.vence ? formatDateLarga(f.vence) : '—'}</td>
                <td>{formatDateLarga(f.fechaPago)}</td>
                <td>{f.metodo === 'EFECTIVO' ? 'Efectivo' : 'QR'}</td>
                <td className="perfil-pagos__num tabular">{formatMoney(f.monto)}</td>
                <td className="perfil-pagos__num">
                  {f.mostrarRecibo && f.estado === 'CONFIRMADO' ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => verRecibo(f.pagoId)}
                      disabled={reciboEnVuelo === f.pagoId}
                    >
                      {reciboEnVuelo === f.pagoId ? 'Abriendo…' : 'Ver recibo'}
                    </Button>
                  ) : (
                    ''
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

// Cuotas de UN deportista: lista todas (mes, vencimiento, monto, estado). El ADMIN
// puede ELIMINAR cuotas SIN pago — limpieza de migración: meses "fantasma" de un
// deportista que se dio de baja y volvió. Las cuotas con pago no se pueden borrar
// (hay que anular el pago primero; el backend responde 409).
function CuotasDeportista({
  deportistaId,
  isAdmin,
}: {
  deportistaId: string;
  isAdmin: boolean;
}) {
  const toast = useToast();
  const [cuotas, setCuotas] = useState<CuotaListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Confirmación en dos pasos por fila (evita borrados accidentales).
  const [confirmarId, setConfirmarId] = useState<string | null>(null);
  const [borrandoId, setBorrandoId] = useState<string | null>(null);
  // Edición inline del monto (la tarifa mensual cambió; corregir cuotas viejas).
  const [editandoId, setEditandoId] = useState<string | null>(null);
  const [montoEdit, setMontoEdit] = useState('');
  const [guardandoId, setGuardandoId] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setError(null);
    api
      .cuotas({ deportista_id: deportistaId, page: 1, page_size: 100 }, controller.signal)
      .then((res) => {
        if (active) setCuotas(res.items);
      })
      .catch((err) => {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        if (active) setError('No se pudieron cargar las cuotas.');
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [deportistaId]);

  async function eliminar(cuotaId: string) {
    setBorrandoId(cuotaId);
    setError(null);
    try {
      await api.eliminarCuota(cuotaId);
      setCuotas((prev) => (prev ? prev.filter((c) => c.id !== cuotaId) : prev));
      setConfirmarId(null);
      toast.success('Cuota eliminada');
    } catch (err) {
      let msg = 'No se pudo eliminar la cuota.';
      if (err instanceof ApiError) {
        msg =
          err.status === 409
            ? 'Esa cuota tiene un pago aplicado; anula el pago antes de eliminarla.'
            : err.isForbidden
              ? 'No tienes permiso para eliminar cuotas.'
              : err.message;
      }
      setError(msg);
      toast.error(msg);
    } finally {
      setBorrandoId(null);
    }
  }

  function iniciarEdicion(c: CuotaListItem) {
    setEditandoId(c.id);
    setMontoEdit(String(c.monto));
    setConfirmarId(null);
    setError(null);
  }

  function cancelarEdicion() {
    setEditandoId(null);
    setMontoEdit('');
  }

  async function guardarMonto(cuotaId: string) {
    const monto = montoEdit.trim();
    if (!monto || Number.isNaN(Number(monto)) || Number(monto) <= 0) {
      setError('Ingresa un monto mayor a 0.');
      return;
    }
    setGuardandoId(cuotaId);
    setError(null);
    try {
      const actualizada = await api.actualizarMontoCuota(cuotaId, monto);
      setCuotas((prev) =>
        prev
          ? prev.map((c) =>
              c.id === cuotaId
                ? {
                    ...c,
                    monto: actualizada.monto,
                    saldo: actualizada.saldo,
                    estado: actualizada.estado,
                  }
                : c,
            )
          : prev,
      );
      setEditandoId(null);
      toast.success('Monto de la cuota actualizado');
    } catch (err) {
      let msg = 'No se pudo cambiar el monto.';
      if (err instanceof ApiError) {
        msg =
          err.status === 409
            ? 'Esa cuota tiene un pago aplicado; anula el pago antes de cambiar el monto.'
            : err.isForbidden
              ? 'No tienes permiso para cambiar el monto.'
              : err.message;
      }
      setError(msg);
      toast.error(msg);
    } finally {
      setGuardandoId(null);
    }
  }

  if (error && cuotas === null) {
    return (
      <Card>
        <div className="page-error" role="alert">
          {error}
        </div>
      </Card>
    );
  }
  if (cuotas === null) {
    return (
      <Card>
        <p className="perfil__empty">Cargando cuotas…</p>
      </Card>
    );
  }
  if (cuotas.length === 0) {
    return (
      <Card>
        <p className="perfil__empty">Sin cuotas generadas.</p>
      </Card>
    );
  }

  // Cronológico por vencimiento (el backend las trae desc; acá asc para lectura).
  const ordenadas = [...cuotas].sort((a, b) => a.vence_el.localeCompare(b.vence_el));

  return (
    <Card>
      {error && (
        <div className="page-error" role="alert">
          {error}
        </div>
      )}
      <div className="perfil-pagos__wrap">
        <table className="perfil-pagos">
          <thead>
            <tr>
              <th>Cuota</th>
              {/* Distingue cuotas del mismo mes cuando hay varias inscripciones. */}
              <th>Disciplina</th>
              <th>Vencimiento</th>
              <th className="perfil-pagos__num">Monto</th>
              <th>Estado</th>
              {isAdmin && <th aria-label="Acciones" />}
            </tr>
          </thead>
          <tbody>
            {ordenadas.map((c) => {
              // "Con pago" (no borrable) = tiene algo aplicado o ya está pagada/parcial.
              const conPago =
                Number(c.monto_pagado) > 0 ||
                c.estado === 'PAGADO' ||
                c.estado === 'PARCIAL';
              return (
                <tr key={c.id}>
                  <td>{mesLargo(c.vence_el)}</td>
                  <td>{c.disciplina ?? '—'}</td>
                  <td>{formatDateLarga(c.vence_el)}</td>
                  <td className="perfil-pagos__num tabular">
                    {editandoId === c.id ? (
                      <input
                        className="field__input perfil-cuotas__monto-input"
                        type="number"
                        inputMode="decimal"
                        min="0"
                        step="0.01"
                        value={montoEdit}
                        onChange={(e) => setMontoEdit(e.target.value)}
                        autoFocus
                        aria-label="Nuevo monto de la cuota"
                      />
                    ) : (
                      formatMoney(c.monto)
                    )}
                  </td>
                  <td>
                    <EstadoBadge estado={c.estado} />
                  </td>
                  {isAdmin && (
                    <td className="perfil-pagos__num">
                      {conPago ? (
                        <span
                          className="perfil-cuotas__lock"
                          title="Tiene un pago aplicado; anúlalo para editar o borrar."
                        >
                          Con pago
                        </span>
                      ) : editandoId === c.id ? (
                        <span className="perfil-cuotas__confirm">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={cancelarEdicion}
                            disabled={guardandoId === c.id}
                          >
                            Cancelar
                          </Button>
                          <Button
                            variant="primary"
                            size="sm"
                            onClick={() => guardarMonto(c.id)}
                            disabled={guardandoId === c.id}
                          >
                            {guardandoId === c.id ? 'Guardando…' : 'Guardar'}
                          </Button>
                        </span>
                      ) : confirmarId === c.id ? (
                        <span className="perfil-cuotas__confirm">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setConfirmarId(null)}
                            disabled={borrandoId === c.id}
                          >
                            Cancelar
                          </Button>
                          <Button
                            variant="danger"
                            size="sm"
                            onClick={() => eliminar(c.id)}
                            disabled={borrandoId === c.id}
                          >
                            {borrandoId === c.id ? 'Eliminando…' : 'Confirmar'}
                          </Button>
                        </span>
                      ) : (
                        <span className="perfil-cuotas__confirm">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => iniciarEdicion(c)}
                          >
                            Editar monto
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setConfirmarId(c.id)}
                          >
                            Eliminar
                          </Button>
                        </span>
                      )}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {isAdmin && (
        <p className="perfil-cuotas__hint">
          Podés <strong>editar el monto</strong> o <strong>eliminar</strong> cuotas{' '}
          <strong>sin pago</strong> — útil si la tarifa cambió a mitad de año, o para
          limpiar meses generados de más. Las que ya tienen pago se anulan primero.
        </p>
      )}
    </Card>
  );
}

export function DeportistaPerfil() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  // viewRole es la verdad de la UI; el backend impone el permiso real (la
  // baja/reactivación es solo ADMIN — el coach es lectura). Gateamos por el rol
  // real (viewRole === user.role, sin toggle de prototipo).
  const { viewRole } = useAuth();
  const isAdmin = viewRole === 'ADMIN';
  const toast = useToast();

  const [deportista, setDeportista] = useState<DeportistaDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Baja/reactivación (epic escuela-y-bajas, Fase 2). confirmando = pide
  // confirmación; bajaEnVuelo = request en curso (deshabilita el botón para
  // evitar doble envío); bajaError = error de red/404/403 de la acción.
  const [confirmando, setConfirmando] = useState(false);
  const [bajaEnVuelo, setBajaEnVuelo] = useState(false);
  const [bajaError, setBajaError] = useState<string | null>(null);

  // Soft-delete reversible: si está activo, el botón da de baja; si no, reactiva.
  // Llama al endpoint dedicado y refresca el perfil con el detalle devuelto.
  async function ejecutarBajaReactivar() {
    if (!deportista) return;
    setBajaEnVuelo(true);
    setBajaError(null);
    try {
      const esBaja = deportista.activo;
      const actualizado = esBaja
        ? await api.darBajaDeportista(deportista.id)
        : await api.reactivarDeportista(deportista.id);
      setDeportista(actualizado);
      setConfirmando(false);
      toast.success(esBaja ? 'Deportista dado de baja' : 'Deportista reactivado');
    } catch (err) {
      let msg = 'No se pudo conectar con el servidor.';
      if (err instanceof ApiError) {
        msg =
          err.status === 404
            ? 'El deportista ya no existe.'
            : err.isForbidden
              ? 'No tienes permiso para esta acción.'
              : err.message;
      }
      setBajaError(msg);
      toast.error(msg);
    } finally {
      setBajaEnVuelo(false);
    }
  }

  useEffect(() => {
    if (!id) return;
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    api
      .deportista(id, controller.signal)
      .then((data) => {
        if (active) setDeportista(data);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        if (err instanceof ApiError) {
          setError(
            err.status === 404
              ? 'Deportista no encontrado.'
              : err.isForbidden
                ? 'No tienes acceso a este deportista.'
                : err.message,
          );
        } else {
          setError('No se pudo cargar el perfil del deportista.');
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [id]);

  if (loading) {
    return <div className="perfil__state">Cargando perfil…</div>;
  }

  if (error || !deportista) {
    return (
      <div className="perfil">
        <Link to="/deportistas" className="perfil__back">
          ← Volver a deportistas
        </Link>
        <div className="page-error" role="alert">
          {error ?? 'No se pudo cargar el deportista.'}
        </div>
      </div>
    );
  }

  const categoriaLabel = deportista.categoria
    ? `${deportista.categoria.nombre} ${nivelLabel(deportista.categoria.nivel)}`.trim()
    : null;

  // Un deportista puede tener VARIAS inscripciones (una por disciplina). La "cuota
  // mensual" del encabezado es la SUMA de las cuotas de las inscripciones ACTIVAS; y
  // "Deportista desde" es la fecha de inscripción más temprana entre las activas.
  const inscripcionesActivas = deportista.inscripciones.filter((i) => i.estado === 'ACTIVA');
  const cuotaMensualTotal = inscripcionesActivas.reduce(
    (sum, i) => sum + Number(i.monto_mensual),
    0,
  );
  const fechaDesde =
    inscripcionesActivas.length > 0
      ? inscripcionesActivas.reduce(
          (min, i) => (i.fecha_inscripcion < min ? i.fecha_inscripcion : min),
          inscripcionesActivas[0].fecha_inscripcion,
        )
      : null;

  const tabs: TabItem[] = [
    {
      id: 'datos',
      label: 'Datos personales',
      content: (
        <Card>
          <dl className="datalist">
            <DataRow label="Apellido paterno" value={deportista.ap_paterno} />
            <DataRow label="Apellido materno" value={deportista.ap_materno} />
            <DataRow label="Nombres" value={deportista.nombres} />
            <DataRow label="CI" value={deportista.ci} />
            <DataRow
              label="Fecha de nacimiento"
              value={`${formatDate(deportista.fecha_nac)} (${deportista.edad} años)`}
            />
            <DataRow label="Disciplina" value={deportista.disciplina} />
            <DataRow label="Categoría" value={categoriaLabel ?? 'Sin categoría'} />
            <DataRow label="Sucursal" value={deportista.sucursal.nombre} />
            {deportista.lugar_nacimiento && (
              <DataRow label="Lugar de nacimiento" value={deportista.lugar_nacimiento} />
            )}
            {deportista.domicilio && (
              <DataRow label="Domicilio" value={deportista.domicilio} />
            )}
          </dl>
        </Card>
      ),
    },
    {
      id: 'tutores',
      label: 'Tutores y emergencia',
      content: (
        <div className="perfil__stack">
          <Card title="Contacto de emergencia">
            <p className="perfil__emergency">{deportista.contacto_emergencia || '—'}</p>
          </Card>
          <Card title={`Tutores (${deportista.tutores.length})`} padded={false}>
            {deportista.tutores.length === 0 ? (
              <p className="perfil__empty">Sin tutores registrados.</p>
            ) : (
              <ul className="tutor-list">
                {deportista.tutores.map((t) => (
                  <li key={t.id} className="tutor-list__item">
                    <Avatar name={t.nombres} size="md" />
                    <div className="tutor-list__body">
                      <div className="tutor-list__head">
                        <span className="tutor-list__name">{t.nombres}</span>
                        {t.responsable_pago && (
                          <Badge tone="accent">Responsable de pago</Badge>
                        )}
                      </div>
                      <span className="tutor-list__meta">
                        {t.parentesco} · {t.telefono} · CI {t.ci}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      ),
    },
    {
      id: 'ficha',
      label: 'Ficha médica',
      content: (
        <Card
          title="Ficha médica"
          actions={
            deportista.consentimiento ? (
              <Badge tone="paid">✓ Consentimiento del tutor</Badge>
            ) : null
          }
        >
          {deportista.ficha_medica ? (
            <dl className="datalist">
              <DataRow label="Tipo de sangre" value={deportista.ficha_medica.tipo_sangre} />
              <DataRow label="Alergias" value={deportista.ficha_medica.alergias} />
              <DataRow label="Condiciones" value={deportista.ficha_medica.condiciones} />
            </dl>
          ) : (
            <div className="perfil__restricted" role="note">
              Información visible solo para administradores y entrenador de la categoría.
            </div>
          )}
        </Card>
      ),
    },
    {
      id: 'inscripcion',
      label: 'Inscripción',
      content: (
        <Card>
          {deportista.inscripciones.length === 0 ? (
            <p className="perfil__empty">Sin inscripción registrada.</p>
          ) : (
            <div className="perfil-insc-list">
              {deportista.inscripciones.map((insc) => (
                <div key={insc.id} className="perfil-insc">
                  <dl className="datalist">
                    <DataRow label="Disciplina" value={insc.disciplina_nombre ?? '—'} />
                    <DataRow
                      label="Cuota mensual"
                      value={<span className="tabular">{formatMoney(insc.monto_mensual)}</span>}
                    />
                    <DataRow
                      label="Fecha de inscripción"
                      value={formatDate(insc.fecha_inscripcion)}
                    />
                    <DataRow
                      label="Estado"
                      value={
                        <Badge tone={insc.estado === 'ACTIVA' ? 'paid' : 'neutral'}>
                          {insc.estado === 'ACTIVA' ? 'Activa' : 'Inactiva'}
                        </Badge>
                      }
                    />
                  </dl>
                </div>
              ))}
            </div>
          )}
        </Card>
      ),
    },
    {
      id: 'cuotas',
      label: 'Cuotas',
      content: <CuotasDeportista deportistaId={deportista.id} isAdmin={isAdmin} />,
    },
    {
      id: 'pagos',
      label: 'Historial de pagos',
      content: <HistorialPagos deportistaId={deportista.id} />,
    },
  ];

  return (
    <div className="perfil">
      <Link to="/deportistas" className="perfil__back">
        ← Volver a deportistas
      </Link>

      <header className="perfil__header">
        <Avatar name={deportista.nombre_completo} size="lg" />
        <div className="perfil__header-main">
          <div className="perfil__name-row">
            <h1 className="perfil__name">{deportista.nombre_completo}</h1>
            {/* Badge "Inactivo": soft-delete (epic escuela-y-bajas, Fase 2). */}
            {!deportista.activo && <Badge tone="neutral">Inactivo</Badge>}
          </div>
          <div className="perfil__tags">
            {categoriaLabel && <Badge tone="accent">{categoriaLabel}</Badge>}
            <span className="perfil__tag-text">{deportista.disciplina}</span>
            <span className="perfil__dot" aria-hidden="true">
              ·
            </span>
            <span className="perfil__tag-text">Sucursal {deportista.sucursal.nombre}</span>
          </div>
          <dl className="perfil__facts">
            <div>
              <dt>CI</dt>
              <dd className="tabular">{deportista.ci}</dd>
            </div>
            {inscripcionesActivas.length > 0 && (
              <div>
                <dt>Cuota mensual</dt>
                <dd className="tabular">{formatMoney(cuotaMensualTotal)}</dd>
              </div>
            )}
            {fechaDesde && (
              <div>
                <dt>Deportista desde</dt>
                <dd>{formatDate(fechaDesde)}</dd>
              </div>
            )}
          </dl>
        </div>

        {/* Acciones — SOLO ADMIN (el coach es lectura; el backend da 403/422 a
            ENTRENADOR). Editar (Fase 3) abre el formulario en modo edición;
            baja/reactivar (Fase 2) pide confirmación antes de ejecutar. */}
        {isAdmin && (
          <div className="perfil__acciones">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => navigate(`/deportistas/${deportista.id}/editar`)}
            >
              Editar
            </Button>
            {deportista.activo ? (
              <Button
                variant="danger"
                size="sm"
                onClick={() => {
                  setBajaError(null);
                  setConfirmando(true);
                }}
              >
                Dar de baja
              </Button>
            ) : (
              <Button
                variant="primary"
                size="sm"
                onClick={() => {
                  setBajaError(null);
                  setConfirmando(true);
                }}
              >
                Reactivar
              </Button>
            )}
          </div>
        )}
      </header>

      {bajaError && (
        <div className="page-error" role="alert">
          {bajaError}
        </div>
      )}

      {isAdmin && confirmando && (
        <div
          className="perfil__confirm-backdrop"
          role="dialog"
          aria-modal="true"
          aria-label={
            deportista.activo ? 'Confirmar baja del deportista' : 'Confirmar reactivación'
          }
          onClick={(e) => {
            if (e.target === e.currentTarget && !bajaEnVuelo) setConfirmando(false);
          }}
        >
          <div className="perfil__confirm">
            <Card title={deportista.activo ? 'Dar de baja' : 'Reactivar deportista'}>
              <p className="perfil__confirm-text">
                {deportista.activo ? (
                  <>
                    ¿Seguro que quieres dar de baja a{' '}
                    <strong>{deportista.nombre_completo}</strong>? Se ocultará de los
                    listados activos, pero se conserva todo su historial y puedes
                    reactivarlo cuando quieras.
                  </>
                ) : (
                  <>
                    ¿Reactivar a <strong>{deportista.nombre_completo}</strong>? Volverá a
                    aparecer en los listados activos.
                  </>
                )}
              </p>
              <div className="perfil__confirm-actions">
                <Button
                  variant="secondary"
                  onClick={() => setConfirmando(false)}
                  disabled={bajaEnVuelo}
                >
                  Cancelar
                </Button>
                <Button
                  variant={deportista.activo ? 'danger' : 'primary'}
                  onClick={ejecutarBajaReactivar}
                  disabled={bajaEnVuelo}
                >
                  {bajaEnVuelo
                    ? 'Procesando…'
                    : deportista.activo
                      ? 'Sí, dar de baja'
                      : 'Sí, reactivar'}
                </Button>
              </div>
            </Card>
          </div>
        </div>
      )}

      <Tabs items={tabs} />
    </div>
  );
}
