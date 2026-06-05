"""Wiring de adaptadores (selección por configuración, no hardcodeada en el dominio).

Los routers/tasks piden aquí las implementaciones concretas de los puertos. El
dominio nunca importa estos adaptadores (import-linter); este módulo de aplicación
(`app.services`) sí puede.
"""

from __future__ import annotations

from app.adapters.comprobante.pdf import PdfComprobanteService
from app.adapters.notifications.noop import NoopNotificationService
from app.adapters.openbcb.provider import OpenBcbSandboxProvider
from app.domain.ports.invoice import ComprobanteService
from app.domain.ports.notification import NotificationService
from app.domain.ports.payment import PaymentProvider


def get_comprobante_service() -> ComprobanteService:
    """Comprobante PDF (fpdf2)."""
    return PdfComprobanteService()


def get_notification_service() -> NotificationService:
    """Notificaciones: hoy Noop (WhatsApp real en epic posterior, RNF-07)."""
    return NoopNotificationService()


def get_payment_provider() -> PaymentProvider:
    """Proveedor de cobro QR: sandbox OpenBCB (real requiere onboarding BCB)."""
    return OpenBcbSandboxProvider()
