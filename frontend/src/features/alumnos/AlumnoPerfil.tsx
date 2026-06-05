import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, ApiError } from '@/api/client';
import type { AlumnoDetail } from '@/api/types';
import { Avatar, Badge, Card, Tabs, type TabItem } from '@/components/ui';
import { formatDate, formatMoney, nivelLabel } from '@/lib/format';
import './AlumnoPerfil.css';

function DataRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="datarow">
      <dt className="datarow__label">{label}</dt>
      <dd className="datarow__value">{value || '—'}</dd>
    </div>
  );
}

export function AlumnoPerfil() {
  const { id } = useParams<{ id: string }>();
  const [alumno, setAlumno] = useState<AlumnoDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    api
      .alumno(id, controller.signal)
      .then((data) => {
        if (active) setAlumno(data);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        if (err instanceof ApiError) {
          setError(
            err.status === 404
              ? 'Alumno no encontrado.'
              : err.isForbidden
                ? 'No tienes acceso a este alumno.'
                : err.message,
          );
        } else {
          setError('No se pudo cargar el perfil del alumno.');
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

  if (error || !alumno) {
    return (
      <div className="perfil">
        <Link to="/alumnos" className="perfil__back">
          ← Volver a alumnos
        </Link>
        <div className="page-error" role="alert">
          {error ?? 'No se pudo cargar el alumno.'}
        </div>
      </div>
    );
  }

  const categoriaLabel = alumno.categoria
    ? `${alumno.categoria.nombre} ${nivelLabel(alumno.categoria.nivel)}`.trim()
    : null;

  const tabs: TabItem[] = [
    {
      id: 'datos',
      label: 'Datos personales',
      content: (
        <Card>
          <dl className="datalist">
            <DataRow label="Apellido paterno" value={alumno.ap_paterno} />
            <DataRow label="Apellido materno" value={alumno.ap_materno} />
            <DataRow label="Nombres" value={alumno.nombres} />
            <DataRow label="CI" value={alumno.ci} />
            <DataRow
              label="Fecha de nacimiento"
              value={`${formatDate(alumno.fecha_nac)} (${alumno.edad} años)`}
            />
            <DataRow label="Disciplina" value={alumno.disciplina} />
            <DataRow label="Categoría" value={categoriaLabel ?? 'Sin categoría'} />
            <DataRow label="Sucursal" value={alumno.sucursal.nombre} />
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
            <p className="perfil__emergency">{alumno.contacto_emergencia || '—'}</p>
          </Card>
          <Card title={`Tutores (${alumno.tutores.length})`} padded={false}>
            {alumno.tutores.length === 0 ? (
              <p className="perfil__empty">Sin tutores registrados.</p>
            ) : (
              <ul className="tutor-list">
                {alumno.tutores.map((t) => (
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
            alumno.consentimiento ? (
              <Badge tone="paid">✓ Consentimiento del tutor</Badge>
            ) : null
          }
        >
          {alumno.ficha_medica ? (
            <dl className="datalist">
              <DataRow label="Tipo de sangre" value={alumno.ficha_medica.tipo_sangre} />
              <DataRow label="Alergias" value={alumno.ficha_medica.alergias} />
              <DataRow label="Condiciones" value={alumno.ficha_medica.condiciones} />
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
          {alumno.inscripcion ? (
            <dl className="datalist">
              <DataRow label="Disciplina" value={alumno.inscripcion.disciplina} />
              <DataRow
                label="Cuota mensual"
                value={<span className="tabular">{formatMoney(alumno.inscripcion.monto_mensual)}</span>}
              />
              <DataRow
                label="Fecha de inscripción"
                value={formatDate(alumno.inscripcion.fecha_inscripcion)}
              />
              <DataRow
                label="Estado"
                value={
                  <Badge tone={alumno.inscripcion.estado === 'ACTIVA' ? 'paid' : 'neutral'}>
                    {alumno.inscripcion.estado === 'ACTIVA' ? 'Activa' : 'Inactiva'}
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
      <Link to="/alumnos" className="perfil__back">
        ← Volver a alumnos
      </Link>

      <header className="perfil__header">
        <Avatar name={alumno.nombre_completo} size="lg" />
        <div className="perfil__header-main">
          <h1 className="perfil__name">{alumno.nombre_completo}</h1>
          <div className="perfil__tags">
            {categoriaLabel && <Badge tone="accent">{categoriaLabel}</Badge>}
            <span className="perfil__tag-text">{alumno.disciplina}</span>
            <span className="perfil__dot" aria-hidden="true">
              ·
            </span>
            <span className="perfil__tag-text">Sucursal {alumno.sucursal.nombre}</span>
          </div>
          <dl className="perfil__facts">
            <div>
              <dt>CI</dt>
              <dd className="tabular">{alumno.ci}</dd>
            </div>
            {alumno.inscripcion && (
              <div>
                <dt>Cuota mensual</dt>
                <dd className="tabular">{formatMoney(alumno.inscripcion.monto_mensual)}</dd>
              </div>
            )}
            {alumno.inscripcion && (
              <div>
                <dt>Alumno desde</dt>
                <dd>{formatDate(alumno.inscripcion.fecha_inscripcion)}</dd>
              </div>
            )}
          </dl>
        </div>
      </header>

      <Tabs items={tabs} />
    </div>
  );
}
