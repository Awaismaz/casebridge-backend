"""Inbound connector event handling: verify → land idempotently → apply.

Applying is one-directional (CMS → portal). The canonical stage ladder is the
target; a per-firm stage_map translates the source's stage codes onto it.
"""

import hashlib
import hmac

from django.utils import timezone

from apps.cases.models import STAGE_ORDER, CaseStageEvent, PortalCase
from apps.clients.models import PortalClientUser
from apps.messaging.models import Notification
from apps.tenants.context import firm_context

from .models import ConnectorConfig, InboundEvent


def verify_signature(secret: str, raw_body: bytes, signature: str) -> bool:
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def land_event(firm, event_type, idempotency_key, source, payload) -> tuple[InboundEvent, bool]:
    """Idempotent landing. Returns (event, created)."""
    existing = InboundEvent.objects_unscoped.filter(
        firm=firm, idempotency_key=idempotency_key
    ).first()
    if existing:
        return existing, False
    ev = InboundEvent.objects_unscoped.create(
        firm=firm,
        idempotency_key=idempotency_key,
        event_type=event_type,
        source=source,
        payload=payload,
    )
    return ev, True


def _map_stage(config, raw_stage):
    if not raw_stage:
        return None
    mapped = (config.stage_map or {}).get(raw_stage)
    if mapped in STAGE_ORDER:
        return mapped
    if raw_stage in STAGE_ORDER:  # already canonical
        return raw_stage
    return None


def apply_event(event: InboundEvent) -> None:
    """Apply one landed event within its firm context. Raises on failure so the
    caller can mark it failed/dead and alert."""
    config = ConnectorConfig.objects.filter(firm=event.firm).first()
    with firm_context(event.firm_id):
        event.attempts += 1
        p = event.payload or {}
        try:
            if event.event_type == "client.upserted":
                _apply_client(event.firm, p)
            elif event.event_type == "case.upserted":
                _apply_case(event.firm, config, p)
            elif event.event_type == "case.closed":
                _close_case(event.firm, p)
            elif event.event_type in ("document.added", "contact.logged", "appointment.upcoming"):
                _touch_case(event.firm, p, event.event_type)
            event.status = InboundEvent.Status.APPLIED
            event.applied_at = timezone.now()
            event.error = ""
        except Exception as exc:  # noqa: BLE001
            event.status = (
                InboundEvent.Status.DEAD if event.attempts >= 5 else InboundEvent.Status.FAILED
            )
            event.error = str(exc)[:500]
            event.save()
            raise
        event.save()
        if config:
            config.last_event_at = timezone.now()
            config.save(update_fields=["last_event_at"])


def _apply_client(firm, p):
    ext_id = str(p.get("external_id") or "")
    client = PortalClientUser.objects_unscoped.filter(
        firm=firm, email__iexact=p.get("email", "")
    ).first()
    if client is None:
        client = PortalClientUser.objects_unscoped.create(
            firm=firm,
            name=p.get("name", "Client"),
            email=p.get("email", ""),
            phone=p.get("phone", ""),
            preferred_language=p.get("preferred_language", "en"),
            status="active",
        )
    else:
        for f in ("name", "phone"):
            if p.get(f):
                setattr(client, f, p[f])
        client.save()
    return client


def _apply_case(firm, config, p):
    ext_source = p.get("source", "pm")
    ext_id = str(p.get("external_id") or "")
    client = PortalClientUser.objects_unscoped.filter(
        firm=firm, email__iexact=p.get("client_email", "")
    ).first()
    if client is None:
        client = _apply_client(firm, {"name": p.get("client_name", "Client"),
                                      "email": p.get("client_email", "")})
    case = PortalCase.objects_unscoped.filter(
        firm=firm, external_source=ext_source, external_id=ext_id
    ).first()
    canonical = _map_stage(config, p.get("stage")) if config else p.get("stage")
    if case is None:
        case = PortalCase.objects_unscoped.create(
            firm=firm, client=client,
            title=p.get("title", "Case"),
            case_type=p.get("case_type", "Motor Vehicle Accident"),
            external_source=ext_source, external_id=ext_id,
            canonical_stage=canonical or "intake",
            stage_label_raw=p.get("stage", ""),
        )
    else:
        if canonical and canonical != case.canonical_stage:
            CaseStageEvent.objects_unscoped.create(
                firm=firm, case=case, from_stage=case.canonical_stage,
                to_stage=canonical, note="Synced from case management system",
            )
            Notification.objects_unscoped.create(
                firm=firm, case=case, kind="stage_move",
                title=f"Your case moved to {canonical.title()}",
            )
            case.canonical_stage = canonical
        case.stage_label_raw = p.get("stage", case.stage_label_raw)
        case.save()
    return case


def _close_case(firm, p):
    case = PortalCase.objects_unscoped.filter(
        firm=firm, external_source=p.get("source", "pm"),
        external_id=str(p.get("external_id") or ""),
    ).first()
    if case:
        case.status = "closed"
        case.canonical_stage = "closed"
        case.save()


def _touch_case(firm, p, event_type):
    case = PortalCase.objects_unscoped.filter(
        firm=firm, external_source=p.get("source", "pm"),
        external_id=str(p.get("external_id") or ""),
    ).first()
    if case:
        case.last_firm_touch_at = timezone.now()
        case.save(update_fields=["last_firm_touch_at"])
