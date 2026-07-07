import { useCallback, useEffect, useMemo, useState } from 'react';
import { api, ApiError } from '@/api/client';
import type {
  EntrenadorOut,
  EstadoRecordatorioDeudores,
  RecordatorioDeudoresResult,
} from '@/api/types';
import { Badge, Button, Card, DataTable, useToast, type Column } from '@/components/ui';
import { formatMoney } from '@/lib/format';
import { NuevoEntrenador } from './NuevoEntrenador';
import './Entrenadores.css';

// Tono del badge por estado del recordatorio (verde=enviado, ámbar=sin deudores,
// rojo=fallido). Reusa el sistema verde/ámbar/rojo del design-system.
const ESTADO_RECORDATORIO_TONE: Record<
  EstadoRecordatorioDeudores,
  'paid' | 'pending' | 'overdue'
> = {
  ENVIADO: 'paid',
  SIN_DEUDORES: 'pending',
  FALLIDO: 'overdue',
};

const ESTADO_RECORDATORIO_LABEL: Record<EstadoRecordatorioDeudores, string> = {
  ENVIADO: 'Enviado',
  SIN_DEUDORES: 'Sin deudores',
  FALLIDO: 'Fallido',
};

// Pantalla de gestión de entrenadores (Epic B). SOLO ADMIN (la ruta y el item de
// nav ya están gateados; el backend da 403 a ENTRENADOR en las escrituras).
// Lista (nombres, email, especialidad, chips de disciplinas, badge activo) +
// alta + edición (incl. baja/reactivación con activo).
export function Entrenadores() {
  const toast = useToast();
  const [items, setItems] = useState<EntrenadorOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filtro: mostrar también los dados de baja (activo=false).
  const [soloActivos, setSoloActivos] = useState(false);

  // Alta/edición + recarga.
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<EntrenadorOut | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  // Baja/reactivación directa desde la fila (epic escuela-y-bajas, Fase 2):
  // entrenador a confirmar, request en vuelo (deshabilita el botón) y error de
  // la acción. Reusa el contrato existente (PUT /entrenadores/{id} con activo).
  const [confirmandoBaja, setConfirmandoBaja] = useState<EntrenadorOut | null>(null);
  const [bajaEnVuelo, setBajaEnVuelo] = useState(false);
  const [bajaError, setBajaError] = useState<string | null>(null);

  // Recordatorio de deudores: id del entrenador con la request en vuelo (deshabilita
  // su botón para evitar doble envío), resultado a mostrar y error si falló la red.
  const [enviandoId, setEnviandoId] = useState<string | null>(null);
  const [resultado, setResultado] = useState<{
    entrenador: EntrenadorOut;
    data: RecordatorioDeudoresResult;
  } | null>(null);
  const [resultadoError, setResultadoError] = useState<{
    entrenador: EntrenadorOut;
    mensaje: string;
  } | null>(null);

  // Dispara el digest de deudores del entrenador. El botón queda deshabilitado
  // mientras la request está en vuelo (no se permite doble envío).
  const enviarResumen = useCallback(
    async (entrenador: EntrenadorOut) => {
      // Evita doble envío: si ya hay una request en vuelo, ignora el clic.
      let yaEnVuelo = false;
      setEnviandoId((prev) => {
        if (prev) yaEnVuelo = true;
        return entrenador.id;
      });
      if (yaEnVuelo) return;
      setResultado(null);
      setResultadoError(null);
      try {
        const data = await api.enviarRecordatorioDeudores(entrenador.id);
        setResultado({ entrenador, data });
        toast.success(`${data.enviados} recordatorio(s) enviado(s)`);
      } catch (err) {
        const mensaje =
          err instanceof ApiError
            ? err.status === 404
              ? 'Ese entrenador ya no existe.'
              : err.isForbidden
                ? 'No tienes permiso para enviar el resumen.'
                : err.message
            : 'No se pudo conectar con el servidor.';
        setResultadoError({ entrenador, mensaje });
        toast.error(mensaje);
      } finally {
        setEnviandoId(null);
      }
    },
    [toast],
  );

  // Da de baja / reactiva (soft-delete reversible) vía el contrato existente
  // (PUT /entrenadores/{id} con activo). Tras confirmar, recarga la lista.
  async function ejecutarBajaReactivar(entrenador: EntrenadorOut) {
    setBajaEnVuelo(true);
    setBajaError(null);
    try {
      await api.updateEntrenador(entrenador.id, { activo: !entrenador.activo });
      toast.success('Entrenador actualizado');
      setConfirmandoBaja(null);
      recargar();
    } catch (err) {
      const mensaje =
        err instanceof ApiError
          ? err.status === 404
            ? 'Ese entrenador ya no existe.'
            : err.isForbidden
              ? 'No tienes permiso para esta acción.'
              : err.message
          : 'No se pudo conectar con el servidor.';
      setBajaError(mensaje);
      toast.error(mensaje);
    } finally {
      setBajaEnVuelo(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    api
      .listEntrenadores(soloActivos || undefined, controller.signal)
      .then((data) => {
        if (active) setItems(data);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setError(
          err instanceof ApiError ? err.message : 'No se pudieron cargar los entrenadores',
        );
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [soloActivos, reloadKey]);

  function recargar() {
    setReloadKey((k) => k + 1);
  }

  function abrirNuevo() {
    setEditing(null);
    setModalOpen(true);
  }

  function abrirEditar(entrenador: EntrenadorOut) {
    setEditing(entrenador);
    setModalOpen(true);
  }

  const total = items.length;

  const columns = useMemo<Column<EntrenadorOut>[]>(
    () => [
      {
        key: 'nombres',
        header: 'Entrenador',
        render: (e) => (
          <div className="entrenador-cell">
            <span className="entrenador-cell__nombre">{e.nombres}</span>
            <span className="entrenador-cell__email">{e.email}</span>
          </div>
        ),
      },
      {
        key: 'especialidad',
        header: 'Especialidad',
        hideOnNarrow: true,
        render: (e) =>
          e.especialidad ? (
            e.especialidad
          ) : (
            <span className="entrenador-cell__muted">—</span>
          ),
      },
      {
        key: 'disciplinas',
        header: 'Disciplinas',
        render: (e) =>
          e.disciplinas.length > 0 ? (
            <div className="entrenador-chips">
              {e.disciplinas.map((d) => (
                <Badge key={d.id} tone="accent">
                  {d.nombre}
                </Badge>
              ))}
            </div>
          ) : (
            <span className="entrenador-cell__muted">—</span>
          ),
      },
      {
        key: 'activo',
        header: 'Estado',
        align: 'center',
        render: (e) =>
          e.activo ? (
            <Badge tone="paid">Activo</Badge>
          ) : (
            <Badge tone="neutral">Inactivo</Badge>
          ),
      },
      {
        key: 'acciones',
        header: '',
        align: 'right',
        render: (e) => (
          <div className="entrenadores__acciones">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => enviarResumen(e)}
              disabled={enviandoId === e.id}
            >
              {enviandoId === e.id ? 'Enviando…' : 'Enviar resumen de deudores'}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => abrirEditar(e)}>
              Editar
            </Button>
            {/* Baja/Reactivación DIRECTA (fuera del modal Editar), con
                confirmación. Soft-delete reversible (epic escuela-y-bajas). */}
            <Button
              variant={e.activo ? 'danger' : 'primary'}
              size="sm"
              onClick={() => {
                setBajaError(null);
                setConfirmandoBaja(e);
              }}
            >
              {e.activo ? 'Dar de baja' : 'Reactivar'}
            </Button>
          </div>
        ),
      },
    ],
    [enviandoId, enviarResumen],
  );

  return (
    <div className="entrenadores">
      <header className="page-head">
        <div>
          <h1 className="page-head__title">Entrenadores</h1>
          <p className="page-head__subtitle">
            {loading
              ? 'Cargando…'
              : `${total} entrenador${total === 1 ? '' : 'es'}`}
          </p>
        </div>
        <Button variant="primary" onClick={abrirNuevo}>
          + Nuevo entrenador
        </Button>
      </header>

      {error && (
        <div className="page-error" role="alert">
          {error}
        </div>
      )}

      <label className="entrenadores__toggle">
        <input
          type="checkbox"
          checked={soloActivos}
          onChange={(e) => setSoloActivos(e.target.checked)}
        />
        Mostrar solo activos
      </label>

      <Card padded={false}>
        <DataTable
          ariaLabel="Lista de entrenadores"
          columns={columns}
          rows={items}
          rowKey={(e) => e.id}
          loading={loading}
          emptyMessage="Aún no hay entrenadores registrados"
        />
      </Card>

      {modalOpen && (
        <NuevoEntrenador
          entrenador={editing}
          onClose={() => setModalOpen(false)}
          onSaved={() => {
            setModalOpen(false);
            setEditing(null);
            recargar();
          }}
        />
      )}

      {confirmandoBaja && (
        <div
          className="entrenadores__modal-backdrop"
          role="dialog"
          aria-modal="true"
          aria-label={
            confirmandoBaja.activo
              ? 'Confirmar baja del entrenador'
              : 'Confirmar reactivación del entrenador'
          }
          onClick={(e) => {
            if (e.target === e.currentTarget && !bajaEnVuelo) setConfirmandoBaja(null);
          }}
        >
          <div className="entrenadores__modal">
            <Card
              title={confirmandoBaja.activo ? 'Dar de baja' : 'Reactivar entrenador'}
            >
              <p className="entrenadores__resumen-sub">
                {confirmandoBaja.activo ? (
                  <>
                    ¿Seguro que quieres dar de baja a{' '}
                    <strong>{confirmandoBaja.nombres}</strong>? Perderá el acceso
                    al sistema, pero se conserva su registro y puedes reactivarlo
                    cuando quieras.
                  </>
                ) : (
                  <>
                    ¿Reactivar a <strong>{confirmandoBaja.nombres}</strong>? Volverá
                    a poder iniciar sesión y aparecer en los listados activos.
                  </>
                )}
              </p>
              {bajaError && (
                <div className="page-error" role="alert">
                  {bajaError}
                </div>
              )}
              <div className="entrenadores__modal-actions">
                <Button
                  variant="secondary"
                  onClick={() => setConfirmandoBaja(null)}
                  disabled={bajaEnVuelo}
                >
                  Cancelar
                </Button>
                <Button
                  variant={confirmandoBaja.activo ? 'danger' : 'primary'}
                  onClick={() => ejecutarBajaReactivar(confirmandoBaja)}
                  disabled={bajaEnVuelo}
                >
                  {bajaEnVuelo
                    ? 'Procesando…'
                    : confirmandoBaja.activo
                      ? 'Sí, dar de baja'
                      : 'Sí, reactivar'}
                </Button>
              </div>
            </Card>
          </div>
        </div>
      )}

      {resultadoError && (
        <div
          className="entrenadores__modal-backdrop"
          role="dialog"
          aria-modal="true"
          aria-label="Error al enviar el resumen de deudores"
          onClick={(e) => {
            if (e.target === e.currentTarget) setResultadoError(null);
          }}
        >
          <div className="entrenadores__modal">
            <Card title="No se pudo enviar el resumen">
              <p className="entrenadores__resumen-sub">
                Entrenador: {resultadoError.entrenador.nombres}
              </p>
              <div className="page-error" role="alert">
                {resultadoError.mensaje}
              </div>
              <div className="entrenadores__modal-actions">
                <Button variant="primary" onClick={() => setResultadoError(null)}>
                  Entendido
                </Button>
              </div>
            </Card>
          </div>
        </div>
      )}

      {resultado && (
        <ResumenDeudores
          entrenador={resultado.entrenador}
          data={resultado.data}
          onClose={() => setResultado(null)}
        />
      )}
    </div>
  );
}

// Resumen legible del digest de deudores devuelto por el backend: por sucursal,
// nº de deudores, monto adeudado y estado (Enviado / Sin deudores / Fallido).
// Si TODAS las sucursales vinieron en FALLIDO con al menos una sucursal asignada,
// el caso típico es "entrenador sin teléfono" -> aviso claro (CONTRATO 4).
function ResumenDeudores({
  entrenador,
  data,
  onClose,
}: {
  entrenador: EntrenadorOut;
  data: RecordatorioDeudoresResult;
  onClose: () => void;
}) {
  const sucursales = data.sucursales;
  const sinTelefono =
    !entrenador.telefono &&
    sucursales.length > 0 &&
    sucursales.every((s) => s.estado === 'FALLIDO');

  return (
    <div
      className="entrenadores__modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label="Resumen de deudores enviado"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="entrenadores__modal">
        <Card title="Resumen de deudores">
          <p className="entrenadores__resumen-sub">
            Entrenador: {entrenador.nombres} · {data.enviados} mensaje
            {data.enviados === 1 ? '' : 's'} enviado
            {data.enviados === 1 ? '' : 's'}
          </p>

          {sinTelefono && (
            <div className="page-error" role="alert">
              El entrenador no tiene teléfono registrado. Edítalo para añadir su
              número de WhatsApp y poder enviarle el resumen.
            </div>
          )}

          {sucursales.length === 0 ? (
            <p className="entrenador-cell__muted">
              El entrenador no tiene sucursales asignadas. Asígnale al menos una
              desde «Editar».
            </p>
          ) : (
            <ul className="entrenadores__resumen-list" aria-label="Resumen por sucursal">
              {sucursales.map((s) => (
                <li key={s.sucursal_id} className="entrenadores__resumen-item">
                  <div className="entrenadores__resumen-item-head">
                    <span className="entrenadores__resumen-suc">{s.sucursal_nombre}</span>
                    <Badge tone={ESTADO_RECORDATORIO_TONE[s.estado]}>
                      {ESTADO_RECORDATORIO_LABEL[s.estado]}
                    </Badge>
                  </div>
                  <span className="entrenador-cell__email">
                    {s.num_deudores} deudor{s.num_deudores === 1 ? '' : 'es'} ·{' '}
                    <span className="tabular">{formatMoney(s.monto_total)}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}

          <div className="entrenadores__modal-actions">
            <Button variant="primary" onClick={onClose}>
              Cerrar
            </Button>
          </div>
        </Card>
      </div>
    </div>
  );
}
