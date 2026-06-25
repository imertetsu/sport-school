"""Wiring de adaptadores (selección por configuración, no hardcodeada en el dominio).

Los routers/tasks piden aquí las implementaciones concretas de los puertos. El
dominio nunca importa estos adaptadores (import-linter); este módulo de aplicación
(`app.services`) sí puede.
"""

from __future__ import annotations

import logging

from app.adapters.comprobante.pdf import PdfComprobanteService
from app.adapters.notifications.noop import NoopNotificationService
from app.adapters.openbcb.provider import OpenBcbSandboxProvider
from app.adapters.whatsapp.gateway import GatewayWhatsAppAdapter
from app.adapters.whatsapp.meta import MetaCloudWhatsAppAdapter
from app.adapters.whatsapp.mock import MockWhatsAppAdapter
from app.core.config import settings
from app.domain.ports.invoice import ComprobanteService
from app.domain.ports.notification import NotificationService
from app.domain.ports.payment import PaymentProvider
from app.domain.ports.whatsapp import WhatsAppPort

logger = logging.getLogger(__name__)


def get_comprobante_service() -> ComprobanteService:
    """Comprobante PDF (fpdf2)."""
    return PdfComprobanteService()


def get_notification_service() -> NotificationService:
    """Notificaciones: hoy Noop (WhatsApp real en epic posterior, RNF-07)."""
    return NoopNotificationService()


def get_payment_provider() -> PaymentProvider:
    """Proveedor de cobro QR: sandbox OpenBCB (real requiere onboarding BCB)."""
    return OpenBcbSandboxProvider()


def get_whatsapp_port() -> WhatsAppPort:
    """Adaptador de WhatsApp, seleccionado por configuración (no hardcodeado).

    `whatsapp_provider == "meta"` **con** credenciales presentes
    (`whatsapp_phone_number_id` y `whatsapp_access_token` no vacíos) ⇒ adaptador
    real (`MetaCloudWhatsAppAdapter`). `whatsapp_provider == "gateway"` **con**
    `whatsapp_gateway_url` y `whatsapp_gateway_token` no vacíos ⇒ sidecar no-oficial
    (`GatewayWhatsAppAdapter`, epic whatsapp-gateway). Cualquier otro caso
    (`noop`/`mock`, o `meta`/`gateway` sin credenciales) ⇒ `MockWhatsAppAdapter`. Si
    era `meta`/`gateway` pero faltan credenciales, loguea WARNING. **Fail-safe:** nunca
    lanza en arranque; ante config incompleta degrada al mock para no tumbar el
    worker/API.
    """
    provider = (settings.whatsapp_provider or "").strip().lower()
    if provider == "meta":
        phone_id = (settings.whatsapp_phone_number_id or "").strip()
        token = (settings.whatsapp_access_token or "").strip()
        if phone_id and token:
            return MetaCloudWhatsAppAdapter()
        logger.warning(
            "whatsapp_provider=meta pero faltan credenciales "
            "(whatsapp_phone_number_id/whatsapp_access_token); usando MockWhatsAppAdapter"
        )
    elif provider == "gateway":
        url = (settings.whatsapp_gateway_url or "").strip()
        token = (settings.whatsapp_gateway_token or "").strip()
        if url and token:
            return GatewayWhatsAppAdapter()
        logger.warning(
            "whatsapp_provider=gateway pero faltan credenciales "
            "(whatsapp_gateway_url/whatsapp_gateway_token); usando MockWhatsAppAdapter"
        )
    return MockWhatsAppAdapter()
