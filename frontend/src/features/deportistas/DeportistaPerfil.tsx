import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api, ApiError } from '@/api/client';
import { useAuth } from '@/auth/useAuth';
import type { DeportistaDetail } from '@/api/types';
import { Avatar, Badge, Button, Card, Tabs, type TabItem } from '@/components/ui';
import { formatDate, formatMoney, nivelLabel } from '@/lib/format';
import './DeportistaPerfil.css';

function DataRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="datarow">
      <dt className="datarow__label">{label}</dt>
      <dd className="datarow__value">{value || '—'}</dd>
    </div>
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
      const actualizado = deportista.activo
        ? await api.darBajaDeportista(deportista.id)
        : await api.reactivarDeportista(deportista.id);
      setDeportista(actualizado);
      setConfirmando(false);
    } catch (err) {
      if (err instanceof ApiError) {
        setBajaError(
          err.status === 404
            ? 'El deportista ya no existe.'
            : err.isForbidden
              ? 'No tienes permiso para esta acción.'
              : err.message,
        );
      } else {
        setBajaError('No se pudo conectar con el servidor.');
      }
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
          {deportista.inscripcion ? (
            <dl className="datalist">
              <DataRow label="Disciplina" value={deportista.inscripcion.disciplina} />
              <DataRow
                label="Cuota mensual"
                value={<span className="tabular">{formatMoney(deportista.inscripcion.monto_mensual)}</span>}
              />
              <DataRow
                label="Fecha de inscripción"
                value={formatDate(deportista.inscripcion.fecha_inscripcion)}
              />
              <DataRow
                label="Estado"
                value={
                  <Badge tone={deportista.inscripcion.estado === 'ACTIVA' ? 'paid' : 'neutral'}>
                    {deportista.inscripcion.estado === 'ACTIVA' ? 'Activa' : 'Inactiva'}
                  </Badge>
                }
              />
            </dl>
          ) : (
            <p className="perfil__empty">Sin inscripción registrada.</p>
          )}
        </Card>
      ),
    },
    {
      id: 'pagos',
      label: 'Historial de pagos',
      content: (
        <Card>
          {/* Cobranza es otro epic. */}
          <p className="perfil__empty">Sin pagos aún.</p>
        </Card>
      ),
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
            {deportista.inscripcion && (
              <div>
                <dt>Cuota mensual</dt>
                <dd className="tabular">{formatMoney(deportista.inscripcion.monto_mensual)}</dd>
              </div>
            )}
            {deportista.inscripcion && (
              <div>
                <dt>Deportista desde</dt>
                <dd>{formatDate(deportista.inscripcion.fecha_inscripcion)}</dd>
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
